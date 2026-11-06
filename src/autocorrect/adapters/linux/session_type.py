"""
Linux display-session detection.

The X11 adapter (XRecord + XTest) only works on a real X server or under
XWayland *for X11 clients*. Under a Wayland compositor the only sanctioned
route is the IBus engine (`autocorrect.adapters.linux.ibus_engine`), so the
daemon needs to know which world it is running in before picking a hook.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum


class LinuxSessionType(str, Enum):
    X11 = "x11"
    WAYLAND = "wayland"
    HEADLESS = "headless"


def detect_linux_session(env: Mapping[str, str] | None = None) -> LinuxSessionType:
    """
    Classify the current graphical session from environment variables only
    (no X connection is opened, so this is safe to call in tests and CI).

    Precedence follows what login managers actually set:
    `XDG_SESSION_TYPE` is authoritative when present; otherwise the presence
    of `WAYLAND_DISPLAY` wins over `DISPLAY` because XWayland always exports
    `DISPLAY` too.
    """
    e = os.environ if env is None else env
    session = e.get("XDG_SESSION_TYPE", "").strip().lower()
    if session == "wayland":
        return LinuxSessionType.WAYLAND
    if session == "x11":
        return LinuxSessionType.X11
    if e.get("WAYLAND_DISPLAY"):
        return LinuxSessionType.WAYLAND
    if e.get("DISPLAY"):
        return LinuxSessionType.X11
    return LinuxSessionType.HEADLESS
