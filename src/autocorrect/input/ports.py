"""
OS-Independent Ports and Value Objects for Keyboard Interception,
Focus/Password Inspection, and Atomic Text Injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class KeyAction(str, Enum):
    """Disposition of an intercepted keyboard event."""

    PASS_THROUGH = "PASS_THROUGH"
    SUPPRESS_AND_INJECT = "SUPPRESS_AND_INJECT"


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """Normalized OS-independent representation of a physical or synthetic key event."""

    key_name: str  # e.g. 'a', 'Space', 'Backspace', 'Return', 'Left', 'Tab'
    char: str  # Printable character if any, else ''
    timestamp_ms: float
    ctrl_pressed: bool = False
    alt_pressed: bool = False
    meta_pressed: bool = False
    shift_pressed: bool = False
    is_injected: bool = False


@dataclass(frozen=True, slots=True)
class FocusContext:
    """Metadata about the currently focused OS window and text control."""

    process_name: str = ""
    window_title: str = ""
    bundle_or_app_id: str = ""
    is_password_or_secure: bool = False
    is_terminal_or_code: bool = False
    is_excluded_app: bool = False


class TextInjectorPort(Protocol):
    """Port implemented by OS adapters to atomically backspace and inject Unicode text."""

    def execute_replacement(self, backspaces: int, text_to_inject: str) -> None: ...


class FocusInspectorPort(Protocol):
    """Port implemented by OS adapters to query the active window and password field state."""

    def get_current_focus(self) -> FocusContext: ...
