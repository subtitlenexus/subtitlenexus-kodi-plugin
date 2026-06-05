"""Subtitle generation orchestration.

Per-file pipeline: cache lookup, audio extract, upload, poll-with-streaming-
partials, final SRT download. Logs via xbmc.log, progress via
xbmcgui.DialogProgressBG, and an optional xbmc.Player().setSubtitles()
refresh at the end so the new SRT loads into the active player.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import xbmc
import xbmcgui
import xbmcvfs

from .audio import AUDIO_CONTENT_TYPE, AUDIO_FORMAT, extract_audio, resolve_ffmpeg
from .nexus_api import NexusClient, NexusError, download_file
from .nexus_hash import oshash, sha256_endpoints
from .settings import Settings


LOG_PREFIX = "[Subtitle Nexus] "

POLL_INTERVAL_S = 20
POLL_MAX_WAIT_S = 60 * 45
INITIAL_POLL_DELAY_S = 15


def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    try:
        xbmc.log(LOG_PREFIX + msg, level)
    except Exception:
        pass


ProgressCb = Callable[[str, int, str], None]


def srt_output_path(video_path: Path, language: str) -> Path:
    """Standard sidecar caption layout: `<basename>.<lang>.srt`.

    Kodi auto-detects this naming convention next to the video file.
    """
    return video_path.with_name(f"{video_path.stem}.{language}.srt")


def _is_writable_dir(d: Path) -> bool:
    try:
        return os.access(str(d), os.W_OK)
    except OSError:
        return False


def resolve_output_path(video_path: Path, language: str,
                        userdata_dir: Optional[Path] = None) -> Path:
    """Prefer writing the SRT next to the video; fall back to userdata.

    Kodi will auto-pick up sidecar SRTs that share the basename of the video.
    If the video lives on a read-only mount (a common case on Kodi-on-TV
    deployments), we drop the SRT in the user profile dir and the caller is
    expected to wire it up via xbmc.Player().setSubtitles().
    """
    sidecar = srt_output_path(video_path, language)
    if _is_writable_dir(video_path.parent):
        return sidecar
    if userdata_dir is None:
        return sidecar
    userdata_dir.mkdir(parents=True, exist_ok=True)
    return userdata_dir / sidecar.name


def download_subtitle(client: NexusClient, subtitle_id: str, out_path: Path,
                      auto_purchase: bool) -> bool:
    try:
        link_data = client.download_link(subtitle_id)
    except NexusError as e:
        if e.code == "http_402" and auto_purchase:
            _log(f"Daily limit hit, purchasing subtitle {subtitle_id}")
            client.purchase(subtitle_id)
            link_data = client.download_link(subtitle_id)
        else:
            raise
    url = link_data.get("download_link")
    if not url:
        raise NexusError(f"No download_link in response: {link_data}")
    download_file(url, str(out_path))
    return True


def poll_and_stream(client: NexusClient, subtitle_id: str, out_path: Path,
                    auto_purchase: bool,
                    progress_cb: Optional[ProgressCb] = None) -> None:
    """Poll until COMPLETED, streaming partial SRT updates as Nexus produces them.

    On Kodi we keep writing the SRT to disk and let the caller (the player UI)
    refresh subtitles when the job finishes. If a progress_cb is provided we
    drive it on each percentage change.
    """
    time.sleep(INITIAL_POLL_DELAY_S)
    elapsed = INITIAL_POLL_DELAY_S
    last_progress = -1

    while elapsed < POLL_MAX_WAIT_S:
        try:
            status = client.poll_status(subtitle_id)
        except NexusError as e:
            _log(f"Poll error: {e}", xbmc.LOGWARNING)
            time.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            continue

        progress = int(status.get("progress") or 0)
        if progress != last_progress:
            _log(
                f"{subtitle_id} progress={progress}% "
                f"status={status.get('status')} has_file={status.get('has_file')}"
            )
            last_progress = progress
            if progress_cb:
                try:
                    progress_cb("transcribing", progress, f"{progress}%")
                except Exception:
                    pass

        if status.get("status") == "FAILED":
            raise NexusError(f"Subtitle request FAILED: {status.get('error_type')}")

        if status.get("has_file"):
            try:
                download_subtitle(client, subtitle_id, out_path, auto_purchase)
                _log(
                    f"Streamed SRT update ({out_path.stat().st_size} bytes, "
                    f"progress={progress}%)"
                )
            except NexusError as e:
                _log(f"Streaming download failed: {e}", xbmc.LOGWARNING)

        if status.get("status") == "COMPLETED":
            return

        time.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S
    raise NexusError(f"Polling exceeded {POLL_MAX_WAIT_S}s for {subtitle_id}")


def _maybe_set_player_subtitle(srt_path: Path) -> None:
    """Best-effort: if a video is currently playing, load the new SRT.

    Safe to call when nothing is playing — xbmc.Player().setSubtitles silently
    no-ops in that case in modern Kodi builds.
    """
    try:
        player = xbmc.Player()
        if player.isPlayingVideo():
            player.setSubtitles(str(srt_path))
            _log(f"Loaded SRT into current player: {srt_path.name}")
    except Exception as e:
        _log(f"Player.setSubtitles failed (non-fatal): {e}", xbmc.LOGWARNING)


def process_video(client: NexusClient, cfg: Settings, video_path: Path,
                  duration_seconds: int = 0,
                  userdata_dir: Optional[Path] = None,
                  progress_cb: Optional[ProgressCb] = None,
                  refresh_player: bool = True) -> dict:
    """Generate subtitles for a single video file.

    Returns a dict with keys:
      - result: 'cached' | 'generated' | 'skipped' | 'error'
      - srt_path: str | None
      - error: str | None
    """
    if not video_path.exists():
        return {"result": "skipped", "srt_path": None,
                "error": f"Path missing on disk: {video_path}"}

    out_path = resolve_output_path(video_path, cfg.subtitle_language, userdata_dir)
    _log(f"Processing: {video_path.name} ({duration_seconds}s) -> {out_path}")

    try:
        file_hash = oshash(video_path)
        file_hash_sha256 = sha256_endpoints(video_path)
    except OSError as e:
        _log(f"Hash failed for {video_path}: {e}", xbmc.LOGERROR)
        return {"result": "error", "srt_path": None, "error": f"Hash failed: {e}"}

    if not cfg.disable_subtitle_search:
        scope = "own" if cfg.ignore_community_subs else "all"
        try:
            if progress_cb:
                progress_cb("searching", 5, "Checking cache")
            res = client.search(file_hash, cfg.model, cfg.subtitle_language, scope)
            ids = (res or {}).get("subtitle_ids") or []
            if ids:
                _log(f"Cache hit: {ids[0]}")
                if progress_cb:
                    progress_cb("downloading", 90, "Downloading cached SRT")
                download_subtitle(client, ids[0], out_path,
                                  cfg.auto_purchase_past_daily_limit)
                if refresh_player:
                    _maybe_set_player_subtitle(out_path)
                if progress_cb:
                    progress_cb("done", 100, "Cached")
                return {"result": "cached", "srt_path": str(out_path), "error": None}
        except NexusError as e:
            _log(f"Cache search failed ({e.code}): {e}", xbmc.LOGWARNING)

    ffmpeg_bin = resolve_ffmpeg(cfg.ffmpeg_path)
    with tempfile.TemporaryDirectory(prefix="nexus_") as tmp:
        audio_path = Path(tmp) / f"{video_path.stem}.{AUDIO_FORMAT}"
        _log("Extracting audio...")
        if progress_cb:
            progress_cb("extracting", 10, "Extracting audio")
        extract_audio(video_path, audio_path, ffmpeg_bin)

        file_size = audio_path.stat().st_size
        _log(f"Uploading audio ({file_size / 1048576:.1f} MB)...")
        if progress_cb:
            progress_cb("uploading", 25, f"Uploading audio ({file_size // 1048576} MB)")
        start = client.upload_start(
            file_name=audio_path.name,
            content_type=AUDIO_CONTENT_TYPE,
            file_size=file_size,
            duration_seconds=duration_seconds,
            audio_language=cfg.audio_language,
        )
        upload_id = start["upload_id"]
        client.upload_to_s3(start["presigned_url"], str(audio_path),
                            AUDIO_CONTENT_TYPE)
        client.upload_finish(upload_id)

        _log("Submitting subtitle request...")
        if progress_cb:
            progress_cb("submitting", 40, "Submitting request")
        req = client.submit_subtitle_request(
            upload_id=upload_id,
            file_hash=file_hash,
            file_hash_sha256=file_hash_sha256,
            audio_language=cfg.audio_language,
            subtitle_language=cfg.subtitle_language,
            version=cfg.model,
            visibility=cfg.visibility,
        )
        subtitle_id = req["subtitle_id"]
        _log(f"Subtitle request: {subtitle_id}")

    _log("Waiting for transcription...")
    poll_and_stream(client, subtitle_id, out_path,
                    cfg.auto_purchase_past_daily_limit, progress_cb)

    _log("Downloading final SRT...")
    if progress_cb:
        progress_cb("downloading", 95, "Downloading final SRT")
    download_subtitle(client, subtitle_id, out_path,
                      cfg.auto_purchase_past_daily_limit)
    _log(f"Wrote: {out_path}")

    if refresh_player:
        _maybe_set_player_subtitle(out_path)

    if progress_cb:
        progress_cb("done", 100, "Done")
    return {"result": "generated", "srt_path": str(out_path), "error": None}



def userdata_subtitle_dir() -> Path:
    """Per-add-on profile dir where we drop SRTs when the video dir is RO."""
    import xbmcaddon
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    p = Path(profile) / "subtitles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def notify(msg: str, heading: str = "Subtitle Nexus",
           icon: str = xbmcgui.NOTIFICATION_INFO, ms: int = 5000) -> None:
    try:
        xbmcgui.Dialog().notification(heading, msg, icon, ms)
    except Exception:
        _log(f"notify failed; msg was: {msg}", xbmc.LOGWARNING)


def make_dialog_progress_cb(dialog: xbmcgui.DialogProgressBG) -> ProgressCb:
    def cb(phase: str, pct: int, detail: str) -> None:
        try:
            dialog.update(pct, "Subtitle Nexus", detail or phase)
        except Exception:
            pass
    return cb
