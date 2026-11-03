"""
System Tray / Menu Bar Integration (`pystray`).
Provides unobtrusive background control:
- Status display (Edition / Trial status)
- Pause / Resume typing assistance
- Launch out-of-process Settings window (same executable with `--settings` when frozen,
  `python -m autocorrect.ui.settings_main` from a source checkout)
- Exit cleanly (releasing all OS hooks)
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def build_settings_command(data_dir: Path) -> list[str]:
    """
    Return the argv needed to open the Settings UI as a separate process.
    Frozen builds re-invoke the same executable in `--settings` mode; source
    checkouts spawn the module through the current interpreter.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--settings", "--data-dir", str(data_dir)]
    return [
        sys.executable,
        "-m",
        "autocorrect.ui.settings_main",
        "--data-dir",
        str(data_dir),
    ]


class SystemTrayController:
    """
    Lightweight system tray icon and menu controller.
    Spawns the Settings window as a separate short-lived process so the daemon
    never holds GUI widget memory while running in the background.
    """

    def __init__(
        self,
        on_toggle_pause: Callable[[], bool],
        on_quit: Callable[[], None],
        get_status_label: Callable[[], str],
        data_dir: Path,
        is_paused: Callable[[], bool] | None = None,
    ) -> None:
        self._on_toggle_pause = on_toggle_pause
        self._on_quit = on_quit
        self._get_status_label = get_status_label
        self._is_paused = is_paused or (lambda: False)
        self._data_dir = data_dir
        self._icon: Any = None
        self._settings_proc: subprocess.Popen[bytes] | None = None

    @staticmethod
    def create_tray_icon_image(active: bool = True) -> Image.Image:
        """Generate a clean 64x64 RGBA icon in memory without external image assets."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bg_color = (37, 99, 235, 255) if active else (107, 114, 128, 255)
        draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill=bg_color)
        # Draw a crisp checkmark
        draw.line([(18, 34), (28, 44), (46, 22)], fill=(255, 255, 255, 255), width=5)
        return img

    def launch_settings_subprocess(self) -> subprocess.Popen[bytes] | None:
        """Spawn the out-of-process Settings UI so daemon RSS stays < 30MB."""
        if self._settings_proc is not None and self._settings_proc.poll() is None:
            return self._settings_proc
        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._settings_proc = subprocess.Popen(
                build_settings_command(self._data_dir),
                creationflags=creation_flags,
            )
            return self._settings_proc
        except Exception:
            return None

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> Any:
        import pystray

        def pause_label(_item: Any) -> str:
            return "Resume typing assistance" if self._is_paused() else "Pause typing assistance"

        def on_toggle(_icon: Any, _item: Any) -> None:
            self._on_toggle_pause()
            self._refresh_icon()

        def on_settings(_icon: Any, _item: Any) -> None:
            self.launch_settings_subprocess()

        def on_quit(_icon: Any, _item: Any) -> None:
            try:
                self._on_quit()
            finally:
                if self._icon is not None:
                    self._icon.stop()

        return pystray.Menu(
            pystray.MenuItem(lambda _i: self._get_status_label(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Settings…", on_settings, default=True),
            pystray.MenuItem(pause_label, on_toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit AutoCorrect", on_quit),
        )

    def _refresh_icon(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.icon = self.create_tray_icon_image(active=not self._is_paused())
            self._icon.title = self._get_status_label()
            self._icon.update_menu()
        except Exception:
            pass

    def run_blocking(self) -> None:
        """
        Create the tray icon and block on its event loop until Quit is chosen.
        Must be called from the main thread on macOS; on Windows any thread is fine.
        """
        import pystray

        self._icon = pystray.Icon(
            name="AutoCorrectDesktop",
            icon=self.create_tray_icon_image(active=not self._is_paused()),
            title=self._get_status_label(),
            menu=self._build_menu(),
        )
        self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
