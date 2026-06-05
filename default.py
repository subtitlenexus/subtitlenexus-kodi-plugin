"""Default entry point for the Subtitle Nexus add-on.

Reached when the user runs the add-on from the Programs/Video add-ons menu, or
when another add-on/script invokes us with `RunScript`/`RunAddon`. Supports a
small set of CLI-style actions so the same script can back the home-screen
launcher, the context-menu launcher, and a "validate key" diagnostic.

Usage:
  default.py                       -> show the action picker
  default.py validate              -> validate API key + show user info
  default.py generate <video_path> -> generate subs for the given path
  default.py generate_current      -> generate subs for the currently playing
                                       video
"""
from __future__ import annotations

import sys
from pathlib import Path

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.generator import (
    notify,
    process_video,
    make_dialog_progress_cb,
    userdata_subtitle_dir,
)
from resources.lib.nexus_api import NexusClient, NexusError
from resources.lib.settings import Settings


ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name")


def _require_api_key(cfg: Settings) -> bool:
    if not cfg.api_key:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            "No API key configured. Open the add-on settings and paste your "
            "key from subtitlenexus.com/account.",
        )
        ADDON.openSettings()
        return False
    return True


def action_validate() -> None:
    cfg = Settings.load(ADDON)
    if not _require_api_key(cfg):
        return
    client = NexusClient(api_key=cfg.api_key, domain=cfg.domain)
    try:
        client.health()
    except NexusError as e:
        xbmcgui.Dialog().ok(ADDON_NAME, f"Health check failed: {e}")
        return
    try:
        info = client.validate_key()
        user = client.user_info()
    except NexusError as e:
        xbmcgui.Dialog().ok(ADDON_NAME, f"Key validation failed: {e}")
        return
    msg = (
        f"Valid: {info.get('valid', True)}\n"
        f"User: {user.get('username')}\n"
        f"Plan: {user.get('plan')}\n"
        f"Subtitle credits: {user.get('subtitle_request_credits')}\n"
        f"Tokens: {user.get('tokens')}"
    )
    xbmcgui.Dialog().ok(ADDON_NAME, msg)


def _confirm_transcribe(video_path: Path) -> bool:
    """Show a confirmation dialog before kicking off a (paid) transcription."""
    return xbmcgui.Dialog().yesno(
        ADDON_NAME,
        f"Generate AI subtitles for:\n[B]{video_path.name}[/B]\n\n"
        "This may consume Nexus tokens or daily credits.",
        nolabel="Cancel",
        yeslabel="Generate",
    )


def _run_generate(video_path_str: str, refresh_player: bool = True) -> None:
    cfg = Settings.load(ADDON)
    if not _require_api_key(cfg):
        return

    video_path = Path(video_path_str)
    if not video_path.exists():
        xbmcgui.Dialog().ok(ADDON_NAME, f"File not found:\n{video_path}")
        return

    if not _confirm_transcribe(video_path):
        return

    client = NexusClient(api_key=cfg.api_key, domain=cfg.domain)
    bg = xbmcgui.DialogProgressBG()
    bg.create(ADDON_NAME, "Starting...")
    cb = make_dialog_progress_cb(bg)
    try:
        result = process_video(
            client, cfg, video_path,
            userdata_dir=userdata_subtitle_dir(),
            progress_cb=cb,
            refresh_player=refresh_player,
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

    if result["result"] in ("cached", "generated"):
        notify(
            f"{result['result'].title()}: {Path(result['srt_path']).name}",
            icon=xbmcgui.NOTIFICATION_INFO,
        )
    elif result["result"] == "skipped":
        notify(f"Skipped: {result['error']}", icon=xbmcgui.NOTIFICATION_WARNING)
    else:
        notify(f"Error: {result['error']}", icon=xbmcgui.NOTIFICATION_ERROR)


def action_generate(video_path: str) -> None:
    _run_generate(video_path)


def action_generate_current() -> None:
    player = xbmc.Player()
    if not player.isPlayingVideo():
        xbmcgui.Dialog().ok(ADDON_NAME, "No video is currently playing.")
        return
    try:
        playing = player.getPlayingFile()
    except RuntimeError:
        xbmcgui.Dialog().ok(ADDON_NAME, "Could not read the current playback path.")
        return
    if playing.startswith(("http://", "https://", "plugin://", "stack://")):
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            "Subtitle Nexus needs a local file path to extract audio. The "
            "current item is a network/plugin stream and isn't supported yet.",
        )
        return
    _run_generate(playing, refresh_player=True)


def action_picker() -> None:
    choices = [
        "Generate subs for currently playing video",
        "Pick a video file and generate subs",
        "Validate API key",
        "Open settings",
    ]
    sel = xbmcgui.Dialog().select(ADDON_NAME, choices)
    if sel == 0:
        action_generate_current()
    elif sel == 1:
        path = xbmcgui.Dialog().browseSingle(
            1,
            "Pick a video file",
            "files",
            ".mkv|.mp4|.avi|.mov|.webm|.m4v|.ts|.wmv|.flv",
        )
        if path:
            _run_generate(path)
    elif sel == 2:
        action_validate()
    elif sel == 3:
        ADDON.openSettings()


def main(argv: list) -> None:
    if len(argv) <= 1:
        action_picker()
        return
    action = argv[1]
    if action == "validate":
        action_validate()
    elif action == "generate" and len(argv) > 2:
        action_generate(argv[2])
    elif action == "generate_current":
        action_generate_current()
    else:
        xbmc.log(f"[Subtitle Nexus] Unknown action: {action}", xbmc.LOGWARNING)
        action_picker()


if __name__ == "__main__":
    main(sys.argv)
