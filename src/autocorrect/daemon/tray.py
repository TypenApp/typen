"""
System Tray / Menu Bar Integration (`pystray`).
Provides unobtrusive background control:
- Tooltip that says only what matters: "Typen", "Typen - Paused" or
  "Typen - Not correcting" (the reason lives in the Settings app)
- Open Typen (the settings window) / Pause / Resume / Send feedback / Quit
- A brief proof-red pulse of the icon whenever a correction lands, so the
  user can see the app is working without being interrupted
- A countdown in the tooltip while Esc is being held
- Balloon / banner notifications (first run, first correction, pause/resume)
- Exit cleanly (the launcher releases all OS hooks when the loop returns)

The icon is the real Typen mark from `autocorrect.branding`, adapted to the
light/dark taskbar and greyed while paused.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from PIL import Image

from autocorrect import branding
from autocorrect.licensing.entitlement_manager import DONATE_URL

log = logging.getLogger(__name__)

APP_NAME: Final[str] = "Typen"
PULSE_SECONDS: Final[float] = 0.6
TOOLTIP_LIMIT: Final[int] = 127  # Windows NOTIFYICONDATA szTip


def build_settings_command(data_dir: Path, screen: str | None = None) -> list[str]:
    """
    Return the argv needed to open the Settings UI as a separate process.
    Frozen builds re-invoke the same executable in `--settings` mode; source
    checkouts spawn the module through the current interpreter. `screen`
    (e.g. "feedback") asks the window to open on that screen.
    """
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--settings", "--data-dir", str(data_dir)]
    else:
        cmd = [
            sys.executable,
            "-m",
            "autocorrect.ui.settings_main",
            "--data-dir",
            str(data_dir),
        ]
    if screen:
        cmd += ["--screen", screen]
    return cmd


def tooltip_for(*, paused: bool, needs_attention: bool, hold_remaining: float | None = None) -> str:
    """The short tray tooltip. Never explanatory: that is what the settings window is for."""
    if hold_remaining is not None:
        return f"{APP_NAME} - keep holding Esc ({max(1, round(hold_remaining))} s)"
    if needs_attention:
        return f"{APP_NAME} - Not correcting"
    if paused:
        return f"{APP_NAME} - Paused"
    return APP_NAME


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
        get_status_label: Callable[[], str] | None = None,
        data_dir: Path = Path("."),
        is_paused: Callable[[], bool] | None = None,
        needs_attention: Callable[[], bool] | None = None,
    ) -> None:
        self._on_toggle_pause = on_toggle_pause
        self._on_quit = on_quit
        # Kept for callers that still pass a long status label; the tooltip no longer uses it.
        self._get_status_label = get_status_label or (lambda: APP_NAME)
        self._is_paused = is_paused or (lambda: False)
        self._needs_attention = needs_attention or (lambda: False)
        self._data_dir = data_dir
        self._icon: Any = None
        self._settings_proc: subprocess.Popen[bytes] | None = None
        self._theme = branding.tray_theme()
        self._pulse_timer: threading.Timer | None = None
        self._pulsing = False
        self._hold_remaining: float | None = None
        self._lock = threading.Lock()

    @staticmethod
    def create_tray_icon_image(
        active: bool = True, theme: branding.Theme | None = None, *, accent: bool = False
    ) -> Image.Image:
        """Render the 64x64 tray icon from the shared brand drawing (no external image assets)."""
        return branding.draw_mark(64, theme=theme or branding.tray_theme(), active=active, accent=accent)

    def launch_settings_subprocess(self, screen: str | None = None) -> subprocess.Popen[bytes] | None:
        """Spawn the out-of-process Settings UI so daemon RSS stays < 30MB."""
        already_open = self._settings_proc is not None and self._settings_proc.poll() is None
        if already_open and not screen:
            return self._settings_proc
        # With a screen request while a window is open, the new process hands
        # the request to the running window and exits (see settings_main).
        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                build_settings_command(self._data_dir, screen),
                creationflags=creation_flags,
            )
            if self._settings_proc is None or self._settings_proc.poll() is not None:
                self._settings_proc = proc
            return proc
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

    # -------------------------------------------------------------- pulse

    def pulse(self) -> None:
        """Flash the icon proof-red for a moment: a correction just landed."""
        if self._icon is None or self._is_paused() or self._needs_attention():
            return
        with self._lock:
            if self._pulse_timer is not None:
                self._pulse_timer.cancel()
            self._pulsing = True
            self._pulse_timer = threading.Timer(PULSE_SECONDS, self._end_pulse)
            self._pulse_timer.daemon = True
            self._pulse_timer.start()
        self._render_icon()

    def _end_pulse(self) -> None:
        with self._lock:
            self._pulsing = False
            self._pulse_timer = None
        self._render_icon()

    def show_hold_countdown(self, remaining: float | None) -> None:
        """Esc is being held: show the seconds left in the tooltip (None clears it)."""
        self._hold_remaining = remaining
        self.refresh()

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> Any:
        import pystray

        def pause_label(_item: Any) -> str:
            return "Resume" if self._is_paused() else "Pause"

        def on_toggle(_icon: Any, _item: Any) -> None:
            try:
                self._on_toggle_pause()
            finally:
                self.refresh()

        def on_open(_icon: Any, _item: Any) -> None:
            self.launch_settings_subprocess()

        def on_feedback(_icon: Any, _item: Any) -> None:
            self.launch_settings_subprocess(screen="feedback")

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
            pystray.MenuItem(f"Open {APP_NAME}", on_open, default=True),
            pystray.MenuItem(pause_label, on_toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Send feedback…", on_feedback),
            pystray.MenuItem("Sponsor Typen on GitHub…", on_sponsor),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Quit {APP_NAME}", on_quit),
        )

    def tooltip(self) -> str:
        return tooltip_for(
            paused=self._is_paused(),
            needs_attention=self._needs_attention(),
            hold_remaining=self._hold_remaining,
        )[:TOOLTIP_LIMIT]

    def _render_icon(self) -> None:
        if self._icon is None:
            return
        try:
            paused = self._is_paused() or self._needs_attention()
            self._icon.icon = self.create_tray_icon_image(
                active=not paused,
                theme=self._theme,
                accent=(self._pulsing or self._hold_remaining is not None) and not paused,
            )
        except Exception:
            log.exception("tray icon render failed")

    def refresh(self) -> None:
        """Re-render icon, tooltip and menu after a state change (thread-safe enough for pystray)."""
        if self._icon is None:
            return
        try:
            self._theme = branding.tray_theme()
            self._render_icon()
            self._icon.title = self.tooltip()
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
            name="Typen",
            icon=self.create_tray_icon_image(active=not self._is_paused(), theme=self._theme),
            title=self.tooltip(),
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
        with self._lock:
            if self._pulse_timer is not None:
                self._pulse_timer.cancel()
                self._pulse_timer = None
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
