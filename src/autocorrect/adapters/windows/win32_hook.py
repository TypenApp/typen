"""
Windows Low-Level Keyboard Hook (`WH_KEYBOARD_LL`) + Raw Input mouse sink.

Design rules, all of which exist because a slow or crashing low-level hook
stalls keyboard input for *every* process on the machine:

1. Every Win32 call goes through `win32_api` with explicit `argtypes`, so
   64-bit `lParam` pointers can never overflow ctypes' default `int`.
2. The hook callback never raises: any exception is logged and the event is
   passed down the chain with `CallNextHookEx`.
3. The callback does the minimum (`ToUnicodeEx` + build `KeyEvent`) and hands
   the event to `on_key_event`, which in the daemon is the non-blocking
   `InputDispatcher.post_key`. Word evaluation and `SendInput` happen on the
   dispatcher's worker thread, never inside the hook.
4. Mouse clicks come from Raw Input (`WM_INPUT`, `RIDEV_INPUTSINK`) on a
   message-only window instead of `WH_MOUSE_LL`. Raw Input is asynchronous
   and only fires for button changes, so the pointer can never be slowed.
5. Callback timing is recorded; if callbacks repeatedly exceed their budget
   `on_unhealthy` fires so the daemon can release the hook. The thread's exit
   (clean or by exception) is reported through `on_thread_exit`.

Global hotkeys (pause, open settings) are registered with `RegisterHotKey`
on the same message loop and delivered through `on_hotkey(id)`.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from autocorrect.adapters.windows import win32_api as w32
from autocorrect.adapters.windows.win32_injector import AUTOCORRECT_EXTRA_INFO_TAG
from autocorrect.adapters.windows.win_keymap import (
    VK_CAPITAL,
    VK_CONTROL,
    VK_LWIN,
    VK_MENU,
    VK_RWIN,
    VK_SHIFT,
    VK_TO_KEY_NAME,
)
from autocorrect.input.hotkeys import Hotkey
from autocorrect.input.ports import KeyAction, KeyEvent

log = logging.getLogger(__name__)

# Re-exported for callers/tests that referenced them here before win32_api existed.
WH_KEYBOARD_LL: Final[int] = w32.WH_KEYBOARD_LL
WM_KEYDOWN: Final[int] = w32.WM_KEYDOWN
WM_SYSKEYDOWN: Final[int] = w32.WM_SYSKEYDOWN
WM_QUIT: Final[int] = w32.WM_QUIT
HC_ACTION: Final[int] = w32.HC_ACTION
LLKHF_INJECTED: Final[int] = w32.LLKHF_INJECTED

HOOK_START_TIMEOUT_S: Final[float] = 5.0
DEFAULT_CALLBACK_BUDGET_MS: Final[float] = 20.0
DEFAULT_SLOW_CALLBACK_LIMIT: Final[int] = 20
SLOW_WINDOW_S: Final[float] = 10.0
_MODIFIER_VKS: Final[frozenset[int]] = frozenset({VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN})

_NAMED_VK: Final[dict[str, int]] = {name: vk for vk, name in VK_TO_KEY_NAME.items()}
_PUNCT_VK: Final[dict[str, int]] = {
    ",": 0xBC,
    ".": 0xBE,
    "+": 0xBB,
    "-": 0xBD,
    ";": 0xBA,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}


class Win32HookError(RuntimeError):
    """Raised by `start()` when the hook cannot be installed; `remediation` is user-facing."""

    def __init__(self, message: str, remediation: str = "") -> None:
        super().__init__(message)
        self.remediation = remediation or (
            "Restart Typen. If the problem persists, check logs/typen.log and report it."
        )


@dataclass
class HookStats:
    callbacks: int = 0
    slow_callbacks: int = 0
    exceptions: int = 0
    max_callback_ms: float = 0.0
    last_callback_ms: float = 0.0
    mouse_clicks: int = 0
    hotkeys: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "callbacks": self.callbacks,
            "slow_callbacks": self.slow_callbacks,
            "exceptions": self.exceptions,
            "max_callback_ms": round(self.max_callback_ms, 2),
            "last_callback_ms": round(self.last_callback_ms, 2),
            "mouse_clicks": self.mouse_clicks,
            "hotkeys": self.hotkeys,
        }


def hotkey_to_win32(hk: Hotkey) -> tuple[int, int] | None:
    """Map a parsed `Hotkey` to `(fsModifiers, vk)` for `RegisterHotKey`."""
    mods = w32.MOD_NOREPEAT
    if hk.ctrl:
        mods |= w32.MOD_CONTROL
    if hk.alt:
        mods |= w32.MOD_ALT
    if hk.shift:
        mods |= w32.MOD_SHIFT
    if hk.meta:
        mods |= w32.MOD_WIN
    key = hk.key
    if key in _NAMED_VK:
        return mods, _NAMED_VK[key]
    if key in _PUNCT_VK:
        return mods, _PUNCT_VK[key]
    if len(key) == 1 and (key.isascii() and key.isalnum()):
        return mods, ord(key.upper())
    if key.startswith("F") and key[1:].isdigit():
        return mods, 0x70 + int(key[1:]) - 1
    return None


class Win32KeyboardMouseHook:
    """
    Owns the hook thread: `WH_KEYBOARD_LL`, a message-only window receiving
    Raw Input mouse buttons and `WM_HOTKEY`, and the `GetMessageW` pump.
    """

    def __init__(
        self,
        on_key_event: Callable[[KeyEvent], KeyAction],
        on_mouse_click: Callable[[], None],
        *,
        hotkeys: Mapping[int, Hotkey] | None = None,
        on_hotkey: Callable[[int], None] | None = None,
        on_thread_exit: Callable[[BaseException | None], None] | None = None,
        on_unhealthy: Callable[[str], None] | None = None,
        callback_budget_ms: float = DEFAULT_CALLBACK_BUDGET_MS,
        slow_callback_limit: int = DEFAULT_SLOW_CALLBACK_LIMIT,
    ) -> None:
        self._on_key_event = on_key_event
        self._on_mouse_click = on_mouse_click
        self._hotkeys: dict[int, Hotkey] = dict(hotkeys or {})
        self._on_hotkey = on_hotkey
        self._on_thread_exit = on_thread_exit
        self._on_unhealthy = on_unhealthy
        self._budget_ms = callback_budget_ms
        self._slow_limit = slow_callback_limit
        self._slow_times: list[float] = []
        self._unhealthy_reported = False
        self._kb_hook_id: Any = None
        self._hwnd: Any = None
        self._class_atom: Any = None
        self._class_name = f"TypenInputSink{os.getpid()}"
        self._registered_hotkeys: list[int] = []
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._running = False
        self._started = threading.Event()
        self._start_error: Win32HookError | None = None
        self._install_ok = False
        self._kb_cb: Any = None
        self._wnd_cb: Any = None
        self._last_exc_log = 0.0
        self.stats = HookStats()
        self.registered_hotkey_ids: list[int] = []

    # ------------------------------------------------------------ properties

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def hook_installed(self) -> bool:
        return bool(self._kb_hook_id)

    @staticmethod
    def is_self_injected(flags: int, dw_extra_info: int) -> bool:
        """True if the event carries our tag or was injected by any software (never re-evaluate those)."""
        return dw_extra_info == AUTOCORRECT_EXTRA_INFO_TAG or bool(flags & LLKHF_INJECTED)

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start the hook thread and block until the hook is installed (or raise `Win32HookError`)."""
        if self._running:
            return
        if sys.platform != "win32" or w32.user32 is None:
            raise Win32HookError(
                "Win32 hooks are only available on Windows",
                "This build of the Windows adapter cannot run on this operating system.",
            )
        self._started.clear()
        self._start_error = None
        self._install_ok = False
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, name="Win32HookThread", daemon=True)
        self._thread.start()
        if not self._started.wait(HOOK_START_TIMEOUT_S):
            self.stop()
            raise Win32HookError("Timed out waiting for the Win32 hook thread to start")
        if self._start_error is not None:
            self._running = False
            self._thread = None
            raise self._start_error

    def stop(self) -> None:
        """Safely release the keyboard hook, raw-input window and terminate the message pump."""
        if not self._running and self._thread is None:
            return
        self._running = False
        if sys.platform == "win32" and self._thread_id and w32.user32 is not None:
            w32.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if (
            self._thread is not None
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=2.0)
        self._thread = None

    # ------------------------------------------------------------ hook thread

    def _thread_main(self) -> None:
        exc: BaseException | None = None
        try:
            self._run_message_loop()
        except BaseException as e:  # noqa: BLE001 - reported, never swallowed silently
            exc = e
            log.exception("Win32 hook thread died")
            if not self._install_ok and self._start_error is None:
                self._start_error = (
                    e if isinstance(e, Win32HookError) else Win32HookError(f"Win32 hook thread failed: {e!r}")
                )
            self._started.set()
        finally:
            self._running = False
            if self._on_thread_exit is not None:
                try:
                    self._on_thread_exit(exc)
                except Exception:
                    log.exception("on_thread_exit raised")

    def _run_message_loop(self) -> None:
        user32 = w32.user32
        kernel32 = w32.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())

        self._kb_cb = w32.HOOKPROC(self._kb_proc)
        self._wnd_cb = w32.WNDPROC(self._wnd_proc)

        try:
            self._create_message_window()
            self._register_raw_mouse()
            self._register_hotkeys()

            self._kb_hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb, None, 0)
            if not self._kb_hook_id:
                err = w32.last_error()
                self._start_error = Win32HookError(
                    f"SetWindowsHookExW(WH_KEYBOARD_LL) failed: {w32.win_error_message(err)}",
                    "Another program may be blocking low-level hooks (anti-cheat, security software). "
                    "Close it or add Typen to its allow-list, then restart Typen.",
                )
                return
            log.info("Win32 WH_KEYBOARD_LL installed (thread %d, hwnd %s)", self._thread_id, self._hwnd)
            self._install_ok = True
            self._started.set()

            msg = w32.MSG()
            while self._running:
                rc = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if rc == 0 or rc == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._teardown()
            self._started.set()

    def _teardown(self) -> None:
        user32 = w32.user32
        if self._kb_hook_id:
            user32.UnhookWindowsHookEx(self._kb_hook_id)
            self._kb_hook_id = None
        for hk_id in self._registered_hotkeys:
            user32.UnregisterHotKey(self._hwnd, hk_id)
        self._registered_hotkeys = []
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._class_atom:
            user32.UnregisterClassW(self._class_name, w32.kernel32.GetModuleHandleW(None))
            self._class_atom = None
        log.info("Win32 hook released")

    # --------------------------------------------------- message-only window

    def _create_message_window(self) -> None:
        user32 = w32.user32
        hinst = w32.kernel32.GetModuleHandleW(None)
        wc = w32.WNDCLASSW()
        wc.lpfnWndProc = self._wnd_cb
        wc.hInstance = hinst
        wc.lpszClassName = self._class_name
        self._class_atom = user32.RegisterClassW(ctypes.byref(wc))
        if not self._class_atom:
            err = w32.last_error()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS: fine, reuse it
                raise Win32HookError(f"RegisterClassW failed: {w32.win_error_message(err)}")
        self._hwnd = user32.CreateWindowExW(
            0, self._class_name, "Typen input sink", 0, 0, 0, 0, 0, w32.HWND_MESSAGE, None, hinst, None
        )
        if not self._hwnd:
            raise Win32HookError(
                f"CreateWindowExW(HWND_MESSAGE) failed: {w32.win_error_message(w32.last_error())}"
            )

    def _register_raw_mouse(self) -> None:
        rid = w32.RAWINPUTDEVICE()
        rid.usUsagePage = w32.HID_USAGE_PAGE_GENERIC
        rid.usUsage = w32.HID_USAGE_GENERIC_MOUSE
        rid.dwFlags = w32.RIDEV_INPUTSINK
        rid.hwndTarget = self._hwnd
        if not w32.user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(w32.RAWINPUTDEVICE)):
            # Not fatal: typing still works, only click-invalidation of the word buffer is lost.
            log.warning("RegisterRawInputDevices(mouse) failed: %s", w32.win_error_message(w32.last_error()))

    def _register_hotkeys(self) -> None:
        for hk_id, hk in self._hotkeys.items():
            mapped = hotkey_to_win32(hk)
            if mapped is None:
                log.warning("hotkey %s (%d) cannot be mapped to a Win32 virtual key", hk.label(), hk_id)
                continue
            mods, vk = mapped
            if w32.user32.RegisterHotKey(self._hwnd, hk_id, mods, vk):
                self._registered_hotkeys.append(hk_id)
                log.info("registered global hotkey %s (id %d)", hk.label(), hk_id)
            else:
                log.warning(
                    "RegisterHotKey %s failed: %s (already taken by another app?)",
                    hk.label(),
                    w32.win_error_message(w32.last_error()),
                )
        self.registered_hotkey_ids = list(self._registered_hotkeys)

    def _wnd_proc(self, hwnd: Any, msg: int, w_param: int, l_param: int) -> int:
        try:
            if msg == w32.WM_INPUT:
                if self._raw_input_is_button_down(l_param):
                    self.stats.mouse_clicks += 1
                    self._on_mouse_click()
            elif msg == w32.WM_HOTKEY:
                self.stats.hotkeys += 1
                if self._on_hotkey is not None:
                    self._on_hotkey(int(w_param))
                return 0
        except Exception:
            self._log_exception("window procedure")
        return int(w32.user32.DefWindowProcW(hwnd, msg, w_param, l_param))

    @staticmethod
    def _raw_input_is_button_down(h_raw_input: int) -> bool:
        size = ctypes.c_uint(0)
        header_size = ctypes.sizeof(w32.RAWINPUTHEADER)
        w32.user32.GetRawInputData(h_raw_input, w32.RID_INPUT, None, ctypes.byref(size), header_size)
        if size.value == 0 or size.value > 4096:
            return False
        buf = ctypes.create_string_buffer(size.value)
        got = w32.user32.GetRawInputData(h_raw_input, w32.RID_INPUT, buf, ctypes.byref(size), header_size)
        if got != size.value or got < ctypes.sizeof(w32.RAWINPUT_MOUSE):
            return False
        raw = w32.RAWINPUT_MOUSE.from_buffer_copy(buf.raw[: ctypes.sizeof(w32.RAWINPUT_MOUSE)])
        if raw.header.dwType != w32.RIM_TYPEMOUSE:
            return False
        return bool(raw.mouse.usButtonFlags & w32.RI_MOUSE_ANY_BUTTON_DOWN)

    @staticmethod
    def raw_mouse_button_flags_is_down(button_flags: int) -> bool:
        """Pure helper (unit-tested anywhere): does a RAWMOUSE.usButtonFlags value contain a button-down?"""
        return bool(button_flags & w32.RI_MOUSE_ANY_BUTTON_DOWN)

    # ------------------------------------------------------- keyboard hook

    def _kb_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == HC_ACTION and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = w32.KBDLLHOOKSTRUCT.from_address(l_param)
                if not self.is_self_injected(kb.flags, kb.dwExtraInfo):
                    vk = int(kb.vkCode)
                    if vk not in _MODIFIER_VKS:
                        t0 = time.perf_counter()
                        action = self._on_key_event(self.build_key_event(vk, int(kb.scanCode)))
                        self._note_callback((time.perf_counter() - t0) * 1000.0)
                        if action == KeyAction.SUPPRESS_AND_INJECT:
                            return 1
        except Exception:
            self._log_exception("keyboard hook")
        return int(w32.user32.CallNextHookEx(self._kb_hook_id, n_code, w_param, l_param))

    def build_key_event(self, vk: int, scan_code: int) -> KeyEvent:
        user32 = w32.user32
        ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        win = bool((user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or (user32.GetAsyncKeyState(VK_RWIN) & 0x8000))

        key_name = VK_TO_KEY_NAME.get(vk, "")
        char_str = self._translate_vk(vk, scan_code, shift) if not (ctrl or alt or win) else ""
        if not key_name and char_str:
            key_name = char_str
        return KeyEvent(
            key_name=key_name,
            char=char_str,
            timestamp_ms=time.perf_counter() * 1000.0,
            ctrl_pressed=ctrl,
            alt_pressed=alt,
            meta_pressed=win,
            shift_pressed=shift,
            is_injected=False,
        )

    @staticmethod
    def _translate_vk(vk: int, scan_code: int, shift: bool) -> str:
        user32 = w32.user32
        state = (ctypes.c_ubyte * 256)()
        if shift:
            state[VK_SHIFT] = 0x80
        # Caps Lock is a *toggle* (low bit of GetKeyState); without it every
        # letter typed with Caps Lock on was seen (and re-injected) lowercase.
        if user32.GetKeyState(VK_CAPITAL) & 0x0001:
            state[VK_CAPITAL] = 0x01
        buf = ctypes.create_unicode_buffer(8)
        hwnd = user32.GetForegroundWindow()
        tid = user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
        hkl = user32.GetKeyboardLayout(tid)
        # Flag 4 (0x4) on Windows 10 1607+ prevents ToUnicodeEx from altering dead-key kernel state
        res = user32.ToUnicodeEx(vk, scan_code, state, buf, 8, 0x4, hkl)
        if res > 0:
            return buf.value[:res]
        return ""

    # ------------------------------------------------------------- health

    def _note_callback(self, elapsed_ms: float) -> None:
        st = self.stats
        st.callbacks += 1
        st.last_callback_ms = elapsed_ms
        if elapsed_ms > st.max_callback_ms:
            st.max_callback_ms = elapsed_ms
        if elapsed_ms <= self._budget_ms:
            return
        st.slow_callbacks += 1
        now = time.perf_counter()
        self._slow_times.append(now)
        self._slow_times = [t for t in self._slow_times if now - t <= SLOW_WINDOW_S]
        log.warning("hook callback took %.1f ms (budget %.0f ms)", elapsed_ms, self._budget_ms)
        if len(self._slow_times) >= self._slow_limit and not self._unhealthy_reported:
            self._unhealthy_reported = True
            reason = (
                f"{len(self._slow_times)} hook callbacks exceeded {self._budget_ms:.0f} ms within "
                f"{SLOW_WINDOW_S:.0f} s"
            )
            log.error("Win32 hook unhealthy: %s", reason)
            if self._on_unhealthy is not None:
                # Never unhook from inside the callback: let the daemon do it on its own thread.
                threading.Thread(target=self._on_unhealthy, args=(reason,), daemon=True).start()

    def _log_exception(self, where: str) -> None:
        self.stats.exceptions += 1
        now = time.monotonic()
        if now - self._last_exc_log > 5.0:  # rate-limit: one traceback per 5 s
            self._last_exc_log = now
            log.exception("exception in Win32 %s (passing event through)", where)
