"""
macOS OS Integration Adapter (Quartz Event Tap, Unicode Injection, and Accessibility API).
"""

from autocorrect.adapters.macos.ax_inspector import MacAXFocusInspector
from autocorrect.adapters.macos.quartz_injector import (
    MACOS_EVENT_USER_DATA_TAG,
    QuartzUnicodeInjector,
)
from autocorrect.adapters.macos.quartz_tap import QuartzEventTapManager

__all__ = [
    "MACOS_EVENT_USER_DATA_TAG",
    "MacAXFocusInspector",
    "QuartzEventTapManager",
    "QuartzUnicodeInjector",
]
