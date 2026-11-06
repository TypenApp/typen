"""
Linux X11 global keyboard/mouse hook via the XRecord extension.

XRecord is *passive*: it reports device events after the X server has
already delivered them, so unlike `WH_KEYBOARD_LL` we can never suppress the
delimiter keystroke. The daemon therefore drives `InputSessionManager` with
`suppress_delimiter_on_replace=False`, whose replacement plans delete the
already-typed delimiter and re-inject it after the corrected word.

Self-generated XTest events are filtered through the shared
`X11SyntheticTracker` ledger populated by `X11TextInjector`.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from autocorrect.adapters.linux.x11_adapter import (
    MODIFIER_KEYSYMS,
    X11SyntheticTracker,
    shared_synthetic_tracker,
    translate_x11_key,
)
from autocorrect.input.ports import KeyAction, KeyEvent

log = logging.getLogger(__name__)


class X11HookError(RuntimeError):
    """Raised by `start()` when the hook cannot be installed; `remediation` is user-facing."""

    def __init__(self, message: str, remediation: str) -> None:
        super().__init__(message)
        self.remediation = remediation


class X11KeyboardMouseHook:
    """
    Runs an XRecord context on a dedicated thread, translating key presses to
    `KeyEvent`s and button presses to caret-invalidation callbacks.
    """

    def __init__(
        self,
        on_key_event: Callable[[KeyEvent], KeyAction],
        on_mouse_click: Callable[[], None],
        tracker: X11SyntheticTracker | None = None,
        *,
        on_thread_exit: Callable[[BaseException | None], None] | None = None,
    ) -> None:
        self._on_key_event = on_key_event
        self._on_mouse_click = on_mouse_click
        self._on_thread_exit = on_thread_exit
        self._tracker = tracker or shared_synthetic_tracker()
        self._running = False
        self._thread: threading.Thread | None = None
        self._record_display: Any = None
        self._local_display: Any = None
        self._context: Any = None
        self._shift_level_cache: dict[int, int] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._running:
            return
        if not sys.platform.startswith("linux"):
            raise X11HookError(
                "X11 hook is only available on Linux",
                "This build of the X11 adapter cannot run on this operating system.",
            )
        try:
            from Xlib import display as xdisplay  # type: ignore[import-not-found]
            from Xlib.ext import record  # type: ignore[import-not-found]
        except ImportError as exc:
            raise X11HookError(
                f"python-xlib is not installed: {exc}",
                "Install the Linux extras (`pip install 'autocorrect[linux]'`) or the "
                "python3-xlib package from your distribution.",
            ) from exc

        try:
            self._record_display = xdisplay.Display()
            self._local_display = xdisplay.Display()
        except Exception as exc:
            raise X11HookError(
                f"Cannot connect to the X server: {exc}",
                "AutoCorrect needs a running X11 session (DISPLAY). Under Wayland use the "
                "IBus engine instead.",
            ) from exc

        if not self._record_display.has_extension("RECORD"):
            raise X11HookError(
                "The X server does not expose the RECORD extension",
                "Enable the RECORD extension in your X server configuration, or use the IBus engine.",
            )
        if not self._local_display.has_extension("XTEST"):
            raise X11HookError(
                "The X server does not expose the XTEST extension",
                "XTest is required to inject corrections; enable it in your X server configuration.",
            )

        from Xlib import X  # type: ignore[import-not-found]

        self._context = self._record_display.record_create_context(
            0,
            [record.AllClients],
            [
                {
                    "core_requests": (0, 0),
                    "core_replies": (0, 0),
                    "ext_requests": (0, 0, 0, 0),
                    "ext_replies": (0, 0, 0, 0),
                    "delivered_events": (0, 0),
                    "device_events": (X.KeyPress, X.ButtonPress),
                    "errors": (0, 0),
                    "client_started": False,
                    "client_died": False,
                }
            ],
        )
        self._running = True
        self._thread = threading.Thread(target=self._run_record_loop, name="X11RecordHookThread", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            if self._context is not None and self._local_display is not None:
                # Must be issued from a *different* connection than the one blocked in enable_context.
                self._local_display.record_disable_context(self._context)
                self._local_display.flush()
        except Exception:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        for attr in ("_record_display", "_local_display"):
            disp = getattr(self, attr)
            if disp is not None:
                try:
                    if attr == "_record_display" and self._context is not None:
                        disp.record_free_context(self._context)
                    disp.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._context = None
        self._tracker.clear()

    # ------------------------------------------------------------- recording

    def _run_record_loop(self) -> None:
        exc: BaseException | None = None
        try:
            self._record_display.record_enable_context(self._context, self._record_callback)
        except Exception as e:
            if self._running:  # a stop() in progress closes the connection on purpose
                exc = e
                log.exception("XRecord loop died")
        finally:
            was_running = self._running
            self._running = False
            if was_running and self._on_thread_exit is not None:
                try:
                    self._on_thread_exit(exc)
                except Exception:
                    log.exception("on_thread_exit raised")

    def _keysym_for(self, keycode: int, state: int) -> int:
        from autocorrect.adapters.linux.x11_adapter import LOCK_MASK, MOD5_MASK, SHIFT_MASK

        disp = self._local_display
        level = 0
        shifted = bool(state & SHIFT_MASK)
        if state & MOD5_MASK:
            level = 3 if shifted else 2  # AltGr levels
        elif shifted:
            level = 1
        keysym = int(disp.keycode_to_keysym(keycode, level))
        if keysym == 0 and level:
            keysym = int(disp.keycode_to_keysym(keycode, 0))
        # Caps Lock flips the case of alphabetic keysyms only.
        if state & LOCK_MASK and not shifted and 0x61 <= keysym <= 0x7A:
            keysym -= 0x20
        elif state & LOCK_MASK and shifted and 0x41 <= keysym <= 0x5A:
            keysym += 0x20
        return keysym

    def _record_callback(self, reply: Any) -> None:
        if not self._running:
            return
        if reply.category != 0 or not reply.data or reply.data[0] < 2:
            return  # Not a device event (category 0 == FromServer)
        from Xlib import X  # type: ignore[import-not-found]
        from Xlib.protocol import rq  # type: ignore[import-not-found]

        data = reply.data
        while len(data):
            event, data = rq.EventField(None).parse_binary_value(
                data, self._record_display.display, None, None
            )
            if event.type == X.ButtonPress:
                if event.detail in (1, 2, 3):  # left/middle/right; 4-7 are wheel/scroll
                    self._on_mouse_click()
                continue
            if event.type not in (X.KeyPress, X.KeyRelease):
                continue
            is_press = event.type == X.KeyPress
            if self._tracker.consume_if_expected(event.detail, is_press):
                continue  # Our own XTest injection.
            if not is_press:
                continue
            try:
                keysym = self._keysym_for(event.detail, event.state)
            except Exception:
                continue
            if keysym in MODIFIER_KEYSYMS or keysym == 0:
                continue
            key_name, char, ctrl, alt, meta, shift = translate_x11_key(keysym, event.state)
            evt = KeyEvent(
                key_name=key_name,
                char=char,
                timestamp_ms=time.perf_counter() * 1000.0,
                ctrl_pressed=ctrl,
                alt_pressed=alt,
                meta_pressed=meta,
                shift_pressed=shift,
                is_injected=False,
            )
            self._on_key_event(evt)
