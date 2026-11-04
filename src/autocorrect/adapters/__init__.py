"""
Cross-Platform OS Adapters (Windows, macOS, Linux).
Provides clean isolation between the core autocorrection engine and
platform-specific keyboard hooks, text injectors, and focus/password inspectors.
"""

from __future__ import annotations

import sys

from autocorrect.input.ports import FocusInspectorPort, TextInjectorPort


def create_platform_injector() -> TextInjectorPort:
    """Instantiate the appropriate TextInjectorPort for the current operating system."""
    if sys.platform == "win32":
        from autocorrect.adapters.windows.win32_injector import Win32UnicodeInjector

        return Win32UnicodeInjector()
    if sys.platform == "darwin":
        from autocorrect.adapters.macos.quartz_injector import QuartzUnicodeInjector

        return QuartzUnicodeInjector()
    from autocorrect.adapters.linux.x11_adapter import X11TextInjector

    return X11TextInjector()


def create_platform_focus_inspector() -> FocusInspectorPort:
    """Instantiate the appropriate FocusInspectorPort for the current operating system."""
    if sys.platform == "win32":
        from autocorrect.adapters.windows.uia_inspector import Win32FocusInspector

        return Win32FocusInspector()
    if sys.platform == "darwin":
        from autocorrect.adapters.macos.ax_inspector import MacAXFocusInspector

        return MacAXFocusInspector()
    from autocorrect.adapters.linux.x11_adapter import X11FocusInspector

    return X11FocusInspector()
