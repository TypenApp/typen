"""
macOS Quartz Unicode Text Injector (`CGEventKeyboardSetUnicodeString`).
Tags synthetic events with `kCGEventSourceUserData = MACOS_EVENT_USER_DATA_TAG`
so the Quartz event tap ignores its own injected events.
"""

from __future__ import annotations

import sys
from typing import Final

MACOS_EVENT_USER_DATA_TAG: Final[int] = 0x41434F52
MACOS_KEYCODE_DELETE: Final[int] = 51  # Backspace / Delete on macOS virtual keymap


class QuartzUnicodeInjector:
    """
    Injects synthetic Backspace (keycode 51) and Unicode strings via Quartz CGEventPost.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self.history: list[tuple[int, str]] = []

    def execute_replacement(self, backspaces: int, text_to_inject: str) -> None:
        self.history.append((backspaces, text_to_inject))
        if self._dry_run or sys.platform != "darwin":
            return

        try:
            import Quartz  # type: ignore[import-not-found]

            source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
            # 1. Emit Backspace keydown/keyup events
            for _ in range(max(0, backspaces)):
                for is_down in (True, False):
                    ev = Quartz.CGEventCreateKeyboardEvent(source, MACOS_KEYCODE_DELETE, is_down)
                    Quartz.CGEventSetIntegerValueField(
                        ev, Quartz.kCGEventSourceUserData, MACOS_EVENT_USER_DATA_TAG
                    )
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

            # 2. Emit Unicode string in a single keyboard event pair
            if text_to_inject:
                utf16_chars = len(text_to_inject.encode("utf-16-le")) // 2
                for is_down in (True, False):
                    ev = Quartz.CGEventCreateKeyboardEvent(source, 0, is_down)
                    Quartz.CGEventKeyboardSetUnicodeString(ev, utf16_chars, text_to_inject)
                    Quartz.CGEventSetIntegerValueField(
                        ev, Quartz.kCGEventSourceUserData, MACOS_EVENT_USER_DATA_TAG
                    )
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        except Exception:
            pass
