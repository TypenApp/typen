"""
Non-Activating Inline Ghost Text Placeholder Overlay (Windows).

Renders predicted suffix completions ('univers' -> 'ity') or next-word suggestions
('Thank ' -> 'you') directly inside the text input area right after the caret as
muted gray placeholder text without stealing focus, mutating the target application's
DOM/buffer, or clashing with the native Windows suggestion bar.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Any, Final

from autocorrect.adapters.windows import win32_api as w32

log = logging.getLogger(__name__)

WS_POPUP: Final[int] = 0x80000000
WS_EX_LAYERED: Final[int] = 0x00080000
WS_EX_TRANSPARENT: Final[int] = 0x00000020
WS_EX_TOPMOST: Final[int] = 0x00000008
WS_EX_TOOLWINDOW: Final[int] = 0x00000080
WS_EX_NOACTIVATE: Final[int] = 0x08000000

SW_HIDE: Final[int] = 0
SW_SHOWNOACTIVATE: Final[int] = 4
HWND_TOPMOST: Final[int] = -1
SWP_NOACTIVATE: Final[int] = 0x0010
SWP_SHOWWINDOW: Final[int] = 0x0040
LWA_COLORKEY: Final[int] = 0x00000001
LWA_ALPHA: Final[int] = 0x00000002

WM_PAINT: Final[int] = 0x000F
WM_ERASEBKGND: Final[int] = 0x0014
WM_UPDATE_GHOST: Final[int] = w32.WM_APP + 42

# Transparent key color (RGB(254, 0, 254)) and muted gray placeholder ink (RGB(132, 138, 148))
COLORKEY_REF: Final[int] = 0x00FE00FE
GHOST_TEXT_COLORREF: Final[int] = 0x00948A84
TRANSPARENT_BK_MODE: Final[int] = 1


class InlineGhostOverlay:
    """
    Dedicated lightweight background thread hosting a click-through, non-activating
    Win32 popup surface that draws inline placeholder text immediately after the caret.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text: str = ""
        self._rect: tuple[int, int, int, int] | None = None
        self._dpi: int = 96
        self._visible: bool = False
        self._thread: threading.Thread | None = None
        self._hwnd: int = 0
        self._thread_id: int = 0
        self._ready = threading.Event()
        self._running = False
        self._wnd_proc_ref: Any = None

    @property
    def is_visible(self) -> bool:
        with self._lock:
            return self._visible and bool(self._text)

    @property
    def current_text(self) -> str:
        with self._lock:
            return self._text

    def start(self) -> None:
        if not w32.IS_WINDOWS or self._running:
            return
        self._running = True
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_window_loop,
            name="typen-inline-ghost-overlay",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=1.5)

    def stop(self) -> None:
        self.hide()
        if not self._running:
            return
        self._running = False
        if w32.IS_WINDOWS and self._thread_id:
            try:
                w32.user32.PostThreadMessageW(self._thread_id, w32.WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def show_at(
        self,
        text: str,
        caret_rect: tuple[int, int, int, int] | None,
        dpi: int = 96,
    ) -> None:
        """Display `text` as an inline placeholder right after `caret_rect`."""
        if not text or caret_rect is None:
            self.hide()
            return
        with self._lock:
            self._text = text
            self._rect = caret_rect
            self._dpi = max(72, dpi)
            self._visible = True
        if w32.IS_WINDOWS and self._hwnd:
            try:
                w32.user32.PostMessageW(self._hwnd, WM_UPDATE_GHOST, 1, 0)
            except Exception:
                pass

    def hide(self) -> None:
        """Immediately hide the inline placeholder."""
        with self._lock:
            was_visible = self._visible
            self._text = ""
            self._visible = False
        if w32.IS_WINDOWS and self._hwnd and was_visible:
            try:
                w32.user32.PostMessageW(self._hwnd, WM_UPDATE_GHOST, 0, 0)
            except Exception:
                pass

    def _run_window_loop(self) -> None:  # pragma: no cover - Win32 GUI thread
        try:
            import ctypes.wintypes as wt

            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            user32 = w32.user32
            kernel32 = w32.kernel32
            self._thread_id = int(kernel32.GetCurrentThreadId())
            h_inst = kernel32.GetModuleHandleW(None)
            cls_name = f"TypenInlineGhost_{self._thread_id}"

            class PAINTSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hdc", wt.HANDLE),
                    ("fErase", wt.BOOL),
                    ("rcPaint", wt.RECT),
                    ("fRestore", wt.BOOL),
                    ("fIncUpdate", wt.BOOL),
                    ("rgbReserved", ctypes.c_byte * 32),
                ]

            user32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
            user32.BeginPaint.restype = wt.HANDLE
            user32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
            user32.EndPaint.restype = wt.BOOL
            user32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
            user32.InvalidateRect.restype = wt.BOOL
            user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, ctypes.c_ubyte, wt.DWORD]
            user32.SetLayeredWindowAttributes.restype = wt.BOOL
            user32.FillRect.argtypes = [wt.HANDLE, ctypes.POINTER(wt.RECT), wt.HANDLE]
            user32.FillRect.restype = ctypes.c_int

            gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
            gdi32.CreateSolidBrush.restype = wt.HANDLE
            gdi32.DeleteObject.argtypes = [wt.HANDLE]
            gdi32.DeleteObject.restype = wt.BOOL
            gdi32.SetBkMode.argtypes = [wt.HANDLE, ctypes.c_int]
            gdi32.SetBkMode.restype = ctypes.c_int
            gdi32.SetTextColor.argtypes = [wt.HANDLE, wt.DWORD]
            gdi32.SetTextColor.restype = wt.DWORD
            gdi32.CreateFontW.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wt.DWORD,
                wt.DWORD,
                wt.DWORD,
                wt.DWORD,
                wt.DWORD,
                wt.DWORD,
                wt.DWORD,
                wt.DWORD,
                wt.LPCWSTR,
            ]
            gdi32.CreateFontW.restype = wt.HANDLE
            gdi32.SelectObject.argtypes = [wt.HANDLE, wt.HANDLE]
            gdi32.SelectObject.restype = wt.HANDLE
            gdi32.TextOutW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int]
            gdi32.TextOutW.restype = wt.BOOL

            key_brush = gdi32.CreateSolidBrush(COLORKEY_REF)

            def _wnd_proc(hwnd: int, msg: int, w_param: int, l_param: int) -> int:
                try:
                    if msg == WM_ERASEBKGND:
                        return 1
                    if msg == WM_UPDATE_GHOST:
                        if w_param == 0:
                            user32.ShowWindow(hwnd, SW_HIDE)
                            return 0
                        with self._lock:
                            text = self._text
                            rect = self._rect
                            vis = self._visible
                        if not vis or not text or rect is None:
                            user32.ShowWindow(hwnd, SW_HIDE)
                            return 0
                        cx, cy, _cw, ch = rect
                        font_h = max(14, min(36, int(ch * 0.92)))
                        width = max(48, int(len(text) * (font_h * 0.65)) + 16)
                        height = max(18, ch + 4)
                        user32.SetWindowPos(
                            hwnd,
                            HWND_TOPMOST,
                            int(cx + 1),
                            int(cy),
                            width,
                            height,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW,
                        )
                        user32.InvalidateRect(hwnd, None, True)
                        return 0
                    if msg == WM_PAINT:
                        ps = PAINTSTRUCT()
                        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                        if hdc:
                            user32.FillRect(hdc, ctypes.byref(ps.rcPaint), key_brush)
                            with self._lock:
                                text = self._text
                                rect = self._rect
                            if text and rect is not None:
                                ch = rect[3]
                                font_h = max(14, min(36, int(ch * 0.88)))
                                h_font = gdi32.CreateFontW(
                                    -font_h,
                                    0,
                                    0,
                                    0,
                                    400,
                                    0,
                                    0,
                                    0,
                                    0,
                                    0,
                                    0,
                                    4,  # ANTIALIASED_QUALITY (avoids ClearType color-key fringe)
                                    0,
                                    "Segoe UI",
                                )
                                old_font = gdi32.SelectObject(hdc, h_font) if h_font else None
                                gdi32.SetBkMode(hdc, TRANSPARENT_BK_MODE)
                                gdi32.SetTextColor(hdc, GHOST_TEXT_COLORREF)
                                gdi32.TextOutW(hdc, 1, 0, text, len(text))
                                if old_font:
                                    gdi32.SelectObject(hdc, old_font)
                                if h_font:
                                    gdi32.DeleteObject(h_font)
                            user32.EndPaint(hwnd, ctypes.byref(ps))
                        return 0
                except Exception:
                    pass
                return int(user32.DefWindowProcW(hwnd, msg, w_param, l_param))

            self._wnd_proc_ref = w32.WNDPROC(_wnd_proc)
            wc = w32.WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = self._wnd_proc_ref
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = h_inst
            wc.hIcon = None
            wc.hCursor = None
            wc.hbrBackground = key_brush
            wc.lpszMenuName = None
            wc.lpszClassName = cls_name
            user32.RegisterClassW(ctypes.byref(wc))

            ex_style = (
                WS_EX_LAYERED
                | WS_EX_TRANSPARENT
                | WS_EX_TOPMOST
                | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE
            )
            self._hwnd = int(
                user32.CreateWindowExW(
                    ex_style,
                    cls_name,
                    "",
                    WS_POPUP,
                    0,
                    0,
                    1,
                    1,
                    None,
                    None,
                    h_inst,
                    None,
                )
            )
            if self._hwnd:
                user32.SetLayeredWindowAttributes(
                    self._hwnd, COLORKEY_REF, 195, LWA_COLORKEY | LWA_ALPHA
                )
            self._ready.set()

            msg = w32.MSG()
            while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
                self._hwnd = 0
            if key_brush:
                gdi32.DeleteObject(key_brush)
            user32.UnregisterClassW(cls_name, h_inst)
        except Exception:
            log.debug("InlineGhostOverlay thread exited", exc_info=True)
            self._ready.set()


def create_inline_ghost_overlay() -> InlineGhostOverlay | None:
    if sys.platform == "win32":
        return InlineGhostOverlay()
    return None
