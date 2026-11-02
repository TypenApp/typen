"""
OS Login Startup Registration Manager.
Supports Windows (`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`)
and macOS (`~/Library/LaunchAgents/io.autocorrect.desktop.plist`).
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from typing import Final

WIN_RUN_KEY_PATH: Final[str] = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_STARTUP_NAME: Final[str] = "AutoCorrectDesktop"
MACOS_PLIST_NAME: Final[str] = "io.autocorrect.desktop.plist"


class StartupManager:
    """Manages optional launch-at-login registration for Windows and macOS."""

    @staticmethod
    def build_macos_launch_agent_plist(executable_command: list[str]) -> bytes:
        payload = {
            "Label": "io.autocorrect.desktop",
            "ProgramArguments": executable_command,
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
        }
        return plistlib.dumps(payload)

    @staticmethod
    def set_launch_at_login(enabled: bool, executable_path: str | None = None) -> bool:
        exe = executable_path or sys.executable
        if sys.platform == "win32":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    WIN_RUN_KEY_PATH,
                    0,
                    winreg.KEY_SET_VALUE,
                ) as key:
                    if enabled:
                        winreg.SetValueEx(key, APP_STARTUP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
                    else:
                        try:
                            winreg.DeleteValue(key, APP_STARTUP_NAME)
                        except FileNotFoundError:
                            pass
                return True
            except Exception:
                return False

        if sys.platform == "darwin":
            plist_path = Path.home() / "Library" / "LaunchAgents" / MACOS_PLIST_NAME
            if enabled:
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                plist_path.write_bytes(
                    StartupManager.build_macos_launch_agent_plist([exe])
                )
            else:
                plist_path.unlink(missing_ok=True)
            return True

        return False
