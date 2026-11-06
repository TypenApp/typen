"""
Hold-Esc switch: hold Esc for `hold_seconds` (default 10) anywhere and typing
assistance toggles between paused and active (the daemon decides what the
trigger means; this module only detects the hold).

The watchdog is deliberately independent of the input hooks. It does not sit
in the hook chain, it does not depend on the dispatcher worker, and it uses a
plain key-state *poll* (`GetAsyncKeyState`, `CGEventSourceKeyState`,
`XQueryKeymap`) on its own thread. If the hook machinery is the thing that
went wrong, the kill switch still works.

Platform probes return True while Esc is physically down. Where no global
probe exists (Wayland) `create_escape_probe()` returns None and the switch
reports itself unsupported; the tray and `--stop` remain the fallback.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Final

log = logging.getLogger(__name__)

DEFAULT_HOLD_SECONDS: Final[float] = 10.0
LEGACY_DEFAULT_HOLD_SECONDS: Final[float] = 15.0
DEFAULT_POLL_INTERVAL_S: Final[float] = 0.1
MIN_HOLD_SECONDS: Final[float] = 5.0
MAX_HOLD_SECONDS: Final[float] = 120.0
PREF_KEY_HOLD_SECONDS: Final[str] = "panic_hold_seconds"
PREF_KEY_ENABLED: Final[str] = "panic_hotkey_enabled"
PREF_KEY_HOLD_MIGRATED: Final[str] = "panic_hold_seconds_migrated_v2"


def migrate_hold_seconds(
    get_setting: Callable[[str, str | None], str | None],
    set_setting: Callable[[str, str], None],
) -> float:
    """
    Read the stored hold time, moving a never-customised legacy 15 s default to
    the new 10 s default exactly once. `get_setting(key, default)` and
    `set_setting(key, value)` are the preference-store accessors.
    """
    raw = get_setting(PREF_KEY_HOLD_SECONDS, None)
    if get_setting(PREF_KEY_HOLD_MIGRATED, "false") != "true":
        set_setting(PREF_KEY_HOLD_MIGRATED, "true")
        try:
            stored = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            stored = None
        if stored is None or stored == LEGACY_DEFAULT_HOLD_SECONDS:
            set_setting(PREF_KEY_HOLD_SECONDS, str(DEFAULT_HOLD_SECONDS))
            return DEFAULT_HOLD_SECONDS
    return clamp_hold_seconds(raw)


def clamp_hold_seconds(value: float | str | None) -> float:
    try:
        v = float(value) if value is not None else DEFAULT_HOLD_SECONDS
    except (TypeError, ValueError):
        v = DEFAULT_HOLD_SECONDS
    return max(MIN_HOLD_SECONDS, min(MAX_HOLD_SECONDS, v))


# --------------------------------------------------------------------- probes


def _windows_probe() -> Callable[[], bool] | None:
    from autocorrect.adapters.windows import win32_api as w32
    from autocorrect.adapters.windows.win_keymap import VK_ESCAPE

    if w32.user32 is None:
        return None
    user32 = w32.user32

    def is_down() -> bool:
        return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)

    return is_down


def _macos_probe() -> Callable[[], bool] | None:
    try:
        import Quartz  # type: ignore[import-not-found]
    except ImportError:
        return None
    state = Quartz.kCGEventSourceStateCombinedSessionState
    escape_keycode = 53

    def is_down() -> bool:
        return bool(Quartz.CGEventSourceKeyState(state, escape_keycode))

    return is_down


def _x11_probe() -> Callable[[], bool] | None:
    try:
        from Xlib import display as xdisplay  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        disp = xdisplay.Display()
    except Exception:
        return None
    xk_escape = 0xFF1B
    keycode = int(disp.keysym_to_keycode(xk_escape))
    if not keycode:
        return None

    def is_down() -> bool:
        keymap = disp.query_keymap()
        return bool((keymap[keycode // 8] >> (keycode % 8)) & 1)

    return is_down


def create_escape_probe(platform: str | None = None) -> Callable[[], bool] | None:
    """Return `is_escape_down()` for this platform, or None when no global probe exists."""
    plat = platform or sys.platform
    try:
        if plat == "win32":
            return _windows_probe()
        if plat == "darwin":
            return _macos_probe()
        if plat.startswith("linux"):
            from autocorrect.adapters.linux.session_type import LinuxSessionType, detect_linux_session

            if detect_linux_session() == LinuxSessionType.X11:
                return _x11_probe()
            return None
    except Exception:
        log.exception("escape probe unavailable")
    return None


# ------------------------------------------------------------------- watchdog


class KillSwitch:
    """
    Poll `is_escape_down` every `poll_interval_s`; when Esc has been held
    continuously for `hold_seconds`, call `on_trigger(reason)` once and
    require a release before it can fire again.

    `hold_progress` (0..1) is exposed so a UI can show a countdown, and
    `on_hold_progress(seconds_remaining)` (optional) is called on every poll
    while Esc is down once the hold is at least a third of the way, then once
    with None when the key is released or the switch fires.
    """

    def __init__(
        self,
        is_escape_down: Callable[[], bool] | None,
        on_trigger: Callable[[str], None],
        *,
        hold_seconds: float = DEFAULT_HOLD_SECONDS,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] | None = None,
        on_hold_progress: Callable[[float | None], None] | None = None,
    ) -> None:
        self._probe = is_escape_down
        self._on_trigger = on_trigger
        self._on_hold_progress = on_hold_progress
        self._progress_shown = False
        self._hold = clamp_hold_seconds(hold_seconds)
        self._poll = poll_interval_s
        self._clock = clock
        self._stop = threading.Event()
        self._sleeper = sleeper or (lambda s: self._stop.wait(s))
        self._thread: threading.Thread | None = None
        self._held_since: float | None = None
        self._armed = True
        self.trigger_count = 0

    @property
    def is_supported(self) -> bool:
        return self._probe is not None

    @property
    def hold_seconds(self) -> float:
        return self._hold

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def hold_progress(self) -> float:
        if self._held_since is None:
            return 0.0
        return max(0.0, min(1.0, (self._clock() - self._held_since) / self._hold))

    def set_hold_seconds(self, seconds: float) -> None:
        self._hold = clamp_hold_seconds(seconds)

    def start(self) -> None:
        if self._probe is None or self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="autocorrect-kill-switch", daemon=True)
        self._thread.start()
        log.info(
            "hold-Esc switch armed: hold Esc for %.0f s to pause or resume typing assistance", self._hold
        )

    def stop(self) -> None:
        self._stop.set()
        if (
            self._thread is not None
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=2.0)
        self._thread = None

    # The polling step is separate from the loop so tests can drive it with a fake clock.
    def poll_once(self) -> bool:
        """Sample the key once; return True if the switch fired on this sample."""
        if self._probe is None:
            return False
        try:
            down = bool(self._probe())
        except Exception:
            log.exception("escape probe raised; disarming kill switch")
            self._probe = None
            return False
        now = self._clock()
        if not down:
            self._held_since = None
            self._armed = True
            self._report_progress(None)
            return False
        if self._held_since is None:
            self._held_since = now
            return False
        elapsed = now - self._held_since
        if self._armed and elapsed >= self._hold:
            self._armed = False
            self.trigger_count += 1
            self._report_progress(None)
            reason = f"Esc held for {self._hold:.0f} s"
            log.info("hold-Esc switch triggered: %s", reason)
            try:
                self._on_trigger(reason)
            except Exception:
                log.exception("hold-Esc handler raised")
            return True
        if self._armed and elapsed >= self._hold / 3.0:
            self._report_progress(max(0.0, self._hold - elapsed))
        return False

    def _report_progress(self, remaining: float | None) -> None:
        if self._on_hold_progress is None:
            return
        if remaining is None and not self._progress_shown:
            return
        self._progress_shown = remaining is not None
        try:
            self._on_hold_progress(remaining)
        except Exception:
            log.exception("hold progress handler raised")

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._sleeper(self._poll)
