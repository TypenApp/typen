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

DEFAULT_CONTEXT_CHARS: Final[int] = 64
PROBE_BUDGET_S: Final[float] = 0.25

UIA_TextPattern2Id: Final[int] = 10024
UIA_TextPatternId: Final[int] = 10014
UIA_ValuePatternId: Final[int] = 10002
UIA_IsPasswordPropertyId: Final[int] = 30019
TextUnit_Character: Final[int] = 0
TextPatternRangeEndpoint_Start: Final[int] = 0
TextPatternRangeEndpoint_End: Final[int] = 1

EM_GETSEL: Final[int] = 0x00B0
WM_GETTEXT: Final[int] = 0x000D
WM_GETTEXTLENGTH: Final[int] = 0x000E
SMTO_ABORTIFHUNG: Final[int] = 0x0002


class CaretContext:
    """Text before the caret, plus what we know about the field."""

    __slots__ = ("text_before", "is_empty_field", "is_password", "source")

    def __init__(
        self, text_before: str, *, is_empty_field: bool, is_password: bool = False, source: str = ""
    ):
        self.text_before = text_before
        self.is_empty_field = is_empty_field
        self.is_password = is_password
        self.source = source

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CaretContext({self.text_before!r}, empty={self.is_empty_field}, src={self.source})"


class WindowsCaretProbe:
    """
    Best-effort "what is before the caret?" for the focused control.

    Thread-safety: COM is initialised per calling thread (MTA); the probe is
    designed to be called from the input dispatcher worker only.
    """

    def __init__(self, context_chars: int = DEFAULT_CONTEXT_CHARS) -> None:
        self._n = max(8, context_chars)
        self._uia: Any = None
        self._uia_failed = False
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
        if self._uia is not None or self._uia_failed:
            return self._uia
        with self._lock:
            if self._uia is not None or self._uia_failed:
                return self._uia
            try:
                import comtypes  # type: ignore[import-not-found]
                import comtypes.client  # type: ignore[import-not-found]

                self._init_com(comtypes)
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen import UIAutomationClient as uia  # type: ignore[import-not-found]

                self._uia_mod = uia
                self._uia = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
                log.info("UI Automation caret probe ready")
            except Exception as exc:
                self._uia_failed = True
                log.info("UI Automation caret probe unavailable: %r", exc)
        return self._uia

    def _init_com(self, comtypes_mod: Any) -> None:
        tid = threading.get_ident()
        if tid in self._com_threads:
            return
        try:
            comtypes_mod.CoInitializeEx(comtypes_mod.COINIT_MULTITHREADED)
        except Exception:
            pass
        self._com_threads.add(tid)

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
        pattern = element.GetCurrentPattern(UIA_TextPattern2Id)
        if pattern is None:
            return None
        text2 = pattern.QueryInterface(mod.IUIAutomationTextPattern2)
        is_active = ctypes.c_int(0)
        caret = text2.GetCaretRange(ctypes.byref(is_active))
        if caret is None:
            return None
        # Walk the start of the range back N characters; the end stays at the caret.
        caret.MoveEndpointByUnit(TextPatternRangeEndpoint_Start, TextUnit_Character, -self._n)
        before = str(caret.GetText(self._n) or "")
        # Also check whether the whole document is empty (so the first word is a sentence start).
        is_empty = False
        try:
            doc = text2.DocumentRange
            whole = str(doc.GetText(2) or "")
            is_empty = whole.strip() == ""
        except Exception:
            is_empty = before.strip() == ""
        return CaretContext(before.replace("\r\n", "\n"), is_empty_field=is_empty, source="uia")

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
        return CaretContext(before, is_empty_field=text.strip() == "", source="edit")


def create_caret_probe() -> WindowsCaretProbe | None:
    """Return a probe for this platform, or None where none exists."""
    if sys.platform == "win32":
        return WindowsCaretProbe()
    return None
