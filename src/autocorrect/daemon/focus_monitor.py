"""
Foreground-focus monitor.

Polls the platform `FocusInspectorPort` on a background thread and notifies
the daemon whenever the focused application / control changes. This is what
turns the password-field, terminal, excluded-app and per-application-profile
flags from inert defaults into live behaviour: without it `FocusContext()`
stays empty and the engine corrects text everywhere, including password boxes.

The poll interval is deliberately short (default 150 ms) but the inspector
calls are cheap Win32/AX/X11 queries; the callback fires only on change.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from autocorrect.input.ports import FocusContext, FocusInspectorPort


class FocusMonitor:
    """Background poller that emits `on_change(FocusContext)` on focus transitions."""

    def __init__(
        self,
        inspector: FocusInspectorPort,
        on_change: Callable[[FocusContext], None],
        poll_interval_s: float = 0.15,
    ) -> None:
        self._inspector = inspector
        self._on_change = on_change
        self._interval = poll_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: FocusContext | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_focus(self) -> FocusContext | None:
        return self._last

    def poll_once(self) -> FocusContext | None:
        """Query the inspector once; fire the callback if focus changed. Returns new focus or None."""
        try:
            focus = self._inspector.get_current_focus()
        except Exception:
            return None
        if focus != self._last:
            self._last = focus
            try:
                self._on_change(focus)
            except Exception:
                pass
            return focus
        return None

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="autocorrect-focus-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._last = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._interval)
