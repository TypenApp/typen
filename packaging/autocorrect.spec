# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller One-Folder Specification for Typen (Windows, macOS, Linux).

Uses COLLECT (one-folder mode) rather than one-file mode to guarantee:
1. Sub-400ms cold startup (no temp-dir archive extraction on every boot).
2. Shared read-only OS mmap pages for `resources/en_base/`.
3. Minimal antivirus heuristic false-positive footprint.

Entry point is `autocorrect.launcher:main`, which serves both the background
daemon (+ system tray) and the `--settings` UI from a single executable.

On macOS the COLLECT output is additionally wrapped in an `.app` BUNDLE with
`packaging/macos_Info.plist` (LSUIElement agent app, Input Monitoring and
Accessibility usage strings) so TCC prompts show a proper app name.
"""

import sys
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH).parent
packaging_dir = project_root / "packaging"

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# The Settings window is PySide6/QML (LGPLv3 Essentials modules only). When the
# build environment lacks PySide6 the frozen app falls back to the tkinter window,
# exactly as a source install does; the QML tree is still shipped so a later
# `pip install PySide6-Essentials` next to a source checkout picks it up.
try:
    import PySide6  # noqa: F401

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False
    print("WARNING: PySide6-Essentials not installed; the frozen Settings window will be the tkinter fallback")

# Hidden imports: OS adapters are imported lazily via factories, tray/UI are optional paths.
hidden = [
    "autocorrect.launcher",
    "autocorrect.ui.settings_main",
    "autocorrect.ui.qml_bridge",
    "autocorrect.ui.lgpl_compliance",
    "autocorrect.feedback",
    "autocorrect.branding",
    "autocorrect.daemon.tray",
    "autocorrect.daemon.kill_switch",
    "autocorrect.daemon.input_dispatcher",
    "autocorrect.preferences.settings_schema",
    "autocorrect.preferences.system_locale",
    "autocorrect.logging_setup",
    "autocorrect.platform_paths",
    "tkinter",
    "tkinter.ttk",
]
if HAS_PYSIDE6:
    hidden += [
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
    ]
if IS_WIN:
    hidden += [
        "autocorrect.adapters.windows.win32_api",
        "autocorrect.adapters.windows.win32_hook",
        "autocorrect.adapters.windows.win32_injector",
        "autocorrect.adapters.windows.uia_inspector",
        "autocorrect.adapters.windows.caret_probe",
        "autocorrect.adapters.windows.window_list",
        "autocorrect.adapters.windows.win_keymap",
        "pystray._win32",
        "keyring.backends.Windows",
        # UI Automation caret probe (optional at runtime; bundled when installed).
        "comtypes",
        "comtypes.client",
        "comtypes.stream",
    ]
elif IS_MAC:
    hidden += [
        "autocorrect.adapters.macos.quartz_tap",
        "autocorrect.adapters.macos.quartz_injector",
        "autocorrect.adapters.macos.ax_inspector",
        "pystray._darwin",
        "keyring.backends.macOS",
        "Quartz",
        "ApplicationServices",
        "AppKit",
        "Foundation",
        "objc",
    ]
elif IS_LINUX:
    hidden += [
        "autocorrect.adapters.linux.session_type",
        "autocorrect.adapters.linux.x11_adapter",
        "autocorrect.adapters.linux.x11_hook",
        "autocorrect.adapters.linux.ibus_engine",
        "pystray._xorg",
        "pystray._appindicator",
        "pystray._gtk",
        "keyring.backends.SecretService",
        "keyring.backends.libsecret",
        "keyring.backends.kwallet",
        "keyring.backends.chainer",
        "secretstorage",
        "jeepney",
        "Xlib",
        "Xlib.ext.record",
        "Xlib.ext.xtest",
        "Xlib.keysymdef",
        "Xlib.keysymdef.latin1",
        "Xlib.keysymdef.miscellany",
    ]

excludes = [
    "matplotlib", "scipy", "pandas", "torch", "tensorflow", "numpy",
    "PyQt5", "PyQt6", "IPython", "pytest", "wordfreq",
    # NOTE: autocorrect.adapters.{windows,macos,linux} all stay bundled — daemon/app.py
    # imports them at module level and each no-ops off-platform via sys.platform guards.
]
# Only the LGPLv3 Essentials modules the Settings window uses may ship. Everything
# else in a (possibly full) PySide6 install is excluded: GPLv3-only Addons would
# break the licence, and the rest is dead weight (WebEngine alone is ~150 MB).
_QT_UNUSED = (
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtBluetooth", "QtCharts", "QtCoap", "QtConcurrent", "QtDataVisualization", "QtDesigner",
    "QtGraphs", "QtGraphsWidgets", "QtGrpc", "QtHelp", "QtHttpServer", "QtLocation", "QtMqtt",
    # (QtOpenGL stays: PySide6.QtQuick imports it at module level.)
    "QtMultimedia", "QtMultimediaWidgets", "QtNetworkAuth", "QtNfc", "QtOpenGLWidgets",
    "QtPdf", "QtPdfWidgets", "QtPositioning", "QtPrintSupport", "QtQuick3D", "QtQuickTest",
    "QtQuickWidgets", "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort",
    "QtSpatialAudio", "QtSql", "QtStateMachine", "QtSvg", "QtSvgWidgets", "QtTest", "QtTextToSpeech",
    "QtUiTools", "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick", "QtWebEngineWidgets",
    "QtWebSockets", "QtWebView", "QtWidgets", "QtXml", "QtAsyncio",
)
excludes += [f"PySide6.{m}" for m in _QT_UNUSED]
if not HAS_PYSIDE6:
    excludes += ["PySide6", "shiboken6"]
if not IS_MAC:
    excludes += ["Quartz", "ApplicationServices", "AppKit", "Foundation", "objc"]
if not IS_LINUX:
    excludes += ["Xlib", "gi", "secretstorage", "jeepney"]

a = Analysis(
    [str(packaging_dir / "entry_autocorrect_desktop.py")],
    pathex=[str(project_root / "src"), str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "resources" / "en_base"), "resources/en_base"),
        # Syne (OFL) for the brand mark drawn at runtime by autocorrect.branding (tray icon).
        (str(packaging_dir / "fonts"), "fonts"),
        # QML Settings window (Main.qml, pages/, the `Typen` module). qml_bridge resolves it
        # relative to its own __file__, which lives under _internal/autocorrect/ui/ when frozen.
        (str(project_root / "src" / "autocorrect" / "ui" / "qml"), "autocorrect/ui/qml"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PyInstaller's PySide6 hooks collect the whole Qt QML tree. Drop the pieces the
# Settings window never imports (it uses QtQuick, Controls (Basic style), Layouts
# and Dialogs) and, above all, the GPLv3-only Timeline / VirtualKeyboard plugins so
# `lgpl_compliance.scan_distribution_dir_for_gpl_binaries` stays clean.
_QT_PRUNE = (
    # GPLv3-only (never ship)
    "quicktimeline", "quick/timeline", "virtualkeyboard",
    # Not used by the Settings window
    "qt6test.dll", "quicktest", "qml/qttest", "qt6sql", "localstorage", "quickparticles",
    "quick/particles", "wavefrontmesh", "qmldesignsupport", "vectorimage", "shapesdesignhelpers",
    "xmllistmodel", "sharedimage", "labsanimation", "labs/animation", "folderlistmodel",
    "labssettings", "labs/settings", "labssynchronizer", "labs/synchronizer", "labsplatform",
    "labs/platform", "quickeffects", "quick/effects", "quicknativestyle", "quick/nativestyle",
    "quick/tooling", "controls/designer",
    # Control styles other than Basic (QQuickStyle.setStyle("Basic") in qml_bridge)
    "controls2fusion", "controls/fusion", "controls2imagine", "controls/imagine",
    "controls2material", "controls/material", "controls2universal", "controls/universal",
    "controls2fluentwinui3", "controls/fluentwinui3", "controls2windows", "controls/windows",
    "controls2native", "controls/native",
)


def _ship(entry):
    dest = str(entry[0]).replace("\\", "/").lower()
    if "pyside6/" not in dest:
        return True
    return not any(p in dest for p in _QT_PRUNE)


a.binaries = [e for e in a.binaries if _ship(e)]
a.datas = [e for e in a.datas if _ship(e)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_kwargs = {}
if IS_WIN:
    exe_kwargs.update(
        icon=str(packaging_dir / "autocorrect.ico"),
        version=str(packaging_dir / "windows_version_info.txt"),
    )
elif IS_MAC:
    icns = packaging_dir / "autocorrect.icns"
    if icns.exists():
        exe_kwargs["icon"] = str(icns)
    # Ad-hoc signing here keeps the binary loadable during local dev; the real
    # Developer ID signature is applied over the whole .app by build_macos_beta.sh.
    exe_kwargs.update(codesign_identity=None, entitlements_file=None, target_arch=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoCorrectDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    **exe_kwargs,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoCorrectDesktop",
)

if IS_MAC:
    import plistlib

    with open(packaging_dir / "macos_Info.plist", "rb") as fh:
        info_plist = plistlib.load(fh)

    app = BUNDLE(
        coll,
        name="Typen.app",
        icon=str(packaging_dir / "autocorrect.icns") if (packaging_dir / "autocorrect.icns").exists() else None,
        bundle_identifier=info_plist.get("CFBundleIdentifier", "io.autocorrect.desktop"),
        info_plist=info_plist,
    )
