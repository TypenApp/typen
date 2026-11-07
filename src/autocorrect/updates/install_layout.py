"""
Detect how this Typen binary was installed so the updater can pick the right
artifact (Inno setup vs zip vs AppImage vs deb vs tar.gz).
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path


class InstallLayout(str, Enum):
    WINDOWS_INSTALLED = "windows_installed"
    WINDOWS_PORTABLE = "windows_portable"
    MACOS_APP = "macos_app"
    LINUX_APPIMAGE = "linux_appimage"
    LINUX_DEB = "linux_deb"
    LINUX_PORTABLE = "linux_portable"
    UNKNOWN = "unknown"


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    """Map the running OS/arch to a release-manifest platforms key."""
    import platform as plat

    sysname = (system or sys.platform).lower()
    mach = (machine or plat.machine()).lower()
    if sysname.startswith("win"):
        return "win64"
    if sysname == "darwin":
        return "macos-arm64" if mach in ("arm64", "aarch64") else "macos-x64"
    if mach in ("aarch64", "arm64"):
        return "linux-aarch64"
    return "linux-x86_64"


def preferred_artifact_kind(layout: InstallLayout) -> str:
    return {
        InstallLayout.WINDOWS_INSTALLED: "installer",
        InstallLayout.WINDOWS_PORTABLE: "portable",
        InstallLayout.MACOS_APP: "portable",
        InstallLayout.LINUX_APPIMAGE: "appimage",
        InstallLayout.LINUX_DEB: "deb",
        InstallLayout.LINUX_PORTABLE: "portable",
        InstallLayout.UNKNOWN: "portable",
    }[layout]


def detect_install_layout(executable: Path | None = None) -> InstallLayout:
    exe = (executable or Path(sys.executable)).resolve()
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            programs = Path(local) / "Programs"
            try:
                exe.relative_to(programs)
                return InstallLayout.WINDOWS_INSTALLED
            except ValueError:
                pass
        return InstallLayout.WINDOWS_PORTABLE if getattr(sys, "frozen", False) else InstallLayout.UNKNOWN

    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return InstallLayout.MACOS_APP
        return InstallLayout.UNKNOWN

    appimage = os.environ.get("APPIMAGE", "").strip()
    if appimage:
        return InstallLayout.LINUX_APPIMAGE
    # .deb installs typically land under /usr or /usr/local.
    try:
        if str(exe).startswith(("/usr/bin", "/usr/local/bin", "/opt/")):
            return InstallLayout.LINUX_DEB
    except Exception:
        pass
    return InstallLayout.LINUX_PORTABLE if getattr(sys, "frozen", False) else InstallLayout.UNKNOWN


def install_root(layout: InstallLayout, executable: Path | None = None) -> Path:
    """Directory (or .app / AppImage path) that an archive replace should target."""
    exe = (executable or Path(sys.executable)).resolve()
    if layout == InstallLayout.MACOS_APP:
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
    if layout == InstallLayout.LINUX_APPIMAGE:
        return Path(os.environ["APPIMAGE"]).resolve()
    if layout in (InstallLayout.WINDOWS_INSTALLED, InstallLayout.WINDOWS_PORTABLE, InstallLayout.LINUX_PORTABLE):
        # PyInstaller one-folder: exe lives in the bundle root.
        return exe.parent
    if layout == InstallLayout.LINUX_DEB:
        return exe
    return exe.parent
