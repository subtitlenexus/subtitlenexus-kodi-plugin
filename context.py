"""Context menu entry point.

Kodi context-menu items run as a script, NOT as a plugin URL, so we just
read the currently focused item via the InfoLabels and delegate to
default.py's `action_generate` logic.

addon.xml binds this to the "Generate Nexus Subtitles" context menu entry
visible when right-clicking a video item in the library or file view.
"""
from __future__ import annotations

import sys

import xbmc
import xbmcgui

from resources.lib.generator import notify

sys.path.insert(0, "")
from default import _run_generate, ADDON_NAME


def _resolve_target_path() -> str:
    """Pull the highlighted item's path from Kodi's InfoLabels.

    `ListItem.FileNameAndPath` gives the full path of the currently focused
    library/file item, which is what context-menu items act on.
    """
    candidates = [
        "ListItem.FileNameAndPath",
        "ListItem.Path",
        "ListItem.Filename",
    ]
    for label in candidates:
        path = xbmc.getInfoLabel(label)
        if path:
            return path
    return ""


def main() -> None:
    path = _resolve_target_path()
    if not path:
        xbmcgui.Dialog().ok(ADDON_NAME,
                            "Could not detect a video file on the focused item.")
        return
    if path.startswith(("plugin://", "http://", "https://", "stack://")):
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            "Subtitle Nexus needs a local file to extract audio. The selected "
            "item is a network/plugin stream and is not supported.",
        )
        return
    _run_generate(path, refresh_player=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        notify(f"Context menu failed: {e}", icon=xbmcgui.NOTIFICATION_ERROR)
