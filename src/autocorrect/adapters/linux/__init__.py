"""
Linux OS Integration Adapters:
- X11 (`XRecord` / `XTest` adapter for Xorg sessions)
- Wayland (`IBus` Input Method Engine adapter respecting compositor security and password purpose flags)
"""

from autocorrect.adapters.linux.ibus_engine import WaylandIBusEngineAdapter
from autocorrect.adapters.linux.x11_adapter import X11FocusInspector, X11TextInjector

__all__ = [
    "WaylandIBusEngineAdapter",
    "X11FocusInspector",
    "X11TextInjector",
]
