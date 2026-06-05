"""ffmpeg-based audio extraction for the Nexus transcription pipeline.

Kodi bundles ffmpeg with the binary but does not expose it as a CLI tool. We
look on PATH first, then fall back to a user-configured path from add-on
settings, then a couple of common install locations.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


AUDIO_FORMAT = "mp3"
AUDIO_CONTENT_TYPE = "audio/mpeg"


def resolve_ffmpeg(configured: str = "") -> str:
    """Return a usable ffmpeg path.

    Tries (in order):
      1. The user-configured path from settings (if non-empty).
      2. `ffmpeg` on $PATH.
      3. Common platform-specific locations.
    """
    if configured:
        if os.path.isabs(configured) and os.path.exists(configured):
            return configured
        found = shutil.which(configured)
        if found:
            return found

    found = shutil.which("ffmpeg")
    if found:
        return found

    candidates = []
    if sys.platform.startswith("win"):
        candidates = [
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/opt/homebrew/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]
    else:
        candidates = [
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "ffmpeg"


def extract_audio(video_path: Path, out_path: Path, ffmpeg: str) -> None:
    """Extract a 16kHz mono 64kbps mp3 from `video_path` to `out_path`."""
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vn", "-sn",
        "-ac", "1", "-ar", "16000",
        "-codec:a", "libmp3lame", "-b:a", "64k",
        str(out_path),
    ]
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    if result.returncode != 0 or not out_path.exists():
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg failed: {err[:500]}")
