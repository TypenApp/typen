"""
macOS Quartz Event Tap Manager (`CGEventTapCreate`).
Monitors global key-down and mouse-click events on macOS, ignores synthetic
events carrying `MACOS_EVENT_USER_DATA_TAG`, and automatically re-enables
the tap if macOS sends `kCGEventTapDisabledByTimeout`.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Final

from autocorrect.adapters.macos.quartz_injector import (
    MACOS_EVENT_USER_DATA_TAG,
    MACOS_KEYCODE_DELETE,
)
from autocorrect.input.ports import KeyAction, KeyEvent

MACOS_KEYCODE_MAP: Final[dict[int, str]] = {
    MACOS_KEYCODE_DELETE: "Backspace",
    36: "Return",
    76: "Enter",
    48: "Tab",
    49: "Space",
    53: "Escape",
    115: "Home",
    116: "PageUp",
    117: "Delete",
    119: "End",
    121: "PageDown",
    123: "Left",
    124: "Right",
    125: "Down",
    126: "Up",
}


class QuartzEventTapManager:
    """
    Manages the macOS `CGEventTap` runloop on a dedicated background thread
    and cleanly disables the tap on stop or trial expiry.
    """

    def __init__(
        self,
        on_key_event: Callable[[KeyEvent], KeyAction],
        on_mouse_click: Callable[[], None],
    ) -> None:
        self._on_key_event = on_key_event
        self._on_mouse_click = on_mouse_click
        self._running = False
        self._thread: threading.Thread | None = None
        self._tap = None
        self._runloop = None

    @property
    def is_running(self) -> bool:
        return self._running

    @staticmethod
    def is_self_injected(user_data_field: int) -> bool:
        return user_data_field == MACOS_EVENT_USER_DATA_TAG

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if sys.platform == "darwin":
            self._thread = threading.Thread(
                target=self._run_tap_loop, name="QuartzEventTapThread", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if sys.platform == "darwin":
            try:
                import Quartz  # type: ignore[import-not-found]

                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, False)
                if self._runloop is not None:
                    Quartz.CFRunLoopStop(self._runloop)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run_tap_loop(self) -> None:
        try:
            import time

            import Quartz  # type: ignore[import-not-found]

            def _tap_callback(proxy: object, event_type: int, event: object, refcon: object) -> object:
                if event_type in (
                    Quartz.kCGEventTapDisabledByTimeout,
                    Quartz.kCGEventTapDisabledByUserInput,
                ):
                    if self._running and self._tap is not None:
                        Quartz.CGEventTapEnable(self._tap, True)
                    return event

                if event_type in (
                    Quartz.kCGEventLeftMouseDown,
                    Quartz.kCGEventRightMouseDown,
                ):
                    self._on_mouse_click()
                    return event

                if event_type == Quartz.kCGEventKeyDown:
                    user_data = int(
                        Quartz.CGEventGetIntegerValueField(
                            event, Quartz.kCGEventSourceUserData
                        )
                    )
                    if self.is_self_injected(user_data):
                        return event

                    keycode = int(
                        Quartz.CGEventGetIntegerValueField(
                            event, Quartz.kCGKeyboardEventKeycode
                        )
                    )
                    flags = int(Quartz.CGEventGetFlags(event))
                    cmd = bool(flags & Quartz.kCGEventFlagMaskCommand)
                    ctrl = bool(flags & Quartz.kCGEventFlagMaskControl)
                    alt = bool(flags & Quartz.kCGEventFlagMaskAlternate)
                    shift = bool(flags & Quartz.kCGEventFlagMaskShift)

                    key_name = MACOS_KEYCODE_MAP.get(keycode, "")
                    char_str = " " if keycode == 49 else ("\n" if keycode in (36, 76) else "")

                    evt = KeyEvent(
                        key_name=key_name or char_str,
                        char=char_str,
                        timestamp_ms=time.perf_counter() * 1000.0,
                        ctrl_pressed=ctrl,
                        alt_pressed=alt,
                        meta_pressed=cmd,
                        shift_pressed=shift,
                        is_injected=False,
                    )
                    action = self._on_key_event(evt)
                    if action == KeyAction.SUPPRESS_AND_INJECT:
                        return None
                return event

            mask = (
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown)
            )
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault,
                mask,
                _tap_callback,
                None,
            )
            if self._tap is None:
                self._running = False
                return

            source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._runloop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(
                self._runloop, source, Quartz.kCFRunLoopCommonModes
            )
            Quartz.CGEventTapEnable(self._tap, True)
            Quartz.CFRunLoopRun()
        except Exception:
            self._running = False
