"""
Single-threaded input dispatcher.

OS hook callbacks (Win32 `WH_KEYBOARD_LL`, Quartz event tap, XRecord) run on
threads the operating system is waiting on: anything slow inside them delays
input for *every* application. The dispatcher moves all real work off those
threads: a hook only builds a `KeyEvent` and `post_key()`s it, and one worker
thread drives `InputSessionManager` (which is documented single-threaded) for
key events, mouse clicks and focus changes alike, so the session is never
touched from two threads at once.

The worker also keeps simple health statistics (queue depth, handler
duration, slow-handler count). When the queue backs up or handlers keep
exceeding their budget, `on_overload` fires so the daemon can release the OS
hooks rather than let typing degrade.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from autocorrect.input.ports import FocusContext, KeyEvent

log = logging.getLogger(__name__)

DEFAULT_HANDLER_BUDGET_MS: Final[float] = 50.0
DEFAULT_MAX_QUEUE_DEPTH: Final[int] = 128
DEFAULT_SLOW_HANDLER_LIMIT: Final[int] = 10
SLOW_WINDOW_S: Final[float] = 10.0


@dataclass
class DispatcherStats:
    posted: int = 0
    handled: int = 0
    dropped: int = 0
    slow_handlers: int = 0
    max_handler_ms: float = 0.0
    last_handler_ms: float = 0.0
    max_queue_depth: int = 0
    _slow_timestamps: list[float] = field(default_factory=list, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "posted": self.posted,
            "handled": self.handled,
            "dropped": self.dropped,
            "slow_handlers": self.slow_handlers,
            "max_handler_ms": round(self.max_handler_ms, 2),
            "last_handler_ms": round(self.last_handler_ms, 2),
            "max_queue_depth": self.max_queue_depth,
        }


class InputDispatcher:
    """
    Serialises key, mouse and focus callbacks onto one worker thread.

    `on_key_event`, `on_mouse_click` and `on_focus_changed` are the session
    entry points; they are invoked on the worker only. `post_*` never blocks
    and never raises.
    """

    def __init__(
        self,
        on_key_event: Callable[[KeyEvent], Any],
        on_mouse_click: Callable[[], Any],
        on_focus_changed: Callable[[FocusContext], Any] | None = None,
        *,
        on_overload: Callable[[str], None] | None = None,
        handler_budget_ms: float = DEFAULT_HANDLER_BUDGET_MS,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
        slow_handler_limit: int = DEFAULT_SLOW_HANDLER_LIMIT,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._on_key_event = on_key_event
        self._on_mouse_click = on_mouse_click
        self._on_focus_changed = on_focus_changed
        self._on_overload = on_overload
        self._budget_ms = handler_budget_ms
        self._max_depth = max_queue_depth
        self._slow_limit = slow_handler_limit
        self._clock = clock
        self._queue: queue.SimpleQueue[tuple[str, Any] | None] = queue.SimpleQueue()
        self._depth = 0
        self._depth_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._overloaded = False
        self.stats = DispatcherStats()

    # ------------------------------------------------------------ lifecycle

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def queue_depth(self) -> int:
        return self._depth

    def start(self) -> None:
        if self.is_running:
            return
        self._running = True
        self._overloaded = False
        self._thread = threading.Thread(target=self._run, name="autocorrect-input-dispatcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if not self._running:
            return
        self._running = False
        self._queue.put(None)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    # ---------------------------------------------------------------- posting

    def post_key(self, event: KeyEvent) -> None:
        self._post("key", event)

    def post_mouse_click(self) -> None:
        self._post("mouse", None)

    def post_focus(self, focus: FocusContext) -> None:
        self._post("focus", focus)

    def post_call(self, fn: Callable[[], Any]) -> None:
        """Run an arbitrary callable on the worker (used for pause/resume and resets)."""
        self._post("call", fn)

    def run_sync(self, fn: Callable[[], Any], timeout: float = 1.0) -> Any:
        """
        Run `fn` on the worker and wait for its result. Falls back to calling
        inline when the worker is not running (tests, dry-run) so callers never
        need to special-case it.
        """
        if not self.is_running or threading.current_thread() is self._thread:
            return fn()
        done = threading.Event()
        box: dict[str, Any] = {}

        def _wrapped() -> None:
            try:
                box["result"] = fn()
            except Exception as exc:  # pragma: no cover - surfaced to caller
                box["error"] = exc
            finally:
                done.set()

        self._post("call", _wrapped)
        if not done.wait(timeout):
            raise TimeoutError("input dispatcher did not run the callable in time")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _post(self, kind: str, payload: Any) -> None:
        if not self._running:
            # Nobody is draining the queue: run focus/call items inline so state stays
            # coherent in dry-run mode, but drop key/mouse events (there is no hook).
            if kind == "focus" and self._on_focus_changed is not None:
                self._safe(self._on_focus_changed, payload)
            elif kind == "call":
                self._safe(payload)
            return
        with self._depth_lock:
            if self._depth >= self._max_depth:
                self.stats.dropped += 1
                self._trip_overload(f"input queue exceeded {self._max_depth} pending events")
                return
            self._depth += 1
            if self._depth > self.stats.max_queue_depth:
                self.stats.max_queue_depth = self._depth
        self.stats.posted += 1
        self._queue.put((kind, payload))

    # ----------------------------------------------------------------- worker

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            with self._depth_lock:
                self._depth = max(0, self._depth - 1)
            kind, payload = item
            started = self._clock()
            try:
                if kind == "key":
                    self._on_key_event(payload)
                elif kind == "mouse":
                    self._on_mouse_click()
                elif kind == "focus":
                    if self._on_focus_changed is not None:
                        self._on_focus_changed(payload)
                elif kind == "call":
                    payload()
            except Exception:
                log.exception("input handler (%s) raised", kind)
            finally:
                self._record(started)
            if not self._running:
                break

    def _record(self, started: float) -> None:
        elapsed_ms = (self._clock() - started) * 1000.0
        st = self.stats
        st.handled += 1
        st.last_handler_ms = elapsed_ms
        if elapsed_ms > st.max_handler_ms:
            st.max_handler_ms = elapsed_ms
        if elapsed_ms > self._budget_ms:
            st.slow_handlers += 1
            now = self._clock()
            st._slow_timestamps.append(now)
            st._slow_timestamps = [t for t in st._slow_timestamps if now - t <= SLOW_WINDOW_S]
            log.warning("input handler took %.1f ms (budget %.0f ms)", elapsed_ms, self._budget_ms)
            if len(st._slow_timestamps) >= self._slow_limit:
                self._trip_overload(
                    f"{len(st._slow_timestamps)} handlers exceeded {self._budget_ms:.0f} ms "
                    f"within {SLOW_WINDOW_S:.0f} s"
                )

    def _trip_overload(self, reason: str) -> None:
        if self._overloaded:
            return
        self._overloaded = True
        log.error("input dispatcher overloaded: %s", reason)
        if self._on_overload is not None:
            try:
                self._on_overload(reason)
            except Exception:
                log.exception("on_overload handler raised")

    @staticmethod
    def _safe(fn: Callable[..., Any], *args: Any) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("inline input handler raised")
