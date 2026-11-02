"""
Qt 6 / PySide6 LGPLv3 Commercial Compliance Verifier.
Ensures that only LGPLv3-licensed modules from `PySide6-Essentials` are ever
imported or bundled, and blocks GPLv3-only Qt modules in proprietary builds.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

# Qt 6 modules licensed under GNU LGPLv3 (safe for proprietary commercial distribution
# when dynamically linked in Nuitka --standalone directory mode).
LGPL_ALLOWED_QT_MODULES: Final[frozenset[str]] = frozenset(
    {
        "QtCore",
        "QtGui",
        "QtQml",
        "QtQuick",
        "QtQuickControls2",
        "QtQuickLayouts",
        "QtQuickDialogs",
        "QtSvg",
        "QtWidgets",
        "QtNetwork",
        "QtDBus",
        "QtOpenGL",
        "Shiboken",
    }
)

# Qt 6 modules that are GPLv3-only in open-source distributions and MUST NEVER
# be imported or shipped in a proprietary closed-source build without a commercial Qt license.
GPL_FORBIDDEN_QT_MODULES: Final[frozenset[str]] = frozenset(
    {
        "QtCharts",
        "QtGraphs",
        "QtQuick3D",
        "QtQuick3DPhysics",
        "QtQuickTimeline",
        "QtLottieAnimation",
        "QtCanvasPainter",
        "QtVirtualKeyboard",
        "QtNetworkAuth",
        "QtHttpServer",
        "QtGrpc",
        "QtMqtt",
        "QtCoap",
        "QtWaylandCompositor",
    }
)

# Heavy unused QML plugins excluded during `pyside6-deploy` / `Nuitka --standalone` packaging.
NUITKA_EXCLUDED_QML_PLUGINS: Final[tuple[str, ...]] = (
    "QtQuick3D",
    "QtCharts",
    "QtGraphs",
    "QtWebEngine",
    "QtTest",
    "QtSensors",
    "QtMultimedia",
)


def assert_no_gpl_qt_modules_loaded() -> list[str]:
    """
    Inspect `sys.modules` to verify that no GPLv3-only `PySide6` module has been imported.
    Raises ` RuntimeError` if any forbidden module is present.
    """
    violations: list[str] = []
    for mod_name in list(sys.modules.keys()):
        if not mod_name.startswith("PySide6."):
            continue
        sub = mod_name.split(".", 1)[1].split(".")[0]
        if sub in GPL_FORBIDDEN_QT_MODULES:
            violations.append(mod_name)
    if violations:
        raise RuntimeError(
            f"LGPLv3 compliance violation: GPLv3-only PySide6 modules loaded: {violations}"
        )
    return violations


def scan_distribution_dir_for_gpl_binaries(dist_dir: Path) -> list[str]:
    """
    Scan a compiled Nuitka `.dist` or `.app` directory to ensure no GPLv3-only
    Qt shared libraries (`Qt6Charts.dll`, `libQt6Quick3D.so`, etc.) are bundled.
    """
    if not dist_dir.exists():
        return []
    forbidden_files: list[str] = []
    for path in dist_dir.rglob("*"):
        if not path.is_file():
            continue
        name_low = path.name.lower()
        for gpl_mod in GPL_FORBIDDEN_QT_MODULES:
            # Match e.g. 'qt6charts.dll', 'libqt6charts.so', 'qtcharts.pyd'
            token_qt6 = gpl_mod.lower().replace("qt", "qt6", 1)
            token_qt = gpl_mod.lower()
            if token_qt6 in name_low or token_qt in name_low:
                forbidden_files.append(str(path.relative_to(dist_dir)))
    return sorted(set(forbidden_files))
