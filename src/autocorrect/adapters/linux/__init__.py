"""
Linux OS Integration Adapters:
- X11 (`XRecord` hook / `XTest` injector / EWMH focus inspector for Xorg sessions)
- Wayland (`IBus` Input Method Engine adapter respecting compositor security and password purpose flags)
- Session detection (X11 vs Wayland vs headless) used by the daemon to pick a backend
"""

from autocorrect.adapters.linux.ibus_engine import WaylandIBusEngineAdapter
from autocorrect.adapters.linux.session_type import LinuxSessionType, detect_linux_session
from autocorrect.adapters.linux.x11_adapter import X11FocusInspector, X11TextInjector
from autocorrect.adapters.linux.x11_hook import X11HookError, X11KeyboardMouseHook

__all__ = [
    "LinuxSessionType",
    "WaylandIBusEngineAdapter",
    "X11FocusInspector",
    "X11HookError",
    "X11KeyboardMouseHook",
    "X11TextInjector",
    "detect_linux_session",
]
