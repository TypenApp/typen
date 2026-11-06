"""
Visible top-level windows → (process name, title) for the Settings > Apps picker.

Read-only and best-effort: windows we cannot query (elevated processes, UWP
hosts without a title) are skipped. Never raises.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from autocorrect.adapters.windows import win32_api as w32

# Hosts that own many windows but are never what the user means by "an app".
_SKIP_PROCESSES = frozenset(
    {
        "applicationframehost.exe",
        "textinputhost.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "searchhost.exe",
        "explorer.exe",
        "typen.exe",
        "autocorrect.exe",
    }
)


def process_name_for_pid(pid: int) -> str:
    """Lower-case image name ('code.exe') for `pid`, or '' when it cannot be read."""
    if sys.platform != "win32" or not pid:
        return ""
    kernel32 = w32.kernel32
    hproc = kernel32.OpenProcess(w32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = ctypes.c_ulong(512)
        if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
    finally:
        kernel32.CloseHandle(hproc)
    return ""


def list_visible_windows(limit: int = 60) -> list[dict[str, str]]:
    """
    One entry per process with a visible, titled top-level window, ordered by
    Z-order (foreground first): [{"process": "code.exe", "title": "main.py - VS Code"}].
    """
    if sys.platform != "win32":
        return []
    user32 = w32.user32
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    import ctypes.wintypes as wt

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _enum(hwnd, _lparam):  # type: ignore[no-untyped-def]
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = process_name_for_pid(pid.value)
            if not proc or proc in _SKIP_PROCESSES or proc in seen:
                return True
            seen.add(proc)
            out.append({"process": proc, "title": title[:120]})
            return len(out) < limit
        except Exception:
            return True

    try:
        user32.EnumWindows(ctypes.cast(_enum, ctypes.c_void_p), 0)
    except Exception:
        return out
    return out
