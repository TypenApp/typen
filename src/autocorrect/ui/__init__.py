"""
Out-of-process Desktop Customisation UI (`autocorrect.ui`).
Provides the 10-screen `SettingsController`, `PySide6-Essentials` QML bridge,
and LGPLv3 module compliance verifier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autocorrect.ui.lgpl_compliance import (
    GPL_FORBIDDEN_QT_MODULES,
    LGPL_ALLOWED_QT_MODULES,
    NUITKA_EXCLUDED_QML_PLUGINS,
    assert_no_gpl_qt_modules_loaded,
    scan_distribution_dir_for_gpl_binaries,
)

if TYPE_CHECKING:
    from autocorrect.ui.settings_main import SCREEN_NAMES, SettingsController

__all__ = [
    "GPL_FORBIDDEN_QT_MODULES",
    "LGPL_ALLOWED_QT_MODULES",
    "NUITKA_EXCLUDED_QML_PLUGINS",
    "SCREEN_NAMES",
    "SettingsController",
    "assert_no_gpl_qt_modules_loaded",
    "scan_distribution_dir_for_gpl_binaries",
]


def __getattr__(name: str) -> Any:
    if name in ("SCREEN_NAMES", "SettingsController"):
        from autocorrect.ui import settings_main

        return getattr(settings_main, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
