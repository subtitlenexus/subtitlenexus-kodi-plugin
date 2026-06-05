"""Add-on settings loader.

Kodi stores settings as strings; we coerce to the right types here so the rest
of the code can stay typed.
"""
from __future__ import annotations

from dataclasses import dataclass

import xbmcaddon


DEFAULT_DOMAIN = "api.subtitlenexus.com"
DEFAULT_MODEL = "lulu-2605"
DEFAULT_SUB_LANG = "en"
DEFAULT_AUDIO_LANG = "ja"
DEFAULT_VISIBILITY = "PUBLIC"


def _bool(addon: xbmcaddon.Addon, key: str) -> bool:
    raw = addon.getSetting(key)
    return raw == "true"


def _str(addon: xbmcaddon.Addon, key: str, default: str) -> str:
    raw = addon.getSetting(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default


@dataclass
class Settings:
    api_key: str
    domain: str
    model: str
    subtitle_language: str
    audio_language: str
    visibility: str
    ignore_community_subs: bool
    disable_subtitle_search: bool
    auto_purchase_past_daily_limit: bool
    ffmpeg_path: str

    @classmethod
    def load(cls, addon: xbmcaddon.Addon | None = None) -> "Settings":
        if addon is None:
            addon = xbmcaddon.Addon()
        return cls(
            api_key=_str(addon, "api_key", ""),
            domain=_str(addon, "domain", DEFAULT_DOMAIN),
            model=_str(addon, "model", DEFAULT_MODEL),
            subtitle_language=_str(addon, "subtitle_language", DEFAULT_SUB_LANG),
            audio_language=_str(addon, "audio_language", DEFAULT_AUDIO_LANG),
            visibility=_str(addon, "visibility", DEFAULT_VISIBILITY).upper() or DEFAULT_VISIBILITY,
            ignore_community_subs=_bool(addon, "ignore_community_subs"),
            disable_subtitle_search=_bool(addon, "disable_subtitle_search"),
            auto_purchase_past_daily_limit=_bool(addon, "auto_purchase_past_daily_limit"),
            ffmpeg_path=_str(addon, "ffmpeg_path", ""),
        )
