"""
System-locale → English variant resolver for the "Follow system" language setting.

Only the *region* part of the locale matters: en-US → EN_US, en-GB/en-IE/en-NZ…
→ EN_GB, en-CA → EN_CA, en-AU → EN_AU. Non-English locales fall back to EN_GB
(Typen only corrects English; British is the house default). Never raises.
"""

from __future__ import annotations

import locale
import os
import sys

from autocorrect.intelligence.schema import RegionFlag

DEFAULT_REGION: RegionFlag = RegionFlag.EN_GB

_REGION_BY_COUNTRY: dict[str, RegionFlag] = {
    "US": RegionFlag.EN_US,
    "PH": RegionFlag.EN_US,
    "CA": RegionFlag.EN_CA,
    "AU": RegionFlag.EN_AU,
    "GB": RegionFlag.EN_GB,
    "UK": RegionFlag.EN_GB,
    "IE": RegionFlag.EN_GB,
    "NZ": RegionFlag.EN_GB,
    "ZA": RegionFlag.EN_GB,
    "IN": RegionFlag.EN_GB,
    "SG": RegionFlag.EN_GB,
    "HK": RegionFlag.EN_GB,
    "MY": RegionFlag.EN_GB,
    "NG": RegionFlag.EN_GB,
    "KE": RegionFlag.EN_GB,
    "JM": RegionFlag.EN_GB,
}


def region_for_locale_tag(tag: str | None) -> RegionFlag:
    """Map a BCP-47 / POSIX locale tag ('en-US', 'en_GB.UTF-8', 'C') to a variant."""
    if not tag:
        return DEFAULT_REGION
    cleaned = tag.strip().replace("_", "-").split(".")[0].split("@")[0]
    parts = [p for p in cleaned.split("-") if p]
    if not parts:
        return DEFAULT_REGION
    # Country is the first 2-letter all-alpha subtag after the language (skip scripts like 'Latn').
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            return _REGION_BY_COUNTRY.get(part.upper(), DEFAULT_REGION)
    return DEFAULT_REGION


def _windows_user_locale() -> str | None:
    """The Windows *user* locale (Settings > Time & language > Region), e.g. 'en-AU'."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
            return buf.value or None
    except Exception:
        return None
    return None


def system_locale_tag() -> str | None:
    """Best available locale tag for this machine, or None when nothing is set."""
    tag = _windows_user_locale()
    if tag:
        return tag
    for env in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env)
        if value and value not in ("C", "POSIX"):
            return value
    try:
        tag = locale.getlocale()[0]
    except Exception:
        tag = None
    return tag or None


def detect_english_region() -> RegionFlag:
    """The English variant the system suggests; EN_GB when unknown or non-English."""
    try:
        return region_for_locale_tag(system_locale_tag())
    except Exception:
        return DEFAULT_REGION
