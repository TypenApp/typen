"""
Windows OS Integration Adapter (Win32 Low-Level Hooks, Atomic SendInput, and UIA Password Inspection).
"""

from autocorrect.adapters.windows.uia_inspector import Win32FocusInspector
from autocorrect.adapters.windows.win32_hook import Win32KeyboardMouseHook
from autocorrect.adapters.windows.win32_injector import (
    AUTOCORRECT_EXTRA_INFO_TAG,
    Win32UnicodeInjector,
)

__all__ = [
    "AUTOCORRECT_EXTRA_INFO_TAG",
    "Win32FocusInspector",
    "Win32KeyboardMouseHook",
    "Win32UnicodeInjector",
]
