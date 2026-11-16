"""
Windows caret-context probe.

When the user clicks or tabs into a text field, the typing session has no idea
what already sits before the caret: is this the start of an empty field (so the
first word must be capitalised), the middle of a sentence, or right after a
full stop? Guessing wrong is what made capitalisation "almost never work" at
the start of a typing sequence.

This module asks UI Automation for the text immediately before the caret:

1. `IUIAutomation.GetFocusedElement()` -> `TextPattern2.GetCaretRange()`
   (Windows 8+; works in Chromium/Electron apps, Word, WordPad, UWP, modern
   Notepad) -> move the range start back N characters -> `GetText`.
2. Fallback for classic `EDIT` / `RichEdit` controls without a usable
   TextPattern: `EM_GETSEL` + `WM_GETTEXT`.
3. If neither works the probe returns None and the caller keeps the
   conservative behaviour it had before.

`comtypes` is an optional dependency: without it (or off Windows) the probe is
simply unavailable. Every call is wrapped so a misbehaving accessibility
provider can never take the daemon down, and the whole probe is time-budgeted
because UIA calls into the target process.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Any, Final

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_CHARS: Final[int] = 256
PROBE_BUDGET_S: Final[float] = 0.25

UIA_TextPattern2Id: Final[int] = 10024
UIA_TextPatternId: Final[int] = 10014
UIA_ValuePatternId: Final[int] = 10002
UIA_LegacyIAccessiblePatternId: Final[int] = 10018
UIA_ControlTypePropertyId: Final[int] = 30003
UIA_IsPasswordPropertyId: Final[int] = 30019
UIA_EditControlTypeId: Final[int] = 50004
UIA_DocumentControlTypeId: Final[int] = 50030
ROLE_SYSTEM_TEXT: Final[int] = 0x2A
STATE_SYSTEM_PROTECTED: Final[int] = 0x20000000
TextUnit_Character: Final[int] = 0
TextPatternRangeEndpoint_Start: Final[int] = 0
TextPatternRangeEndpoint_End: Final[int] = 1

EM_GETSEL: Final[int] = 0x00B0
EM_POSFROMCHAR: Final[int] = 0x00D6
WM_GETTEXT: Final[int] = 0x000D
WM_GETTEXTLENGTH: Final[int] = 0x000E
SMTO_ABORTIFHUNG: Final[int] = 0x0002


class CaretContext:
    """Text before the caret, plus what we know about the field and caret screen geometry."""

    __slots__ = ("text_before", "is_empty_field", "is_password", "source", "caret_rect", "dpi")

    def __init__(
        self,
        text_before: str,
        *,
        is_empty_field: bool,
        is_password: bool = False,
        source: str = "",
        caret_rect: tuple[int, int, int, int] | None = None,
        dpi: int = 96,
    ):
        self.text_before = text_before
        self.is_empty_field = is_empty_field
        self.is_password = is_password
        self.source = source
        self.caret_rect = caret_rect
        self.dpi = dpi

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"CaretContext({self.text_before!r}, empty={self.is_empty_field}, "
            f"src={self.source}, rect={self.caret_rect})"
        )


class WindowsCaretProbe:
    """
    Best-effort "what is before the caret?" for the focused control.

    Thread-safety: COM is initialised per calling thread (MTA); the probe is
    designed to be called from the input dispatcher worker only.
    """

    def __init__(self, context_chars: int = DEFAULT_CONTEXT_CHARS) -> None:
        self._n = max(8, context_chars)
        self._uia: Any = None
        self._uia_mod: Any = None
        self._uia_failed = False
        self._tls = threading.local()
        self._com_threads: set[int] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- public

    @property
    def is_available(self) -> bool:
        return sys.platform == "win32"

    def read(self) -> CaretContext | None:
        """Return the caret context for the focused control, or None if unknown."""
        if sys.platform != "win32":
            return None
        started = time.perf_counter()
        try:
            ctx = self._read_uia()
            if ctx is not None:
                return ctx
        except Exception:
            self._note_uia_failure()
        if time.perf_counter() - started > PROBE_BUDGET_S:
            return None
        try:
            return self._read_classic_edit()
        except Exception:
            return None

    # --------------------------------------------------------------- UIA

    def _ensure_uia(self) -> Any:
        if self._uia_failed:
            return None
        tls_uia = getattr(self._tls, "uia", None)
        if tls_uia is not None:
            return tls_uia
        with self._lock:
            if self._uia_failed:
                return None
            try:
                import comtypes  # type: ignore[import-not-found]
                import comtypes.client  # type: ignore[import-not-found]

                self._init_com(comtypes)
                if self._uia_mod is None:
                    comtypes.client.GetModule("UIAutomationCore.dll")
                    from comtypes.gen import UIAutomationClient as uia  # type: ignore[import-not-found]

                    self._uia_mod = uia
                    log.info("UI Automation caret probe ready")
                inst = comtypes.client.CreateObject(
                    self._uia_mod.CUIAutomation, interface=self._uia_mod.IUIAutomation
                )
                self._tls.uia = inst
                if self._uia is None:
                    self._uia = inst
                return inst
            except Exception as exc:
                self._uia_failed = True
                log.info("UI Automation caret probe unavailable: %r", exc)
                return None

    def _init_com(self, comtypes_mod: Any) -> None:
        tid = threading.get_ident()
        if tid in self._com_threads:
            return
        try:
            comtypes_mod.CoInitializeEx(comtypes_mod.COINIT_MULTITHREADED)
        except Exception:
            pass
        self._com_threads.add(tid)

    def read_geometry_fast(self) -> tuple[tuple[int, int, int, int] | None, int]:
        """
        Sub-millisecond Win32 GUIThreadInfo caret screen rectangle + DPI lookup.
        Falls back to UIA bounding rectangles with a strict 15ms budget.
        """
        if sys.platform != "win32":
            return None, 96
        rect, dpi = self._read_win32_caret_rect()
        if rect is not None:
            return rect, dpi
        t0 = time.perf_counter()
        try:
            ctx = self._read_uia_geometry_only(dpi)
            if ctx is not None and (time.perf_counter() - t0) <= 0.015:
                return ctx, dpi
        except Exception:
            pass
        return None, dpi

    def read_overlay_anchor(
        self, typed_prefix: str = ""
    ) -> tuple[tuple[int, int, int, int] | None, int, str]:
        """
        Resolve `(anchor_rect, dpi, source)` for the floating predictive pill.
        Must ONLY be called from the background overlay worker thread (never on
        the input dispatcher hot path). Checks Win32 caret -> UIA TextPattern2 ->
        UIA TextPattern1 selection -> UIA ValuePattern / Focused Element bounds.
        """
        if sys.platform != "win32":
            return None, 96, "none"
        rect, dpi = self._read_win32_caret_rect()
        if rect is not None:
            return rect, dpi, "win32"

        src = "none"
        uia_rect: tuple[int, int, int, int] | None = None
        try:
            uia_rect, src = self._read_uia_anchor_with_fallbacks(typed_prefix, dpi)
        except Exception:
            uia_rect, src = None, "exc"
        return uia_rect, dpi, src

    def _read_uia_anchor_with_fallbacks(
        self, typed_prefix: str, dpi: int = 96
    ) -> tuple[tuple[int, int, int, int] | None, str]:
        uia = self._ensure_uia()
        if uia is None:
            return None, "no-uia"
        import comtypes  # type: ignore[import-not-found]

        self._init_com(comtypes)
        element = uia.GetFocusedElement()
        if element is None:
            return None, "no-elem"
        mod = self._uia_mod

        # 1. TextPattern2 caret range
        space_adv = int(round(4.5 * max(1.0, dpi / 96.0)))
        try:
            pat2 = element.GetCurrentPattern(UIA_TextPattern2Id)
            if pat2 is not None:
                text2 = pat2.QueryInterface(mod.IUIAutomationTextPattern2)
                is_active = ctypes.c_int(0)
                caret = text2.GetCaretRange(ctypes.byref(is_active))
                if caret is not None:
                    r = self._extract_uia_range_rect(caret)
                    if r is not None:
                        return r, "uia-tp2"
                    caret.MoveEndpointByUnit(
                        TextPatternRangeEndpoint_Start, TextUnit_Character, -1
                    )
                    r = self._extract_uia_range_rect(caret)
                    if r is not None:
                        return r, "uia-tp2-prev"
                    caret.MoveEndpointByUnit(
                        TextPatternRangeEndpoint_Start, TextUnit_Character, -1
                    )
                    r2 = self._extract_uia_range_rect(caret)
                    if r2 is not None:
                        return (r2[0] + space_adv, r2[1], r2[2], r2[3]), "uia-tp2-space"
        except Exception:
            pass

        # 2. TextPattern1 selection range (Chromium, Electron, Cursor, VS Code)
        try:
            pat1 = element.GetCurrentPattern(UIA_TextPatternId)
            if pat1 is not None:
                tp = pat1.QueryInterface(mod.IUIAutomationTextPattern)
                sel = tp.GetSelection()
                if sel is not None and int(sel.Length) > 0:
                    rng = sel.GetElement(0)
                    if rng is not None:
                        r = self._extract_uia_range_rect(rng)
                        if r is not None:
                            return r, "uia-tp1-sel"
                        rng_clone = rng.Clone()
                        rng_clone.MoveEndpointByUnit(
                            TextPatternRangeEndpoint_Start, TextUnit_Character, -1
                        )
                        r = self._extract_uia_range_rect(rng_clone)
                        if r is not None:
                            return r, "uia-tp1-prev"
                        rng_clone.MoveEndpointByUnit(
                            TextPatternRangeEndpoint_Start, TextUnit_Character, -1
                        )
                        r2 = self._extract_uia_range_rect(rng_clone)
                        if r2 is not None:
                            return (r2[0] + space_adv, r2[1], r2[2], r2[3]), "uia-tp1-space"
        except Exception:
            pass

        # 3. ValuePattern / LegacyIAccessiblePattern or Focused Element bounding rectangle
        try:
            val_text = typed_prefix
            val_pat = element.GetCurrentPattern(UIA_ValuePatternId)
            if val_pat is not None:
                vp = val_pat.QueryInterface(mod.IUIAutomationValuePattern)
                raw_v = str(vp.CurrentValue or "").replace("\r\n", "\n")
                if raw_v:
                    val_text = raw_v[-120:]
            else:
                leg_pat = element.GetCurrentPattern(UIA_LegacyIAccessiblePatternId)
                if leg_pat is not None:
                    leg = leg_pat.QueryInterface(mod.IUIAutomationLegacyIAccessiblePattern)
                    raw_l = str(leg.CurrentValue or "").replace("\r\n", "\n")
                    if raw_l:
                        val_text = raw_l[-120:]
            est = self._estimate_element_caret_rect(element, val_text, dpi, allow_tall_composer=True)
            if est is not None:
                return est, "uia-elem"
        except Exception:
            pass
        return None, "uia-miss"

    def _read_uia_geometry_only(self, dpi: int = 96) -> tuple[int, int, int, int] | None:
        rect, _src = self._read_uia_anchor_with_fallbacks("", dpi)
        return rect

    @staticmethod
    def _read_win32_caret_rect() -> tuple[tuple[int, int, int, int] | None, int]:
        from autocorrect.adapters.windows import win32_api as w32

        user32 = w32.user32
        if user32 is None:
            return None, 96
        import ctypes.wintypes as wt

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, 96
        dpi = 96
        try:
            d = int(user32.GetDpiForWindow(hwnd))
            if d > 0:
                dpi = d
        except Exception:
            pass
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        gti = w32.GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(w32.GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
            return None, dpi
        target_hwnd = gti.hwndCaret or gti.hwndFocus
        rc = gti.rcCaret
        if target_hwnd and (rc.right > rc.left or rc.bottom > rc.top):
            pt = wt.POINT(rc.right, rc.top)
            if user32.ClientToScreen(target_hwnd, ctypes.byref(pt)):
                w = max(1, int(rc.right - rc.left))
                h = max(14, int(rc.bottom - rc.top))
                return (int(pt.x), int(pt.y), w, h), dpi
        return None, dpi

    def _note_uia_failure(self) -> None:
        # Individual providers fail all the time (closed windows, hung apps);
        # only give up on UIA entirely if the factory itself is broken.
        if self._uia is None:
            self._uia_failed = True

    def _read_uia(self) -> CaretContext | None:
        uia = self._ensure_uia()
        if uia is None:
            return None
        import comtypes  # type: ignore[import-not-found]

        self._init_com(comtypes)
        element = uia.GetFocusedElement()
        if element is None:
            return None
        try:
            if bool(element.GetCurrentPropertyValue(UIA_IsPasswordPropertyId)):
                return CaretContext("", is_empty_field=False, is_password=True, source="uia")
        except Exception:
            pass

        mod = self._uia_mod
        win_rect, dpi = self._read_win32_caret_rect()
        pattern = element.GetCurrentPattern(UIA_TextPattern2Id)
        if pattern is not None:
            try:
                text2 = pattern.QueryInterface(mod.IUIAutomationTextPattern2)
                is_active = ctypes.c_int(0)
                caret = text2.GetCaretRange(ctypes.byref(is_active))
                if caret is not None:
                    caret_rect = win_rect
                    if caret_rect is None:
                        caret_rect = self._extract_uia_range_rect(caret)
                    # Walk the start of the range back N characters; the end stays at the caret.
                    caret.MoveEndpointByUnit(
                        TextPatternRangeEndpoint_Start, TextUnit_Character, -self._n
                    )
                    before = str(caret.GetText(self._n) or "")
                    if caret_rect is None:
                        caret_rect = self._extract_uia_range_rect(caret)
                    # Also check whether the whole document is empty (so the first word is a sentence start).
                    is_empty = False
                    try:
                        doc = text2.DocumentRange
                        whole = str(doc.GetText(2) or "")
                        is_empty = whole.strip() == ""
                    except Exception:
                        is_empty = before.strip() == ""
                    return CaretContext(
                        before.replace("\r\n", "\n"),
                        is_empty_field=is_empty,
                        source="uia",
                        caret_rect=caret_rect,
                        dpi=dpi,
                    )
            except Exception:
                pass

        # Fallback 2: UIA TextPattern (GetSelection -> caret-relative text + DocumentRange empty check)
        try:
            tp_pat = element.GetCurrentPattern(UIA_TextPatternId)
            if tp_pat is not None:
                tp = tp_pat.QueryInterface(mod.IUIAutomationTextPattern)
                doc = tp.DocumentRange
                is_empty = False
                if doc is not None:
                    try:
                        head = str(doc.GetText(4) or "")
                        is_empty = head.strip() == ""
                    except Exception:
                        is_empty = False
                # Prefer selection range so >256-char fields read text right before the caret!
                sel = tp.GetSelection()
                if sel is not None and int(sel.Length) > 0:
                    caret_rng = sel.GetElement(0)
                    if caret_rng is not None:
                        c_rect = win_rect or self._extract_uia_range_rect(caret_rng)
                        walk = caret_rng.Clone()
                        walk.MoveEndpointByUnit(
                            TextPatternRangeEndpoint_Start, TextUnit_Character, -self._n
                        )
                        before_sel = str(walk.GetText(self._n) or "").replace("\r\n", "\n")
                        if c_rect is None:
                            c_rect = self._extract_uia_range_rect(walk) or self._estimate_element_caret_rect(
                                element, before_sel, dpi
                            )
                        return CaretContext(
                            "" if is_empty else before_sel,
                            is_empty_field=is_empty,
                            source="uia-text1-sel",
                            caret_rect=c_rect,
                            dpi=dpi,
                        )
                if doc is not None:
                    whole = str(doc.GetText(self._n) or "").replace("\r\n", "\n")
                    is_empty = whole.strip() == ""
                    rect = win_rect or self._estimate_element_caret_rect(element, whole, dpi)
                    return CaretContext(
                        "" if is_empty else whole,
                        is_empty_field=is_empty,
                        source="uia-text1",
                        caret_rect=rect,
                        dpi=dpi,
                    )
        except Exception:
            pass

        # Fallback 3: UIA ValuePattern (single-line inputs, search bars, browser fields)
        try:
            val_pat = element.GetCurrentPattern(UIA_ValuePatternId)
            if val_pat is not None:
                vp = val_pat.QueryInterface(mod.IUIAutomationValuePattern)
                val_str = str(vp.CurrentValue or "").replace("\r\n", "\n")
                is_empty = val_str.strip() == ""
                tail = val_str[-self._n :] if not is_empty else ""
                rect = win_rect or self._estimate_element_caret_rect(element, tail, dpi)
                return CaretContext(
                    tail,
                    is_empty_field=is_empty,
                    source="uia-value",
                    caret_rect=rect,
                    dpi=dpi,
                )
        except Exception:
            pass

        # Fallback 4: UIA LegacyIAccessiblePattern on Edit / Document / ROLE_SYSTEM_TEXT controls
        # (UWP / XAML / WebView2 / WhatsApp inputs that bridge MSAA without ValuePattern).
        try:
            ctrl_type = 0
            try:
                ctrl_type = int(element.GetCurrentPropertyValue(UIA_ControlTypePropertyId) or 0)
            except Exception:
                ctrl_type = 0
            leg_pat = element.GetCurrentPattern(UIA_LegacyIAccessiblePatternId)
            if leg_pat is not None:
                leg = leg_pat.QueryInterface(mod.IUIAutomationLegacyIAccessiblePattern)
                role = int(leg.CurrentRole or 0)
                state = int(leg.CurrentState or 0)
                if state & STATE_SYSTEM_PROTECTED:
                    return CaretContext("", is_empty_field=False, is_password=True, source="uia-legacy")
                if ctrl_type in (UIA_EditControlTypeId, UIA_DocumentControlTypeId) or role == ROLE_SYSTEM_TEXT:
                    leg_val = str(leg.CurrentValue or "").replace("\r\n", "\n")
                    is_empty = leg_val.strip() == ""
                    tail = leg_val[-self._n :] if not is_empty else ""
                    rect = win_rect or self._estimate_element_caret_rect(element, tail, dpi)
                    return CaretContext(
                        tail,
                        is_empty_field=is_empty,
                        source="uia-legacy",
                        caret_rect=rect,
                        dpi=dpi,
                    )
        except Exception:
            pass

        return None

    @staticmethod
    def _estimate_element_caret_rect(
        element: Any,
        text_before: str,
        dpi: int = 96,
        *,
        allow_tall_composer: bool = False,
    ) -> tuple[int, int, int, int] | None:
        """
        Estimate caret/anchor coordinates from `element.CurrentBoundingRectangle`
        when a control does not expose `TextPattern` caret rectangles.
        """
        try:
            rc = element.CurrentBoundingRectangle
            left = int(rc.left)
            top = int(rc.top)
            right = int(rc.right)
            bottom = int(rc.bottom)
            width = right - left
            height = bottom - top
            max_h = 1080 if allow_tall_composer else 420
            if width <= 8 or height <= 8 or width > 3840 or height > max_h:
                return None
            scale = max(1.0, dpi / 96.0)
            line_h = min(max(16, int(20 * scale)), max(16, height - 4))
            last_line = text_before.rsplit("\n", 1)[-1] if text_before else ""
            char_w = max(6.0, 7.6 * scale)
            x_offset = int(12 * scale + min(48, len(last_line)) * char_w)
            cx = min(max(left + 12, right - 36), left + x_offset)
            if height <= int(56 * scale):
                cy = top + max(2, (height - line_h) // 2)
            elif height <= int(240 * scale):
                cy = top + int(8 * scale)
            else:
                # Tall chat/document container (e.g. WhatsApp/WebView pane): anchor near bottom composer
                cy = bottom - line_h - int(14 * scale)
                cx = left + int(20 * scale)
            return (cx, cy, 1, line_h)
        except Exception:
            return None

    @staticmethod
    def _extract_uia_range_rect(text_range: Any) -> tuple[int, int, int, int] | None:
        try:
            rects = text_range.GetBoundingRectangles()
            if rects and len(rects) >= 4:
                # Take the last rectangle (closest to the caret endpoint)
                base = len(rects) - 4
                left = int(round(float(rects[base])))
                top = int(round(float(rects[base + 1])))
                width = max(1, int(round(float(rects[base + 2]))))
                height = max(14, int(round(float(rects[base + 3]))))
                if height > 0 and (left != 0 or top != 0):
                    return (left + width, top, 1, height)
        except Exception:
            pass
        return None

    # ----------------------------------------------------- classic EDIT

    def _read_classic_edit(self) -> CaretContext | None:
        from autocorrect.adapters.windows import win32_api as w32

        user32 = w32.user32
        if user32 is None:
            return None
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        gti = w32.GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(w32.GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) or not gti.hwndFocus:
            return None
        focus = gti.hwndFocus
        cls_buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(focus, cls_buf, 64)
        cls = cls_buf.value.lower()
        if "edit" not in cls:
            return None
        result = ctypes.c_size_t(0)
        if not user32.SendMessageTimeoutW(
            focus, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, 50, ctypes.byref(result)
        ):
            return None
        length = int(result.value)
        if length == 0:
            return CaretContext("", is_empty_field=True, source="edit")
        sel_start = ctypes.c_ulong(0)
        sel_end = ctypes.c_ulong(0)
        user32.SendMessageTimeoutW(
            focus,
            EM_GETSEL,
            ctypes.addressof(sel_start),
            ctypes.addressof(sel_end),
            SMTO_ABORTIFHUNG,
            50,
            ctypes.byref(result),
        )
        caret_pos = int(sel_end.value)
        take = min(length, 4096)
        buf = ctypes.create_unicode_buffer(take + 1)
        if not user32.SendMessageTimeoutW(
            focus, WM_GETTEXT, take + 1, ctypes.addressof(buf), SMTO_ABORTIFHUNG, 50, ctypes.byref(result)
        ):
            return None
        text = buf.value.replace("\r\n", "\n")
        caret_pos = max(0, min(caret_pos, len(text)))
        before = text[max(0, caret_pos - self._n) : caret_pos]
        win_rect, dpi = self._read_win32_caret_rect()
        return CaretContext(
            before,
            is_empty_field=text.strip() == "",
            source="edit",
            caret_rect=win_rect,
            dpi=dpi,
        )


def create_caret_probe() -> WindowsCaretProbe | None:
    """Return a probe for this platform, or None where none exists."""
    if sys.platform == "win32":
        return WindowsCaretProbe()
    return None
