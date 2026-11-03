"""
Windows Focus, Application Blocklist, and Password Field Inspector.
Uses Win32 GUIThreadInfo, Process Image Name, Window Styles (`ES_PASSWORD`),
and Window Titles to prevent processing inside password managers, terminals,
or secure fields.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Final

from autocorrect.input.ports import FocusContext

# Default password managers, RDP/SSH clients, and games where autocorrect must auto-suspend
DEFAULT_EXCLUDED_PROCESSES: Final[frozenset[str]] = frozenset(
    {
        "1password.exe",
        "bitwarden.exe",
        "keepass.exe",
        "keepassxc.exe",
        "dashlane.exe",
        "lastpass.exe",
        "mstsc.exe",
        "putty.exe",
        "kitty.exe",
        "vmware-vmx.exe",
        "virtualboxvm.exe",
    }
)

# Terminals and IDEs where prose punctuation/sentence-cap heuristics are relaxed
DEFAULT_TERMINAL_PROCESSES: Final[frozenset[str]] = frozenset(
    {
        "windowsterminal.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "mintty.exe",
        "alacritty.exe",
        "wezterm-gui.exe",
        "hyper.exe",
    }
)

ES_PASSWORD: Final[int] = 0x0020
GWL_STYLE: Final[int] = -16
PROCESS_QUERY_LIMITED_INFORMATION: Final[int] = 0x1000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", RECT),
    ]


class Win32FocusInspector:
    """
    Inspects the foreground window and focused control on Windows 10/11
    to detect password fields, terminal emulators, and excluded applications.
    """

    def __init__(self, extra_excluded_processes: set[str] | None = None) -> None:
        self._user_excluded: set[str] = {p.lower() for p in (extra_excluded_processes or set())}

    def add_excluded_process(self, process_name: str) -> None:
        self._user_excluded.add(process_name.lower())

    def remove_excluded_process(self, process_name: str) -> None:
        self._user_excluded.discard(process_name.lower())

    def classify_window_metadata(
        self,
        process_name: str,
        window_title: str,
        window_style: int = 0,
    ) -> FocusContext:
        """
        Pure classification helper (testable on all platforms) that determines
        security and profile flags from process name, window title, and Win32 style bits.
        """
        proc_low = process_name.lower()
        title_low = window_title.lower()

        is_password = bool(window_style & ES_PASSWORD)
        if any(
            kw in title_low
            for kw in (
                "password",
                "passphrase",
                "1password",
                "bitwarden",
                "keepass",
                "sign in - security key",
            )
        ):
            is_password = True

        is_excluded = proc_low in DEFAULT_EXCLUDED_PROCESSES or proc_low in self._user_excluded
        is_terminal = proc_low in DEFAULT_TERMINAL_PROCESSES

        return FocusContext(
            process_name=proc_low,
            window_title=window_title,
            bundle_or_app_id=proc_low,
            is_password_or_secure=is_password,
            is_terminal_or_code=is_terminal,
            is_excluded_app=is_excluded,
        )

    def get_current_focus(self) -> FocusContext:
        """Query the active Win32 foreground window and focused child control."""
        if sys.platform != "win32":
            return FocusContext()

        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return FocusContext()

            # Read window title
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value

            # Read process image name
            pid = ctypes.c_ulong(0)
            thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc_name = ""
            if pid.value:
                hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
                if hproc:
                    try:
                        img_buf = ctypes.create_unicode_buffer(512)
                        size = ctypes.c_ulong(512)
                        if kernel32.QueryFullProcessImageNameW(hproc, 0, img_buf, ctypes.byref(size)):
                            proc_name = Path(img_buf.value).name.lower()
                    finally:
                        kernel32.CloseHandle(hproc)

            # Check focused control style for ES_PASSWORD
            gti = GUITHREADINFO()
            gti.cbSize = ctypes.sizeof(GUITHREADINFO)
            style = 0
            if user32.GetGUIThreadInfo(thread_id, ctypes.byref(gti)) and gti.hwndFocus:
                style = user32.GetWindowLongW(gti.hwndFocus, GWL_STYLE)

            return self.classify_window_metadata(
                process_name=proc_name,
                window_title=title,
                window_style=style,
            )
        except Exception:
            return FocusContext()
