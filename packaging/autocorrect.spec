# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller One-Folder Specification for AutoCorrect Desktop.
Uses COLLECT (one-folder mode) rather than one-file mode to guarantee:
1. Sub-400ms cold startup (no %TEMP% archive extraction on every boot).
2. Shared read-only OS mmap pages for `resources/en_base/`.
3. Minimal antivirus heuristic false-positive footprint.

Entry point is `autocorrect.launcher:main`, which serves both the background
daemon (+ system tray) and the `--settings` UI from a single executable.
"""

from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH).parent

# Hidden imports: OS adapters are imported lazily via factories, tray/UI are optional paths.
hidden = [
    "autocorrect.launcher",
    "autocorrect.ui.settings_main",
    "autocorrect.daemon.tray",
    "autocorrect.adapters.windows.win32_hook",
    "autocorrect.adapters.windows.win32_injector",
    "autocorrect.adapters.windows.uia_inspector",
    "autocorrect.adapters.windows.win_keymap",
    "pystray._win32",
    "keyring.backends.Windows",
    "tkinter",
    "tkinter.ttk",
]

a = Analysis(
    [str(project_root / "packaging" / "entry_autocorrect_desktop.py")],
    pathex=[str(project_root / "src"), str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "resources" / "en_base"), "resources/en_base"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "pandas", "torch", "tensorflow", "numpy",
        "PySide6", "PyQt5", "PyQt6", "IPython", "pytest", "wordfreq",
        # NOTE: autocorrect.adapters.macos/linux stay bundled — daemon/app.py imports them at
        # module level and they no-op on Windows via sys.platform guards.
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    icon=str(project_root / "packaging" / "autocorrect.ico"),
    version=str(project_root / "packaging" / "windows_version_info.txt"),
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
