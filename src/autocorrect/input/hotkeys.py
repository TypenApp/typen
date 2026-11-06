"""
Parse the hotkey strings stored in preferences ("Ctrl+Alt+P", "Ctrl+Shift+R",
"Ctrl+Alt+,") into a platform-neutral chord that each OS adapter maps to its
own registration API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

_MODIFIER_ALIASES: Final[dict[str, str]] = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "shift": "shift",
    "win": "meta",
    "windows": "meta",
    "super": "meta",
    "meta": "meta",
    "cmd": "meta",
    "command": "meta",
}

_KEY_ALIASES: Final[dict[str, str]] = {
    "comma": ",",
    "period": ".",
    "dot": ".",
    "space": "Space",
    "spacebar": "Space",
    "esc": "Escape",
    "escape": "Escape",
    "return": "Return",
    "enter": "Return",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pgup": "PageUp",
    "pagedown": "PageDown",
    "pgdn": "PageDown",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
}


@dataclass(frozen=True, slots=True)
class Hotkey:
    key: str  # single character ("P", ",") or a named key ("Escape", "F5")
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False

    @property
    def has_modifier(self) -> bool:
        return self.ctrl or self.alt or self.shift or self.meta

    def label(self) -> str:
        parts = []
        if self.ctrl:
            parts.append("Ctrl")
        if self.alt:
            parts.append("Alt")
        if self.shift:
            parts.append("Shift")
        if self.meta:
            parts.append("Win")
        parts.append(self.key)
        return "+".join(parts)


def parse_hotkey(spec: str | None) -> Hotkey | None:
    """
    Parse "Ctrl+Alt+P" style strings. Returns None for empty/unparseable input
    or for a bare key without any modifier (a global hotkey on a plain letter
    would swallow ordinary typing).
    """
    if not spec:
        return None
    text = spec.strip()
    if not text:
        return None
    # Split on '+' but keep a trailing '+' key ("Ctrl++") intact.
    raw_parts = [p for p in text.replace(" ", "").split("+")]
    parts: list[str] = []
    for i, p in enumerate(raw_parts):
        if p == "" and i == len(raw_parts) - 1 and parts:
            parts.append("+")
        elif p:
            parts.append(p)
    if not parts:
        return None
    key_part = parts[-1]
    mods = parts[:-1]
    flags = {"ctrl": False, "alt": False, "shift": False, "meta": False}
    for m in mods:
        canon = _MODIFIER_ALIASES.get(m.lower())
        if canon is None:
            return None
        flags[canon] = True
    low = key_part.lower()
    if low in _KEY_ALIASES:
        key = _KEY_ALIASES[low]
    elif len(key_part) == 1:
        key = key_part.upper()
    elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        key = "F" + low[1:]
    else:
        return None
    hk = Hotkey(key=key, **flags)
    if not hk.has_modifier:
        return None
    return hk
