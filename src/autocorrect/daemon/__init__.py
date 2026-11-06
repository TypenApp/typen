"""
Background Daemon Package.
Manages single-instance locking, system tray / menu bar presence,
OS startup registration, and the main background event loop.
"""

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.daemon.single_instance import SingleInstanceGuard
from autocorrect.daemon.startup import StartupManager
from autocorrect.daemon.tray import SystemTrayController

__all__ = [
    "AutoCorrectDaemon",
    "SingleInstanceGuard",
    "StartupManager",
    "SystemTrayController",
]
