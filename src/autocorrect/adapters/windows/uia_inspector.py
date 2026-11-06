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

from autocorrect.adapters.windows import win32_api as w32
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

ES_PASSWORD: Final[int] = w32.ES_PASSWORD
GWL_STYLE: Final[int] = w32.GWL_STYLE
PROCESS_QUERY_LIMITED_INFORMATION: Final[int] = w32.PROCESS_QUERY_LIMITED_INFORMATION


class Win32FocusInspector:
    """
    Inspects the foreground window and focused control on Windows 10/11
    to detect password fields, terminal emulators, and excluded applications.
    """

    def __init__(self, extra_excluded_processes: set[str] | None = None) -> None:
        self._user_excluded: set[str] = {p.lower() for p in (extra_excluded_processes or set())}
        self._user_code: set[str] = set()

    def add_excluded_process(self, process_name: str) -> None:
        self._user_excluded.add(process_name.lower())

    def remove_excluded_process(self, process_name: str) -> None:
        self._user_excluded.discard(process_name.lower())

    def set_user_excluded_processes(self, names: list[str]) -> None:
        """Replace the user's 'never correct here' list (Settings > Apps)."""
        self._user_excluded = {n.strip().lower() for n in names if n.strip()}

    def set_user_code_processes(self, names: list[str]) -> None:
        """Replace the user's 'treat as code/terminal' list (Settings > Apps)."""
        self._user_code = {n.strip().lower() for n in names if n.strip()}

    @property
    def user_excluded_processes(self) -> frozenset[str]:
        return frozenset(self._user_excluded)

    @property
    def user_code_processes(self) -> frozenset[str]:
        return frozenset(self._user_code)

    def classify_window_metadata(
        self,
        process_name: str,
        window_title: str,
        window_style: int = 0,
        control_id: str = "",
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
        is_terminal = proc_low in DEFAULT_TERMINAL_PROCESSES or proc_low in self._user_code

        return FocusContext(
            process_name=proc_low,
            window_title=window_title,
            bundle_or_app_id=proc_low,
            is_password_or_secure=is_password,
            is_terminal_or_code=is_terminal,
            is_excluded_app=is_excluded,
            control_id=control_id,
        )

    def get_current_focus(self) -> FocusContext:
        """Query the active Win32 foreground window and focused child control."""
        if sys.platform != "win32":
            return FocusContext()

        try:
            user32 = w32.user32
            kernel32 = w32.kernel32

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
            gti = w32.GUITHREADINFO()
            gti.cbSize = ctypes.sizeof(w32.GUITHREADINFO)
            style = 0
            focus_hwnd = 0
            if user32.GetGUIThreadInfo(thread_id, ctypes.byref(gti)) and gti.hwndFocus:
                focus_hwnd = int(gti.hwndFocus)
                style = user32.GetWindowLongW(gti.hwndFocus, GWL_STYLE)

            # Identity of the focused control. Chromium/Electron apps keep one HWND
            # for the whole document, so the id is stable while the title changes.
            control_id = f"{pid.value}:{focus_hwnd or int(hwnd)}"

            return self.classify_window_metadata(
                process_name=proc_name,
                window_title=title,
                window_style=style,
                control_id=control_id,
            )
        except Exception:
            return FocusContext()
