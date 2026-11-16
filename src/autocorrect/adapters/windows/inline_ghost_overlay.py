"""
Non-Activating Inline Ghost Text & Word-Pill Overlay (Windows).

Attempts **True In-Line Ghost Text** first whenever glyph-level caret geometry
is available (Win32 `GUITHREADINFO` or UIA `TextPattern2` / `TextPattern1`
selection), drawing pure frameless 32-bit per-pixel-alpha muted placeholder text
(`UpdateLayeredWindow`) directly at the blinking cursor (`cx + 1, cy`) sized to
match the active field & Windows system font size and background luminance.

When an external app does not expose exact glyph caret coordinates (`uia-elem`
fallback), for multi-word clause suggestions (`AI_REWRITE`), or when the user
selects `"pill"` in Settings, renders a clean, word-only inline pill (no `"Tab"`
label) positioned **~half an inch horizontally in front of the cursor** on the
exact same typing line—never above the focus area where the Windows IME bar sits.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
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
HWND_TOPMOST: Final[int] = -1
SWP_NOACTIVATE: Final[int] = 0x0010
SWP_SHOWWINDOW: Final[int] = 0x0040
SWP_NOMOVE: Final[int] = 0x0002
SWP_NOSIZE: Final[int] = 0x0001

AC_SRC_OVER: Final[int] = 0x00
AC_SRC_ALPHA: Final[int] = 0x01
ULW_ALPHA: Final[int] = 0x00000002
SPI_GETNONCLIENTMETRICS: Final[int] = 0x0029
WM_UPDATE_GHOST: Final[int] = w32.WM_APP + 42

# Anchor sources that represent real glyph/caret coordinates inside the text line
EXACT_CARET_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "win32",
        "uia-tp2",
        "uia-tp2-prev",
        "uia-tp2-space",
        "uia-tp1-sel",
        "uia-tp1-prev",
        "uia-tp1-space",
        "explicit",
    }
)

AnchorProbeFn = Callable[[str], tuple[tuple[int, int, int, int] | None, int, str]]

_FONT_CACHE: dict[tuple[str, int], Any] = {}
_TEXT_SCALE_CACHE: tuple[float, float] = (0.0, 1.0)  # (monotonic_ts, factor)
_SYS_FONT_PX_CACHE: dict[tuple[int, float], int] = {}


def _read_windows_text_scale_factor() -> float:
    """
    Read Windows Accessibility 'Text size' (`HKCU\\Software\\Microsoft\\Accessibility\\TextScaleFactor`),
    cached for 10s so typing never polls the registry repeatedly.
    """
    global _TEXT_SCALE_CACHE
    now = time.monotonic()
    cached_ts, cached_val = _TEXT_SCALE_CACHE
    if now - cached_ts < 10.0:
        return cached_val
    factor = 1.0
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
                val, _ = winreg.QueryValueEx(key, "TextScaleFactor")
                pct = int(val)
                if 80 <= pct <= 250:
                    factor = pct / 100.0
        except Exception:
            factor = 1.0
    _TEXT_SCALE_CACHE = (now, factor)
    return factor


def get_system_text_font_px(dpi: int = 96) -> int:
    """
    Determine the active Windows system message/body font pixel size at `dpi`,
    incorporating both monitor DPI scaling and Windows Accessibility `TextScaleFactor`.
    """
    safe_dpi = max(72, min(384, int(dpi)))
    text_scale = round(_read_windows_text_scale_factor(), 2)
    cache_key = (safe_dpi, text_scale)
    cached = _SYS_FONT_PX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    dpi_scale = safe_dpi / 96.0
    base_px = int(round(14.5 * dpi_scale * text_scale))

    if w32.IS_WINDOWS and w32.user32 is not None:
        try:
            import ctypes.wintypes as wt

            class LOGFONTW(ctypes.Structure):
                _fields_ = [
                    ("lfHeight", wt.LONG),
                    ("lfWidth", wt.LONG),
                    ("lfEscapement", wt.LONG),
                    ("lfOrientation", wt.LONG),
                    ("lfWeight", wt.LONG),
                    ("lfItalic", wt.BYTE),
                    ("lfUnderline", wt.BYTE),
                    ("lfStrikeOut", wt.BYTE),
                    ("lfCharSet", wt.BYTE),
                    ("lfOutPrecision", wt.BYTE),
                    ("lfClipPrecision", wt.BYTE),
                    ("lfQuality", wt.BYTE),
                    ("lfPitchAndFamily", wt.BYTE),
                    ("lfFaceName", wt.WCHAR * 32),
                ]

            class NONCLIENTMETRICSW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.UINT),
                    ("iBorderWidth", ctypes.c_int),
                    ("iScrollWidth", ctypes.c_int),
                    ("iScrollHeight", ctypes.c_int),
                    ("iCaptionWidth", ctypes.c_int),
                    ("iCaptionHeight", ctypes.c_int),
                    ("lfCaptionFont", LOGFONTW),
                    ("iSmCaptionWidth", ctypes.c_int),
                    ("iSmCaptionHeight", ctypes.c_int),
                    ("lfSmCaptionFont", LOGFONTW),
                    ("iMenuWidth", ctypes.c_int),
                    ("iMenuHeight", ctypes.c_int),
                    ("lfMenuFont", LOGFONTW),
                    ("lfStatusFont", LOGFONTW),
                    ("lfMessageFont", LOGFONTW),
                    ("iPaddedBorderWidth", ctypes.c_int),
                ]

            ncm = NONCLIENTMETRICSW()
            ncm.cbSize = ctypes.sizeof(NONCLIENTMETRICSW)
            if w32.user32.SystemParametersInfoW(
                SPI_GETNONCLIENTMETRICS, ncm.cbSize, ctypes.byref(ncm), 0
            ):
                lf_h = abs(int(ncm.lfMessageFont.lfHeight))
                if 8 <= lf_h <= 64:
                    # SystemParametersInfoW returns primary-monitor metrics; adjust to target window DPI
                    primary_dpi = 96
                    try:
                        d_sys = int(w32.user32.GetDpiForSystem())
                        if d_sys > 0:
                            primary_dpi = d_sys
                    except Exception:
                        pass
                    sys_px = int(round(lf_h * (safe_dpi / primary_dpi) * text_scale))
                    # Typical modern editors/apps render prose slightly above Win32 9pt dialog chrome
                    base_px = max(base_px, sys_px)
        except Exception:
            pass

    resolved = max(12, min(42, base_px))
    _SYS_FONT_PX_CACHE[cache_key] = resolved
    return resolved


def resolve_overlay_font_px(
    caret_h: int = 0,
    dpi: int = 96,
    *,
    exact_caret: bool = True,
    font_scale: float = 1.0,
) -> int:
    """
    Compute the target font pixel size that blends naturally with the focused field
    and the Windows system font size.
    """
    sys_px = get_system_text_font_px(dpi)
    if exact_caret and 12 <= caret_h <= 56:
        # Caret height is ~1.28x-1.34x font em-height; anchor smoothly to system font bounds
        from_caret = int(round(caret_h * 0.76))
        blended = max(int(round(sys_px * 0.84)), min(int(round(sys_px * 1.32)), from_caret))
    else:
        blended = sys_px
    clamped_scale = max(0.8, min(1.4, float(font_scale)))
    return max(11, min(48, int(round(blended * clamped_scale))))


def _load_ui_font(size_px: int, *, semibold: bool = False) -> Any:
    from PIL import ImageFont

    key = ("sb" if semibold else "reg", size_px)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    win_dir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = (
        ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf")
        if semibold
        else ("segoeui.ttf", "arial.ttf")
    )
    font: Any = None
    for name in candidates:
        fp = os.path.join(win_dir, "Fonts", name)
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, size_px)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _sample_field_is_dark(cx: int, cy: int, ch: int) -> bool:
    """
    Sample 2 background pixels immediately left of the cursor (`cx - 3`, outside our
    overlay surface) near the top and bottom of the caret line box to detect whether
    the target text box is dark-themed or light-themed.
    """
    if not w32.IS_WINDOWS or w32.user32 is None:
        return False
    try:
        gdi32 = ctypes.WinDLL("gdi32")
        hdc = w32.user32.GetDC(None)
        if not hdc:
            return False
        try:
            sx = max(1, int(cx - 3))
            sy_top = max(1, int(cy + 1))
            sy_bot = max(1, int(cy + max(2, ch - 2)))
            c1 = int(gdi32.GetPixel(hdc, sx, sy_top))
            c2 = int(gdi32.GetPixel(hdc, sx, sy_bot))
        finally:
            w32.user32.ReleaseDC(None, hdc)

        lums: list[float] = []
        for cref in (c1, c2):
            if cref >= 0 and cref != 0xFFFFFFFF:
                r = cref & 0xFF
                g = (cref >> 8) & 0xFF
                b = (cref >> 16) & 0xFF
                lums.append(0.299 * r + 0.587 * g + 0.114 * b)
        if not lums:
            return False
        return (sum(lums) / len(lums)) < 132.0
    except Exception:
        return False


def render_inline_ghost_bgra(
    completion_text: str,
    caret_h: int = 20,
    dpi: int = 96,
    *,
    is_dark_bg: bool = False,
    font_scale: float = 1.0,
) -> tuple[bytes, int, int]:
    """
    Render **True In-Line Ghost Text**: pure frameless, borderless, backgroundless
    32-bit premultiplied BGRA muted placeholder text right at the cursor, matching
    the "Try it" experience inside the Typen app with zero color-key fringes.
    """
    from PIL import Image, ImageDraw

    ss = 2
    font_px = resolve_overlay_font_px(caret_h, dpi, exact_caret=True, font_scale=font_scale)
    font = _load_ui_font(font_px * ss, semibold=False)

    dummy = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    text_w_ss = int(round(dd.textlength(completion_text, font=font)))

    line_h = max(caret_h, font_px + 4)
    canvas_w_ss = max(16 * ss, text_w_ss + 6 * ss)
    canvas_h_ss = max(14 * ss, line_h * ss)

    im = Image.new("RGBA", (canvas_w_ss, canvas_h_ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # Adaptive muted placeholder ink (mirrors Theme.inkFaint in light & dark mode)
    ink_rgba = (150, 158, 172, 194) if is_dark_bg else (122, 128, 140, 200)
    draw.text(
        (ss, canvas_h_ss // 2),
        completion_text,
        font=font,
        fill=ink_rgba,
        anchor="lm",
    )

    out_w = max(8, canvas_w_ss // ss)
    out_h = max(14, canvas_h_ss // ss)
    final_im = im.resize((out_w, out_h), Image.Resampling.BILINEAR)
    bgra = final_im.convert("RGBa").tobytes("raw", "BGRa")
    return bgra, out_w, out_h


def render_pill_bgra(
    prefix_text: str,
    completion_text: str,
    accept_key: str = "both",
    dpi: int = 96,
    *,
    ai_tag: bool = False,
    is_dark_bg: bool = True,
    caret_h: int = 0,
    exact_caret: bool = False,
    font_scale: float = 1.0,
) -> tuple[bytes, int, int]:
    """
    Render a clean, minimal **Word-Only Inline Pill** (no `"Tab"` label, no dot)
    sized to the Windows system / field font size so it blends naturally on the
    typing line ~half an inch ahead of the cursor.
    """
    from PIL import Image, ImageDraw

    _ = (accept_key, ai_tag)  # Kept for signature compatibility; pill is strictly word-only
    scale = max(1.0, min(2.5, dpi / 96.0))
    ss = 2
    font_px = resolve_overlay_font_px(
        caret_h, dpi, exact_caret=exact_caret, font_scale=font_scale
    )
    font_word = _load_ui_font(font_px * ss, semibold=False)

    dummy = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    pref_w = int(round(dd.textlength(prefix_text, font=font_word))) if prefix_text else 0
    comp_w = int(round(dd.textlength(completion_text, font=font_word)))

    pad_x = int(round(8.5 * scale * ss))
    pad_y = int(round(3.5 * scale * ss))
    pill_h_ss = max(int(round(20 * scale * ss)), font_px * ss + pad_y * 2)
    pill_w_ss = max(int(round(28 * scale * ss)), pad_x * 2 + pref_w + comp_w)
    margin = int(round(1.5 * scale * ss))
    canvas_w_ss = pill_w_ss + margin * 2
    canvas_h_ss = pill_h_ss + margin * 2

    im = Image.new("RGBA", (canvas_w_ss, canvas_h_ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    rx0, ry0 = margin, margin
    rx1, ry1 = rx0 + pill_w_ss - 1, ry0 + pill_h_ss - 1
    radius = pill_h_ss // 2

    if is_dark_bg:
        bg_fill = (32, 34, 40, 228)
        rim_stroke = (255, 255, 255, 36)
        pref_ink = (140, 147, 160, 210)
        comp_ink = (218, 223, 232, 245)
        shadow_fill = (0, 0, 0, 48)
    else:
        bg_fill = (244, 245, 248, 234)
        rim_stroke = (15, 23, 42, 34)
        pref_ink = (142, 148, 160, 210)
        comp_ink = (68, 74, 86, 242)
        shadow_fill = (15, 23, 42, 22)

    sh_off = max(1, int(round(1.0 * scale * ss)))
    draw.rounded_rectangle(
        (rx0, ry0 + sh_off, rx1, ry1 + sh_off),
        radius=radius,
        fill=shadow_fill,
    )
    draw.rounded_rectangle(
        (rx0, ry0, rx1, ry1),
        radius=radius,
        fill=bg_fill,
        outline=rim_stroke,
        width=max(1, ss),
    )

    text_x = rx0 + pad_x
    cy_mid = ry0 + pill_h_ss // 2
    if prefix_text:
        draw.text(
            (text_x, cy_mid),
            prefix_text,
            font=font_word,
            fill=pref_ink,
            anchor="lm",
        )
        text_x += pref_w
    draw.text(
        (text_x, cy_mid),
        completion_text,
        font=font_word,
        fill=comp_ink,
        anchor="lm",
    )

    out_w = max(18, canvas_w_ss // ss)
    out_h = max(16, canvas_h_ss // ss)
    final_im = im.resize((out_w, out_h), Image.Resampling.BILINEAR)
    bgra = final_im.convert("RGBa").tobytes("raw", "BGRa")
    return bgra, out_w, out_h


class InlineGhostOverlay:
    """
    Non-activating, click-through Win32 layered overlay surface with asynchronous
    background UIA/Win32 anchor resolution so the input worker never stalls.
    """

    def __init__(self, anchor_probe: AnchorProbeFn | None = None) -> None:
        self._lock = threading.Lock()
        self._anchor_probe: AnchorProbeFn | None = anchor_probe
        self._seq: int = 0
        self._req_prefix: str = ""
        self._req_text: str = ""
        self._req_accept_key: str = "both"
        self._req_display_style: str = "inline"
        self._req_font_scale: float = 1.0
        self._req_ai_tag: bool = False
        self._req_explicit_rect: tuple[int, int, int, int] | None = None
        self._req_dpi: int = 96
        self._want_visible: bool = False

        # Prepared frame ready for UpdateLayeredWindow on the GUI thread
        self._frame_bgra: bytes = b""
        self._frame_pos: tuple[int, int] = (0, 0)
        self._frame_size: tuple[int, int] = (0, 0)
        self._visible: bool = False
        self._text: str = ""

        self._wake_worker = threading.Event()
        self._gui_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._hwnd: int = 0
        self._gui_thread_id: int = 0
        self._ready = threading.Event()
        self._running = False
        self._wnd_proc_ref: Any = None

    def set_anchor_probe(self, probe: AnchorProbeFn | None) -> None:
        self._anchor_probe = probe

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
        self._gui_thread = threading.Thread(
            target=self._run_window_loop,
            name="typen-inline-ghost-gui",
            daemon=True,
        )
        self._gui_thread.start()
        self._ready.wait(timeout=1.5)
        self._worker_thread = threading.Thread(
            target=self._run_anchor_worker,
            name="typen-inline-ghost-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self.hide()
        if not self._running:
            return
        self._running = False
        self._wake_worker.set()
        if w32.IS_WINDOWS and self._gui_thread_id:
            try:
                w32.user32.PostThreadMessageW(self._gui_thread_id, w32.WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.8)
        if self._gui_thread is not None and self._gui_thread.is_alive():
            self._gui_thread.join(timeout=1.0)
        self._worker_thread = None
        self._gui_thread = None

    def request_prediction(
        self,
        prefix_text: str,
        completion_text: str,
        *,
        accept_key: str = "both",
        display_style: str = "inline",
        font_scale: float = 1.0,
        ai_tag: bool = False,
    ) -> None:
        """
        Non-blocking (< 0.02ms) request from the input dispatcher thread.
        Anchor lookup and RGBA inline ghost / word-pill rasterisation happen off-thread.
        """
        if not completion_text:
            self.hide()
            return
        with self._lock:
            self._seq += 1
            self._req_prefix = prefix_text
            self._req_text = completion_text
            self._req_accept_key = accept_key
            self._req_display_style = display_style
            self._req_font_scale = font_scale
            self._req_ai_tag = ai_tag
            self._req_explicit_rect = None
            self._want_visible = True
            self._text = completion_text
        self._wake_worker.set()

    def show_at(
        self,
        text: str,
        caret_rect: tuple[int, int, int, int] | None,
        dpi: int = 96,
        *,
        prefix_text: str = "",
        accept_key: str = "both",
        display_style: str = "inline",
        font_scale: float = 1.0,
        ai_tag: bool = False,
    ) -> None:
        """Display `text` anchored at an explicit `caret_rect`."""
        if not text or caret_rect is None:
            self.hide()
            return
        with self._lock:
            self._seq += 1
            self._req_prefix = prefix_text
            self._req_text = text
            self._req_accept_key = accept_key
            self._req_display_style = display_style
            self._req_font_scale = font_scale
            self._req_ai_tag = ai_tag
            self._req_explicit_rect = caret_rect
            self._req_dpi = max(72, dpi)
            self._want_visible = True
            self._text = text
        self._wake_worker.set()

    def hide(self) -> None:
        """Immediately hide the inline ghost text / word pill."""
        with self._lock:
            self._seq += 1
            was_visible = self._visible or self._want_visible
            self._want_visible = False
            self._visible = False
            self._text = ""
            self._frame_bgra = b""
        if w32.IS_WINDOWS and self._hwnd and was_visible:
            try:
                w32.user32.PostMessageW(self._hwnd, WM_UPDATE_GHOST, 0, 0)
            except Exception:
                pass

    def _run_anchor_worker(self) -> None:  # pragma: no cover - background worker
        handled_seq = -1
        while self._running:
            self._wake_worker.wait(timeout=0.5)
            self._wake_worker.clear()
            if not self._running:
                break
            while self._running:
                with self._lock:
                    seq = self._seq
                    want = self._want_visible
                    prefix = self._req_prefix
                    comp = self._req_text
                    accept_key = self._req_accept_key
                    display_style = self._req_display_style
                    font_scale = self._req_font_scale
                    ai_tag = self._req_ai_tag
                    explicit_rect = self._req_explicit_rect
                    dpi = self._req_dpi
                if seq == handled_seq:
                    break
                handled_seq = seq
                if not want or not comp:
                    break

                rect = explicit_rect
                src = "explicit"
                if rect is None and self._anchor_probe is not None:
                    try:
                        rect, dpi, src = self._anchor_probe(prefix)
                    except Exception:
                        rect = None

                # Drop stale frame if user already typed another key while UIA was probing
                with self._lock:
                    if self._seq != seq or not self._want_visible:
                        continue

                if rect is None:
                    with self._lock:
                        if self._seq == seq:
                            self._visible = False
                    if self._hwnd:
                        try:
                            w32.user32.PostMessageW(self._hwnd, WM_UPDATE_GHOST, 0, 0)
                        except Exception:
                            pass
                    continue

                cx, cy, _cw, ch = rect
                exact_caret = src in EXACT_CARET_SOURCES
                is_dark = _sample_field_is_dark(cx, cy, ch)
                use_true_inline = display_style != "pill" and exact_caret and not ai_tag

                try:
                    if use_true_inline:
                        bgra, pw, ph = render_inline_ghost_bgra(
                            comp,
                            caret_h=ch,
                            dpi=dpi,
                            is_dark_bg=is_dark,
                            font_scale=font_scale,
                        )
                        px = int(cx + 1)
                        py = int(cy + (ch - ph) // 2)
                    else:
                        bgra, pw, ph = render_pill_bgra(
                            prefix,
                            comp,
                            accept_key=accept_key,
                            dpi=dpi,
                            ai_tag=ai_tag,
                            is_dark_bg=is_dark,
                            caret_h=ch,
                            exact_caret=exact_caret,
                            font_scale=font_scale,
                        )
                        # Position ~half an inch (0.5 * dpi px) horizontally in front of the
                        # cursor on the exact same typing line — never above the focus area!
                        half_inch_px = int(round(0.5 * max(72, dpi)))
                        px = int(cx + half_inch_px)
                        py = int(cy + (max(16, ch) - ph) // 2)
                except Exception:
                    continue

                # Clamp cleanly within virtual screen bounds
                try:
                    sm_x = int(w32.user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
                    sm_y = int(w32.user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
                    sm_w = int(w32.user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
                    sm_h = int(w32.user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
                    if sm_w > 0:
                        px = max(sm_x + 4, min(px, sm_x + sm_w - pw - 6))
                    if sm_h > 0:
                        py = max(sm_y + 4, min(py, sm_y + sm_h - ph - 4))
                except Exception:
                    pass

                pushed = False
                with self._lock:
                    if self._seq == seq and self._want_visible:
                        self._frame_bgra = bgra
                        self._frame_pos = (px, py)
                        self._frame_size = (pw, ph)
                        self._visible = True
                        pushed = True
                if pushed and self._hwnd:
                    try:
                        w32.user32.PostMessageW(self._hwnd, WM_UPDATE_GHOST, 1, 0)
                    except Exception:
                        pass

    def _run_window_loop(self) -> None:  # pragma: no cover - Win32 GUI thread
        try:
            import ctypes.wintypes as wt

            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            user32 = w32.user32
            kernel32 = w32.kernel32
            self._gui_thread_id = int(kernel32.GetCurrentThreadId())
            h_inst = kernel32.GetModuleHandleW(None)
            cls_name = f"TypenInlinePill_{self._gui_thread_id}"

            class SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            class BLENDFUNCTION(ctypes.Structure):
                _fields_ = [
                    ("BlendOp", ctypes.c_ubyte),
                    ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte),
                    ("AlphaFormat", ctypes.c_ubyte),
                ]

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wt.DWORD),
                    ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long),
                    ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD),
                ]

            gdi32.CreateCompatibleDC.argtypes = [wt.HANDLE]
            gdi32.CreateCompatibleDC.restype = wt.HANDLE
            gdi32.DeleteDC.argtypes = [wt.HANDLE]
            gdi32.DeleteDC.restype = wt.BOOL
            gdi32.CreateDIBSection.argtypes = [
                wt.HANDLE,
                ctypes.POINTER(BITMAPINFOHEADER),
                wt.UINT,
                ctypes.POINTER(ctypes.c_void_p),
                wt.HANDLE,
                wt.DWORD,
            ]
            gdi32.CreateDIBSection.restype = wt.HANDLE
            gdi32.SelectObject.argtypes = [wt.HANDLE, wt.HANDLE]
            gdi32.SelectObject.restype = wt.HANDLE
            gdi32.DeleteObject.argtypes = [wt.HANDLE]
            gdi32.DeleteObject.restype = wt.BOOL

            user32.GetDC.argtypes = [wt.HWND]
            user32.GetDC.restype = wt.HANDLE
            user32.ReleaseDC.argtypes = [wt.HWND, wt.HANDLE]
            user32.ReleaseDC.restype = ctypes.c_int
            user32.UpdateLayeredWindow.argtypes = [
                wt.HWND,
                wt.HANDLE,
                ctypes.POINTER(wt.POINT),
                ctypes.POINTER(SIZE),
                wt.HANDLE,
                ctypes.POINTER(wt.POINT),
                wt.DWORD,
                ctypes.POINTER(BLENDFUNCTION),
                wt.DWORD,
            ]
            user32.UpdateLayeredWindow.restype = wt.BOOL

            def _apply_layered_frame(hwnd: int) -> None:
                with self._lock:
                    vis = self._visible
                    bgra = self._frame_bgra
                    px, py = self._frame_pos
                    pw, ph = self._frame_size
                if not vis or not bgra or pw <= 0 or ph <= 0:
                    user32.ShowWindow(hwnd, SW_HIDE)
                    return

                screen_dc = user32.GetDC(None)
                mem_dc = gdi32.CreateCompatibleDC(screen_dc)
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = pw
                bmi.biHeight = -ph  # Top-down DIB
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0
                bmi.biSizeImage = pw * ph * 4

                bits = ctypes.c_void_p()
                h_bmp = gdi32.CreateDIBSection(
                    mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
                )
                if h_bmp and bits.value:
                    ctypes.memmove(bits.value, bgra, pw * ph * 4)
                    old_bmp = gdi32.SelectObject(mem_dc, h_bmp)
                    pt_dst = wt.POINT(px, py)
                    pt_src = wt.POINT(0, 0)
                    sz = SIZE(pw, ph)
                    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
                    user32.UpdateLayeredWindow(
                        hwnd,
                        screen_dc,
                        ctypes.byref(pt_dst),
                        ctypes.byref(sz),
                        mem_dc,
                        ctypes.byref(pt_src),
                        0,
                        ctypes.byref(blend),
                        ULW_ALPHA,
                    )
                    user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        px,
                        py,
                        pw,
                        ph,
                        SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOMOVE | SWP_NOSIZE,
                    )
                    if old_bmp:
                        gdi32.SelectObject(mem_dc, old_bmp)
                if h_bmp:
                    gdi32.DeleteObject(h_bmp)
                if mem_dc:
                    gdi32.DeleteDC(mem_dc)
                if screen_dc:
                    user32.ReleaseDC(None, screen_dc)

            def _wnd_proc(hwnd: int, msg: int, w_param: int, l_param: int) -> int:
                try:
                    if msg == WM_UPDATE_GHOST:
                        if w_param == 0:
                            user32.ShowWindow(hwnd, SW_HIDE)
                        else:
                            _apply_layered_frame(hwnd)
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
            wc.hbrBackground = None
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
            self._ready.set()

            msg = w32.MSG()
            while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
                self._hwnd = 0
            user32.UnregisterClassW(cls_name, h_inst)
        except Exception:
            log.debug("InlineGhostOverlay thread exited", exc_info=True)
            self._ready.set()


def create_inline_ghost_overlay() -> InlineGhostOverlay | None:
    if sys.platform == "win32":
        return InlineGhostOverlay()
    return None
