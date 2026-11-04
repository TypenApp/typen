"""
Windows Low-Level Keyboard (`WH_KEYBOARD_LL`) and Mouse (`WH_MOUSE_LL`) Hook Manager.
Runs on a dedicated high-priority message pump thread, filters out synthetic
events tagged with `AUTOCORRECT_EXTRA_INFO_TAG`, invalidates the word buffer
on mouse clicks, and translates virtual keys via `ToUnicodeEx`.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes  # noqa: F401 — needed so `ctypes.wintypes.MSG` resolves at runtime
import sys
import threading
import time
from collections.abc import Callable
from typing import Final

from autocorrect.adapters.windows.win32_injector import AUTOCORRECT_EXTRA_INFO_TAG
from autocorrect.adapters.windows.win_keymap import (
    VK_CONTROL,
    VK_LWIN,
    VK_MENU,
    VK_RWIN,
    VK_SHIFT,
    VK_TO_KEY_NAME,
)
from autocorrect.input.ports import KeyAction, KeyEvent

WH_KEYBOARD_LL: Final[int] = 13
WH_MOUSE_LL: Final[int] = 14
WM_KEYDOWN: Final[int] = 0x0100
WM_SYSKEYDOWN: Final[int] = 0x0104
WM_LBUTTONDOWN: Final[int] = 0x0201
WM_RBUTTONDOWN: Final[int] = 0x0204
WM_MBUTTONDOWN: Final[int] = 0x0207
WM_QUIT: Final[int] = 0x0012
HC_ACTION: Final[int] = 0
LLKHF_INJECTED: Final[int] = 0x00000010


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_ulong),
        ("scanCode", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class Win32KeyboardMouseHook:
    """
    Manages the Win32 `WH_KEYBOARD_LL` and `WH_MOUSE_LL` hooks and guarantees
    safe unhook on stop.
    """

    def __init__(
        self,
        on_key_event: Callable[[KeyEvent], KeyAction],
        on_mouse_click: Callable[[], None],
    ) -> None:
        self._on_key_event = on_key_event
        self._on_mouse_click = on_mouse_click
        self._kb_hook_id: int = 0
        self._mouse_hook_id: int = 0
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @staticmethod
    def is_self_injected(flags: int, dw_extra_info: int) -> bool:
        """Return True if the event carries our custom `AUTOCORRECT_EXTRA_INFO_TAG`."""
        return dw_extra_info == AUTOCORRECT_EXTRA_INFO_TAG or bool(flags & LLKHF_INJECTED)

    def start(self) -> None:
        """Start the dedicated Win32 hook thread if on Windows."""
        if self._running:
            return
        self._running = True
        if sys.platform == "win32":
            self._thread = threading.Thread(
                target=self._run_message_loop, name="Win32HookThread", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """Safely release keyboard and mouse hooks and terminate the message pump."""
        if not self._running:
            return
        self._running = False
        if sys.platform == "win32" and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run_message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)

        def _kb_proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == HC_ACTION and (w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)):
                kb = KBDLLHOOKSTRUCT.from_address(l_param)
                if self.is_self_injected(kb.flags, kb.dwExtraInfo):
                    return int(user32.CallNextHookEx(self._kb_hook_id, n_code, w_param, l_param))

                vk = kb.vkCode
                if vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN):
                    return int(user32.CallNextHookEx(self._kb_hook_id, n_code, w_param, l_param))

                ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                win = bool(
                    (user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or (user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
                )

                key_name = VK_TO_KEY_NAME.get(vk, "")
                char_str = self._translate_vk(vk, kb.scanCode, shift) if not (ctrl or alt or win) else ""
                if not key_name and char_str:
                    key_name = char_str

                evt = KeyEvent(
                    key_name=key_name,
                    char=char_str,
                    timestamp_ms=time.perf_counter() * 1000.0,
                    ctrl_pressed=ctrl,
                    alt_pressed=alt,
                    meta_pressed=win,
                    shift_pressed=shift,
                    is_injected=False,
                )
                action = self._on_key_event(evt)
                if action == KeyAction.SUPPRESS_AND_INJECT:
                    return 1

            return int(user32.CallNextHookEx(self._kb_hook_id, n_code, w_param, l_param))

        def _mouse_proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == HC_ACTION and w_param in (
                WM_LBUTTONDOWN,
                WM_RBUTTONDOWN,
                WM_MBUTTONDOWN,
            ):
                self._on_mouse_click()
            return int(user32.CallNextHookEx(self._mouse_hook_id, n_code, w_param, l_param))

        self._kb_cb = HOOKPROC(_kb_proc)
        self._mouse_cb = HOOKPROC(_mouse_proc)

        self._kb_hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb, None, 0)
        self._mouse_hook_id = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_cb, None, 0)

        try:
            msg = ctypes.wintypes.MSG()
            while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._kb_hook_id:
                user32.UnhookWindowsHookEx(self._kb_hook_id)
                self._kb_hook_id = 0
            if self._mouse_hook_id:
                user32.UnhookWindowsHookEx(self._mouse_hook_id)
                self._mouse_hook_id = 0

    @staticmethod
    def _translate_vk(vk: int, scan_code: int, shift: bool) -> str:
        user32 = ctypes.windll.user32
        state = (ctypes.c_ubyte * 256)()
        if shift:
            state[VK_SHIFT] = 0x80
        buf = ctypes.create_unicode_buffer(8)
        hwnd = user32.GetForegroundWindow()
        tid = user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
        hkl = user32.GetKeyboardLayout(tid)
        # Flag 4 (0x4) on Windows 10 1607+ prevents ToUnicodeEx from altering dead-key kernel state
        res = user32.ToUnicodeEx(vk, scan_code, state, buf, 8, 0x4, hkl)
        if res > 0:
            return buf.value[:res]
        return ""
