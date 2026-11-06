"""
OS Login Startup Registration Manager.

- Windows : `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`
- macOS   : `~/Library/LaunchAgents/io.autocorrect.desktop.plist`, loaded /
            unloaded immediately with `launchctl bootstrap|bootout gui/<uid>`
            so the change takes effect without a logout.
- Linux   : XDG autostart entry `$XDG_CONFIG_HOME/autostart/autocorrect-desktop.desktop`
            (honoured by GNOME, KDE, XFCE, Cinnamon, MATE, LXQt ...).
"""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Final

WIN_RUN_KEY_PATH: Final[str] = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_STARTUP_NAME: Final[str] = "AutoCorrectDesktop"
MACOS_LAUNCH_AGENT_LABEL: Final[str] = "io.autocorrect.desktop"
MACOS_PLIST_NAME: Final[str] = f"{MACOS_LAUNCH_AGENT_LABEL}.plist"
LINUX_DESKTOP_FILE_NAME: Final[str] = "autocorrect-desktop.desktop"


def _frozen_launch_command(exe: str) -> list[str]:
    """Frozen builds run the executable directly; source checkouts go through the launcher module."""
    if getattr(sys, "frozen", False) or exe != sys.executable:
        return [exe]
    return [exe, "-m", "autocorrect.launcher"]


class StartupManager:
    """Manages optional launch-at-login registration for Windows, macOS and Linux."""

    # ----------------------------------------------------------------- macOS

    @staticmethod
    def build_macos_launch_agent_plist(executable_command: list[str]) -> bytes:
        payload = {
            "Label": MACOS_LAUNCH_AGENT_LABEL,
            "ProgramArguments": executable_command,
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
            "LimitLoadToSessionType": "Aqua",
        }
        return plistlib.dumps(payload)

    @staticmethod
    def macos_plist_path(home: Path | None = None) -> Path:
        return (home or Path.home()) / "Library" / "LaunchAgents" / MACOS_PLIST_NAME

    @staticmethod
    def _launchctl(*args: str) -> bool:
        try:
            res = subprocess.run(["launchctl", *args], capture_output=True, timeout=10, check=False)
            return res.returncode == 0
        except Exception:
            return False

    # ----------------------------------------------------------------- Linux

    @staticmethod
    def build_linux_desktop_entry(executable_command: list[str]) -> str:
        exec_line = " ".join(shlex.quote(part) for part in executable_command)
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.0\n"
            "Name=Typen\n"
            "Comment=System-wide offline autocorrect and writing assistant\n"
            f"Exec={exec_line}\n"
            "Icon=autocorrect-desktop\n"
            "Terminal=false\n"
            "Categories=Utility;Accessibility;\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-GNOME-Autostart-Delay=3\n"
            "X-KDE-autostart-after=panel\n"
            "StartupNotify=false\n"
        )

    @staticmethod
    def linux_autostart_path(home: Path | None = None, env: dict[str, str] | None = None) -> Path:
        e = os.environ if env is None else env
        cfg = e.get("XDG_CONFIG_HOME", "").strip()
        base = Path(cfg).expanduser() if cfg else (home or Path.home()) / ".config"
        return base / "autostart" / LINUX_DESKTOP_FILE_NAME

    # ---------------------------------------------------------------- public

    @staticmethod
    def is_launch_at_login_enabled() -> bool:
        if sys.platform == "win32":
            try:
                import winreg

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY_PATH) as key:
                    winreg.QueryValueEx(key, APP_STARTUP_NAME)
                return True
            except Exception:
                return False
        if sys.platform == "darwin":
            return StartupManager.macos_plist_path().exists()
        if sys.platform.startswith("linux"):
            return StartupManager.linux_autostart_path().exists()
        return False

    @staticmethod
    def set_launch_at_login(enabled: bool, executable_path: str | None = None) -> bool:
        exe = executable_path or sys.executable
        command = _frozen_launch_command(exe)

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
            plist_path = StartupManager.macos_plist_path()
            domain = f"gui/{os.getuid()}"
            if enabled:
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                plist_path.write_bytes(StartupManager.build_macos_launch_agent_plist(command))
                # Re-register so an updated ProgramArguments takes effect immediately.
                StartupManager._launchctl("bootout", domain, str(plist_path))
                StartupManager._launchctl("bootstrap", domain, str(plist_path))
            else:
                StartupManager._launchctl("bootout", domain, str(plist_path))
                plist_path.unlink(missing_ok=True)
            return True

        if sys.platform.startswith("linux"):
            desktop_path = StartupManager.linux_autostart_path()
            try:
                if enabled:
                    desktop_path.parent.mkdir(parents=True, exist_ok=True)
                    desktop_path.write_text(
                        StartupManager.build_linux_desktop_entry(command), encoding="utf-8"
                    )
                    desktop_path.chmod(0o644)
                else:
                    desktop_path.unlink(missing_ok=True)
                return True
            except OSError:
                return False

        return False
