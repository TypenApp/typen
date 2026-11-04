"""
macOS Quartz Event Tap Manager (`CGEventTapCreate`).

- Monitors global key-down and mouse-down events on a dedicated CFRunLoop thread.
- Translates each key-down to the Unicode text it produces for the *current*
  keyboard layout via `CGEventKeyboardGetUnicodeString` (dead keys and
  non-US layouts included), falling back to the virtual-keycode table for
  control keys.
- Ignores synthetic events carrying `MACOS_EVENT_USER_DATA_TAG`.
- Re-enables the tap if macOS sends `kCGEventTapDisabledByTimeout`.
- `start()` blocks until the tap is actually created and raises
  `QuartzTapError` (with user-facing remediation) when macOS refuses because
  Input Monitoring / Accessibility permission has not been granted. The first
  attempt also triggers the system permission prompt.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Final

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

TAP_CREATE_TIMEOUT_S: Final[float] = 5.0

PERMISSION_REMEDIATION: Final[str] = (
    "Open System Settings → Privacy & Security → Input Monitoring and enable AutoCorrect, "
    "then also enable it under Accessibility (needed to type corrections). "
    "Quit and reopen AutoCorrect afterwards."
)


class QuartzTapError(RuntimeError):
    """Raised by `start()` when the event tap cannot be installed."""

    def __init__(self, message: str, remediation: str = PERMISSION_REMEDIATION) -> None:
        super().__init__(message)
        self.remediation = remediation


def build_key_event(
    keycode: int,
    flags: int,
    unicode_text: str,
    timestamp_ms: float,
    *,
    mask_command: int,
    mask_control: int,
    mask_alternate: int,
    mask_shift: int,
) -> KeyEvent:
    """
    Pure translation helper (unit-tested on every OS): combine a virtual
    keycode, modifier flags and the layout-translated Unicode text into a
    `KeyEvent`. Chorded shortcuts (Cmd/Ctrl) carry no character so the session
    treats them as buffer-invalidating, exactly like the Win32 hook.
    """
    cmd = bool(flags & mask_command)
    ctrl = bool(flags & mask_control)
    alt = bool(flags & mask_alternate)
    shift = bool(flags & mask_shift)
    key_name = MACOS_KEYCODE_MAP.get(keycode, "")
    if keycode == 49:
        char = " "
    elif keycode in (36, 76):
        char = "\n"
    elif key_name:
        char = ""  # navigation / editing key
    else:
        char = "" if (cmd or ctrl) else unicode_text
        # Option-chords on macOS legitimately type characters (é, ß, …); keep
        # them, but strip ASCII control characters some layouts emit.
        if char and (ord(char[0]) < 0x20 or char[0] == "\x7f"):
            char = ""
    if not key_name and char:
        key_name = char
    return KeyEvent(
        key_name=key_name,
        char=char,
        timestamp_ms=timestamp_ms,
        ctrl_pressed=ctrl,
        alt_pressed=alt and not char,  # Option used purely as a chord, not to type a glyph
        meta_pressed=cmd,
        shift_pressed=shift,
        is_injected=False,
    )


class QuartzEventTapManager:
    """
    Manages the macOS `CGEventTap` runloop on a dedicated background thread
    and cleanly disables the tap on stop.
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
        self._started = threading.Event()
        self._start_error: QuartzTapError | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @staticmethod
    def is_self_injected(user_data_field: int) -> bool:
        return user_data_field == MACOS_EVENT_USER_DATA_TAG

    # ------------------------------------------------------------ permissions

    @staticmethod
    def request_permissions(prompt: bool = True) -> tuple[bool, bool]:
        """
        Return `(input_monitoring_ok, accessibility_ok)`; with `prompt=True`
        macOS shows its own consent dialogs for whichever is missing.
        """
        if sys.platform != "darwin":
            return False, False
        listen_ok = True
        ax_ok = True
        try:
            import Quartz  # type: ignore[import-not-found]

            if hasattr(Quartz, "CGPreflightListenEventAccess"):
                listen_ok = bool(Quartz.CGPreflightListenEventAccess())
                if not listen_ok and prompt and hasattr(Quartz, "CGRequestListenEventAccess"):
                    listen_ok = bool(Quartz.CGRequestListenEventAccess())
        except Exception:
            pass
        try:
            from ApplicationServices import (  # type: ignore[import-not-found]
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )

            ax_ok = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
        except Exception:
            pass
        return listen_ok, ax_ok

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._running:
            return
        if sys.platform != "darwin":
            raise QuartzTapError(
                "Quartz event taps are only available on macOS",
                "This build of the macOS adapter cannot run on this operating system.",
            )
        try:
            import Quartz  # noqa: F401  # type: ignore[import-not-found]
        except ImportError as exc:
            raise QuartzTapError(
                f"pyobjc Quartz framework is not installed: {exc}",
                "Install the macOS extras (`pip install 'autocorrect[macos]'`).",
            ) from exc

        listen_ok, ax_ok = self.request_permissions(prompt=True)
        if not listen_ok:
            raise QuartzTapError("Input Monitoring permission has not been granted")

        self._started.clear()
        self._start_error = None
        self._running = True
        self._thread = threading.Thread(target=self._run_tap_loop, name="QuartzEventTapThread", daemon=True)
        self._thread.start()
        if not self._started.wait(TAP_CREATE_TIMEOUT_S):
            self.stop()
            raise QuartzTapError("Timed out waiting for the Quartz event tap to start")
        if self._start_error is not None:
            self._running = False
            self._thread = None
            raise self._start_error
        if not ax_ok:
            # Listening works, but injections will be dropped until Accessibility is granted.
            # Surface it as a failure so the UI tells the user, and release the tap.
            self.stop()
            raise QuartzTapError("Accessibility permission has not been granted")

    def stop(self) -> None:
        if not self._running and self._thread is None:
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
        self._tap = None
        self._runloop = None

    # ------------------------------------------------------------ tap thread

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
                    Quartz.kCGEventOtherMouseDown,
                ):
                    self._on_mouse_click()
                    return event

                if event_type == Quartz.kCGEventKeyDown:
                    user_data = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData))
                    if self.is_self_injected(user_data):
                        return event
                    if int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)):
                        return event  # held key: not a new keystroke

                    keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
                    flags = int(Quartz.CGEventGetFlags(event))
                    text = ""
                    try:
                        # pyobjc signature: (event, maxStringLength, actualStringLength_out, unicodeString_out)
                        _, text = Quartz.CGEventKeyboardGetUnicodeString(event, 4, None, None)
                        text = str(text or "")
                    except Exception:
                        text = ""

                    evt = build_key_event(
                        keycode,
                        flags,
                        text,
                        time.perf_counter() * 1000.0,
                        mask_command=Quartz.kCGEventFlagMaskCommand,
                        mask_control=Quartz.kCGEventFlagMaskControl,
                        mask_alternate=Quartz.kCGEventFlagMaskAlternate,
                        mask_shift=Quartz.kCGEventFlagMaskShift,
                    )
                    action = self._on_key_event(evt)
                    if action == KeyAction.SUPPRESS_AND_INJECT:
                        return None
                return event

            mask = (
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventOtherMouseDown)
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
                self._start_error = QuartzTapError(
                    "CGEventTapCreate returned NULL (Input Monitoring / Accessibility denied)"
                )
                self._running = False
                self._started.set()
                return

            source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._runloop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._runloop, source, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(self._tap, True)
            self._started.set()
            Quartz.CFRunLoopRun()
        except Exception as exc:
            self._start_error = QuartzTapError(f"Quartz event tap failed: {exc}")
            self._running = False
            self._started.set()
