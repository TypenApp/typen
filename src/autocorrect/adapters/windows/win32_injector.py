"""
Windows Atomic Unicode Text Injector (`SendInput` with `KEYEVENTF_UNICODE`).
Tags every synthetic INPUT struct with `dwExtraInfo = AUTOCORRECT_EXTRA_INFO_TAG`
so the `WH_KEYBOARD_LL` hook recognizes and ignores its own injected events.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Final

from autocorrect.adapters.windows.win_keymap import VK_BACK

# Custom magic tag ("ACOR" = 0x41434F52) stamped onto dwExtraInfo of all injected events
AUTOCORRECT_EXTRA_INFO_TAG: Final[int] = 0x41434F52

INPUT_KEYBOARD: Final[int] = 1
KEYEVENTF_KEYUP: Final[int] = 0x0002
KEYEVENTF_UNICODE: Final[int] = 0x0004


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", _INPUT_UNION),
    ]


class Win32UnicodeInjector:
    """
    Packs all required `VK_BACK` keydowns/keyups and UTF-16 `KEYEVENTF_UNICODE`
    events into a single atomic `SendInput` array call.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self.history: list[tuple[int, str]] = []

    @staticmethod
    def build_input_structs(backspaces: int, text_to_inject: str) -> list[INPUT]:
        """
        Construct the exact sequence of Win32 INPUT structs for `backspaces` + `text_to_inject`.
        Handles surrogate pairs (UTF-16LE code units) cleanly.
        """
        events: list[INPUT] = []

        # 1. Backspace keydown + keyup pairs
        for _ in range(max(0, backspaces)):
            down = INPUT(type=INPUT_KEYBOARD)
            down.union.ki = KEYBDINPUT(
                wVk=VK_BACK,
                wScan=0,
                dwFlags=0,
                time=0,
                dwExtraInfo=AUTOCORRECT_EXTRA_INFO_TAG,
            )
            up = INPUT(type=INPUT_KEYBOARD)
            up.union.ki = KEYBDINPUT(
                wVk=VK_BACK,
                wScan=0,
                dwFlags=KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=AUTOCORRECT_EXTRA_INFO_TAG,
            )
            events.append(down)
            events.append(up)

        # 2. Unicode UTF-16LE code units
        utf16_bytes = text_to_inject.encode("utf-16-le")
        for i in range(0, len(utf16_bytes), 2):
            code_unit = int.from_bytes(utf16_bytes[i : i + 2], "little")
            down = INPUT(type=INPUT_KEYBOARD)
            down.union.ki = KEYBDINPUT(
                wVk=0,
                wScan=code_unit,
                dwFlags=KEYEVENTF_UNICODE,
                time=0,
                dwExtraInfo=AUTOCORRECT_EXTRA_INFO_TAG,
            )
            up = INPUT(type=INPUT_KEYBOARD)
            up.union.ki = KEYBDINPUT(
                wVk=0,
                wScan=code_unit,
                dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=AUTOCORRECT_EXTRA_INFO_TAG,
            )
            events.append(down)
            events.append(up)

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
        user32 = ctypes.windll.user32
        user32.SendInput(len(events), ctypes.byref(input_array), ctypes.sizeof(INPUT))
