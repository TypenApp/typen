"""
Windows Atomic Unicode Text Injector (`SendInput` with `KEYEVENTF_UNICODE`).
Tags every synthetic INPUT struct with `dwExtraInfo = AUTOCORRECT_EXTRA_INFO_TAG`
so the `WH_KEYBOARD_LL` hook recognizes and ignores its own injected events.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any, Final

from autocorrect.adapters.windows import win32_api as w32
from autocorrect.adapters.windows.win_keymap import VK_BACK

# Custom magic tag ("ACOR" = 0x41434F52) stamped onto dwExtraInfo of all injected events
AUTOCORRECT_EXTRA_INFO_TAG: Final[int] = 0x41434F52

INPUT_KEYBOARD: Final[int] = w32.INPUT_KEYBOARD
KEYEVENTF_KEYUP: Final[int] = w32.KEYEVENTF_KEYUP
KEYEVENTF_UNICODE: Final[int] = w32.KEYEVENTF_UNICODE

if w32.IS_WINDOWS:
    KEYBDINPUT = w32.KEYBDINPUT
    MOUSEINPUT = w32.MOUSEINPUT
    HARDWAREINPUT = w32.HARDWAREINPUT
    INPUT = w32.INPUT
else:  # Portable definitions so the struct builder is unit-testable on any OS.

    class KEYBDINPUT(ctypes.Structure):  # type: ignore[no-redef]
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class MOUSEINPUT(ctypes.Structure):  # type: ignore[no-redef]
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):  # type: ignore[no-redef]
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):  # type: ignore[no-redef]
        _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]


class Win32UnicodeInjector:
    """
    Packs all required `VK_BACK` keydowns/keyups and UTF-16 `KEYEVENTF_UNICODE`
    events into a single atomic `SendInput` array call.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self.history: list[tuple[int, str]] = []

    @staticmethod
    def build_input_structs(backspaces: int, text_to_inject: str) -> list[Any]:
        """
        Construct the exact sequence of Win32 INPUT structs for `backspaces` + `text_to_inject`.
        Handles surrogate pairs (UTF-16LE code units) cleanly.
        """
        events: list[Any] = []

        def _key(vk: int, scan: int, flags: int) -> Any:
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.union.ki = KEYBDINPUT(
                wVk=vk,
                wScan=scan,
                dwFlags=flags,
                time=0,
                dwExtraInfo=AUTOCORRECT_EXTRA_INFO_TAG,
            )
            return inp

        # 1. Backspace keydown + keyup pairs
        for _ in range(max(0, backspaces)):
            events.append(_key(VK_BACK, 0, 0))
            events.append(_key(VK_BACK, 0, KEYEVENTF_KEYUP))

        # 2. Unicode UTF-16LE code units
        utf16_bytes = text_to_inject.encode("utf-16-le")
        for i in range(0, len(utf16_bytes), 2):
            code_unit = int.from_bytes(utf16_bytes[i : i + 2], "little")
            events.append(_key(0, code_unit, KEYEVENTF_UNICODE))
            events.append(_key(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))

        return events

    def execute_replacement(self, backspaces: int, text_to_inject: str) -> None:
        """Atomically send the backspace + Unicode sequence to the active Windows control."""
        self.history.append((backspaces, text_to_inject))
        if self._dry_run or sys.platform != "win32":
            return

        events = self.build_input_structs(backspaces, text_to_inject)
        if not events:
            return

        array_type = INPUT * len(events)
        input_array = array_type(*events)
        sent = w32.user32.SendInput(len(events), input_array, ctypes.sizeof(INPUT))
        if sent != len(events):
            import logging

            logging.getLogger(__name__).warning(
                "SendInput delivered %d/%d events: %s",
                sent,
                len(events),
                w32.win_error_message(w32.last_error()),
            )
