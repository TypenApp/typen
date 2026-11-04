"""
System Tray / Menu Bar Integration (`pystray`).
Provides unobtrusive background control:
- Status display (including why nothing is being corrected)
- Pause / Resume typing assistance (Resume also leaves safe mode)
- Launch out-of-process Settings window (same executable with `--settings` when frozen,
  `python -m autocorrect.ui.settings_main` from a source checkout)
- Balloon / banner notifications (first run, emergency stop, degraded hook)
- Exit cleanly (the launcher releases all OS hooks when the loop returns)

The icon is the real Typen mark from `autocorrect.branding`, adapted to the
light/dark taskbar and greyed while paused.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from autocorrect import branding
from autocorrect.licensing.entitlement_manager import DONATE_URL

log = logging.getLogger(__name__)


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
        needs_attention: Callable[[], bool] | None = None,
    ) -> None:
        self._on_toggle_pause = on_toggle_pause
        self._on_quit = on_quit
        self._get_status_label = get_status_label
        self._is_paused = is_paused or (lambda: False)
        self._needs_attention = needs_attention or (lambda: False)
        self._data_dir = data_dir
        self._icon: Any = None
        self._settings_proc: subprocess.Popen[bytes] | None = None
        self._theme = branding.tray_theme()

    @staticmethod
    def create_tray_icon_image(active: bool = True, theme: branding.Theme | None = None) -> Image.Image:
        """Render the 64x64 tray icon from the shared brand drawing (no external image assets)."""
        return branding.draw_mark(64, theme=theme or branding.tray_theme(), active=active)

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
            log.exception("could not launch Settings")
            return None

    # ------------------------------------------------------------- notify

    def notify(self, title: str, message: str) -> None:
        """Show an OS notification from the tray icon (no-op when unsupported or not yet running)."""
        icon = self._icon
        if icon is None:
            log.info("notification (no tray yet): %s - %s", title, message)
            return
        try:
            if getattr(icon, "HAS_NOTIFICATION", False):
                icon.notify(message, title)
            else:
                log.info("notification (backend has none): %s - %s", title, message)
        except Exception:
            log.exception("tray notification failed")

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> Any:
        import pystray

        def pause_label(_item: Any) -> str:
            return "Resume typing assistance" if self._is_paused() else "Pause typing assistance"

        def on_toggle(_icon: Any, _item: Any) -> None:
            try:
                self._on_toggle_pause()
            finally:
                self.refresh()

        def on_settings(_icon: Any, _item: Any) -> None:
            self.launch_settings_subprocess()

        def on_sponsor(_icon: Any, _item: Any) -> None:
            import webbrowser

            webbrowser.open(DONATE_URL)

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
            pystray.MenuItem("Sponsor Typen on GitHub…", on_sponsor),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Typen", on_quit),
        )

    def refresh(self) -> None:
        """Re-render icon, tooltip and menu after a state change (thread-safe enough for pystray)."""
        if self._icon is None:
            return
        try:
            self._theme = branding.tray_theme()
            paused = self._is_paused() or self._needs_attention()
            self._icon.icon = self.create_tray_icon_image(active=not paused, theme=self._theme)
            self._icon.title = self._get_status_label()[:127]  # Windows tooltip limit
            self._icon.update_menu()
        except Exception:
            log.exception("tray refresh failed")

    # Backwards-compatible alias.
    _refresh_icon = refresh

    def run_blocking(self, on_ready: Callable[[], None] | None = None) -> None:
        """
        Create the tray icon and block on its event loop until Quit is chosen.
        `on_ready` runs on pystray's setup thread once the icon is visible; the
        launcher uses it to attach the OS hooks only after the user has a way to
        reach the menu. Must be called from the main thread on macOS.
        """
        import pystray

        self._icon = pystray.Icon(
            name="AutoCorrectDesktop",
            icon=self.create_tray_icon_image(active=not self._is_paused(), theme=self._theme),
            title=self._get_status_label()[:127],
            menu=self._build_menu(),
        )

        def _setup(icon: Any) -> None:
            icon.visible = True
            if on_ready is not None:
                try:
                    on_ready()
                except Exception:
                    log.exception("tray on_ready raised")
            self.refresh()

        self._icon.run(setup=_setup)

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
