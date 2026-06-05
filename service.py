"""Kodi subtitle-provider extension point entry.

Bound via `<extension point="xbmc.subtitle.module" library="service.py"/>` in
addon.xml. Kodi invokes this script with `sys.argv` of the form:

  sys.argv[0] -> "plugin://service.subtitles.subtitlenexus/"
  sys.argv[1] -> handle (int)
  sys.argv[2] -> querystring beginning with '?', e.g.
                 "?action=search&languages=English"

Supported actions:
  - `search`          : auto-search using player metadata
  - `manualsearch`    : user-entered query (we ignore the query and use hash)
  - `download`        : user picked a subtitle; download and return its path

Discovery model:
  1. Hash the currently-playing local file.
  2. POST to /v1/subtitle/search/ with that hash.
  3. If cache hits -> list each as a downloadable subtitle.
  4. If cache misses -> list a single synthetic "Transcribe with Subtitle
     Nexus" entry. Selecting it kicks off the full pipeline (with a confirm
     prompt because it costs credits/tokens).
"""
from __future__ import annotations

import os
import shutil
import sys
import urllib.parse
from pathlib import Path

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.generator import (
    download_subtitle,
    make_dialog_progress_cb,
    notify,
    process_video,
    resolve_output_path,
    userdata_subtitle_dir,
)
from resources.lib.nexus_api import NexusClient, NexusError
from resources.lib.nexus_hash import oshash
from resources.lib.settings import Settings


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
TEMP_DIR = Path(PROFILE) / "temp"

LOG_PREFIX = "[Subtitle Nexus] "


def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(LOG_PREFIX + msg, level)


def _parse_params(qs: str) -> dict:
    if qs.startswith("?"):
        qs = qs[1:]
    out: dict[str, str] = {}
    for k, v in urllib.parse.parse_qsl(qs, keep_blank_values=True):
        out[k] = v
    return out


def _ensure_temp() -> None:
    if TEMP_DIR.exists():
        try:
            shutil.rmtree(TEMP_DIR)
        except OSError:
            pass
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def _current_video_path() -> str:
    """Get the path of the currently playing video, or empty string."""
    try:
        player = xbmc.Player()
        if player.isPlayingVideo():
            return player.getPlayingFile()
    except RuntimeError:
        pass
    return ""


def _list_cache_hit(handle: int, subtitle_id: str, language: str) -> None:
    """Emit a single ListItem for a cached subtitle the user can click to download."""
    listitem = xbmcgui.ListItem(
        label=language,
        label2=f"Nexus cache - {subtitle_id[:8]}",
    )
    try:
        listitem.setArt({"thumb": f"{language}.png", "icon": "5"})
    except Exception:
        pass
    listitem.setProperty("sync", "true")
    listitem.setProperty("hearing_imp", "false")
    url = (f"plugin://{ADDON_ID}/?action=download"
           f"&subtitle_id={urllib.parse.quote(subtitle_id)}"
           f"&language={urllib.parse.quote(language)}")
    xbmcplugin.addDirectoryItem(handle=handle, url=url,
                                listitem=listitem, isFolder=False)


def _list_transcribe_offer(handle: int, language: str) -> None:
    """Emit a synthetic entry the user can click to kick off transcription."""
    listitem = xbmcgui.ListItem(
        label=f"[{language}] Transcribe with Subtitle Nexus (uses credits)",
        label2="No cache hit - generate now",
    )
    try:
        listitem.setArt({"icon": "0"})
    except Exception:
        pass
    listitem.setProperty("sync", "true")
    listitem.setProperty("hearing_imp", "false")
    url = (f"plugin://{ADDON_ID}/?action=transcribe"
           f"&language={urllib.parse.quote(language)}")
    xbmcplugin.addDirectoryItem(handle=handle, url=url,
                                listitem=listitem, isFolder=False)


def do_search(handle: int, params: dict, cfg: Settings) -> None:
    """Kodi 'search' action — auto search using the playing file."""
    if cfg.disable_subtitle_search:
        _log("disable_subtitle_search=true, skipping cache lookup")
        return

    playing = _current_video_path()
    if not playing or playing.startswith(("http://", "https://", "plugin://",
                                          "stack://")):
        _log(f"Not a local file ({playing!r}), no Nexus search possible")
        return

    video = Path(playing)
    if not video.exists():
        _log(f"Playing path missing on disk: {video}")
        return

    try:
        file_hash = oshash(video)
    except OSError as e:
        _log(f"Hash failed: {e}", xbmc.LOGWARNING)
        return

    languages = params.get("languages") or ""
    requested = languages.split(",")[0].strip() if languages else ""
    lang_code = _language_to_iso(requested) if requested else cfg.subtitle_language
    if not lang_code:
        lang_code = cfg.subtitle_language

    client = NexusClient(api_key=cfg.api_key, domain=cfg.domain)
    scope = "own" if cfg.ignore_community_subs else "all"
    try:
        res = client.search(file_hash, cfg.model, lang_code, scope)
    except NexusError as e:
        _log(f"Search failed: {e}", xbmc.LOGWARNING)
        return

    ids = (res or {}).get("subtitle_ids") or []
    if ids:
        _log(f"Nexus cache hits: {ids}")
        for sid in ids:
            _list_cache_hit(handle, sid, lang_code)
    else:
        _log("No cache hit, offering transcription")
        _list_transcribe_offer(handle, lang_code)


def _language_to_iso(name: str) -> str:
    """Best-effort: Kodi sends English language names; convert to 2-char ISO."""
    if not name:
        return ""
    if len(name) in (2, 3) and name.isalpha():
        return name.lower()
    try:
        iso = xbmc.convertLanguage(name, xbmc.ISO_639_1)
        if iso:
            return iso.lower()
    except Exception:
        pass
    return name[:2].lower()


def do_download(handle: int, params: dict, cfg: Settings) -> None:
    """User picked one of the cached subtitle entries."""
    subtitle_id = params.get("subtitle_id", "")
    language = params.get("language") or cfg.subtitle_language
    if not subtitle_id:
        notify("Missing subtitle_id in download action",
               icon=xbmcgui.NOTIFICATION_ERROR)
        return

    _ensure_temp()
    out_path = TEMP_DIR / f"nexus.{language}.srt"

    client = NexusClient(api_key=cfg.api_key, domain=cfg.domain)
    try:
        download_subtitle(client, subtitle_id, out_path,
                          cfg.auto_purchase_past_daily_limit)
    except NexusError as e:
        notify(f"Download failed: {e}", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    listitem = xbmcgui.ListItem(label=str(out_path))
    xbmcplugin.addDirectoryItem(handle=handle, url=str(out_path),
                                listitem=listitem, isFolder=False)


def do_transcribe(handle: int, params: dict, cfg: Settings) -> None:
    """User picked the 'transcribe now' entry — kick off the full pipeline."""
    playing = _current_video_path()
    if not playing:
        notify("No video playing; cannot transcribe.",
               icon=xbmcgui.NOTIFICATION_ERROR)
        return
    video = Path(playing)
    if not video.exists():
        notify(f"Playing file missing: {video}",
               icon=xbmcgui.NOTIFICATION_ERROR)
        return

    if not xbmcgui.Dialog().yesno(
        ADDON_NAME,
        f"No cached subtitles found for [B]{video.name}[/B].\n\n"
        "Run AI transcription now? This may consume Nexus tokens or credits.",
        nolabel="Cancel",
        yeslabel="Transcribe",
    ):
        return

    client = NexusClient(api_key=cfg.api_key, domain=cfg.domain)
    bg = xbmcgui.DialogProgressBG()
    bg.create(ADDON_NAME, "Starting transcription...")
    cb = make_dialog_progress_cb(bg)
    try:
        result = process_video(
            client, cfg, video,
            userdata_dir=userdata_subtitle_dir(),
            progress_cb=cb,
            refresh_player=False,
        )
    except NexusError as e:
        bg.close()
        notify(f"Nexus error: {e}", icon=xbmcgui.NOTIFICATION_ERROR)
        return
    except Exception as e:
        bg.close()
        notify(f"Failed: {e}", icon=xbmcgui.NOTIFICATION_ERROR)
        return
    bg.close()

    if result["result"] in ("cached", "generated") and result.get("srt_path"):
        srt = result["srt_path"]
        listitem = xbmcgui.ListItem(label=srt)
        xbmcplugin.addDirectoryItem(handle=handle, url=srt,
                                    listitem=listitem, isFolder=False)
        notify(f"{result['result'].title()} subtitles ready")
    else:
        notify(f"Transcription error: {result.get('error')}",
               icon=xbmcgui.NOTIFICATION_ERROR)


def main() -> None:
    handle = int(sys.argv[1])
    params = _parse_params(sys.argv[2] if len(sys.argv) > 2 else "")
    action = params.get("action", "")

    cfg = Settings.load(ADDON)
    if not cfg.api_key:
        _log("API key not configured, skipping search", xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(handle)
        return

    _log(f"Action={action} params={params}")

    if action in ("search", "manualsearch"):
        do_search(handle, params, cfg)
    elif action == "download":
        do_download(handle, params, cfg)
    elif action == "transcribe":
        do_transcribe(handle, params, cfg)
    else:
        _log(f"Unknown action: {action}", xbmc.LOGWARNING)

    xbmcplugin.endOfDirectory(handle)


if __name__ == "__main__":
    main()
