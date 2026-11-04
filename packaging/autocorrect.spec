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

# Hidden imports: OS adapters are imported lazily via factories, tray/UI are optional paths.
hidden = [
    "autocorrect.launcher",
    "autocorrect.ui.settings_main",
    "autocorrect.daemon.tray",
    "autocorrect.platform_paths",
    "tkinter",
    "tkinter.ttk",
]
if IS_WIN:
    hidden += [
        "autocorrect.adapters.windows.win32_hook",
        "autocorrect.adapters.windows.win32_injector",
        "autocorrect.adapters.windows.uia_inspector",
        "autocorrect.adapters.windows.win_keymap",
        "pystray._win32",
        "keyring.backends.Windows",
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
    "PySide6", "PyQt5", "PyQt6", "IPython", "pytest", "wordfreq",
    # NOTE: autocorrect.adapters.{windows,macos,linux} all stay bundled — daemon/app.py
    # imports them at module level and each no-ops off-platform via sys.platform guards.
]
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
