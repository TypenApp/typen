"""
Win32 Virtual-Key mapping and Unicode translation helper.
"""

from __future__ import annotations

from typing import Final

VK_BACK: Final[int] = 0x08
VK_TAB: Final[int] = 0x09
VK_RETURN: Final[int] = 0x0D
VK_SHIFT: Final[int] = 0x10
VK_CONTROL: Final[int] = 0x11
VK_MENU: Final[int] = 0x12  # Alt
VK_PAUSE: Final[int] = 0x13
VK_CAPITAL: Final[int] = 0x14
VK_ESCAPE: Final[int] = 0x1B
VK_SPACE: Final[int] = 0x20
VK_PRIOR: Final[int] = 0x21  # PageUp
VK_NEXT: Final[int] = 0x22  # PageDown
VK_END: Final[int] = 0x23
VK_HOME: Final[int] = 0x24
VK_LEFT: Final[int] = 0x25
VK_UP: Final[int] = 0x26
VK_RIGHT: Final[int] = 0x27
VK_DOWN: Final[int] = 0x28
VK_INSERT: Final[int] = 0x2D
VK_DELETE: Final[int] = 0x2E
VK_LWIN: Final[int] = 0x5B
VK_RWIN: Final[int] = 0x5C

VK_TO_KEY_NAME: Final[dict[int, str]] = {
    VK_BACK: "Backspace",
    VK_TAB: "Tab",
    VK_RETURN: "Return",
    VK_ESCAPE: "Escape",
    VK_SPACE: "Space",
    VK_PRIOR: "PageUp",
    VK_NEXT: "PageDown",
    VK_END: "End",
    VK_HOME: "Home",
    VK_LEFT: "Left",
    VK_UP: "Up",
    VK_RIGHT: "Right",
    VK_DOWN: "Down",
    VK_INSERT: "Insert",
    VK_DELETE: "Delete",
}
