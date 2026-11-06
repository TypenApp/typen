"""
Per-platform user data directory for preferences,
resource cache and IPC endpoint files.

- Windows : `~/.autocorrect_desktop` (unchanged — the shipping beta uses it and
            the Inno uninstaller references it)
- macOS   : `~/Library/Application Support/AutoCorrect`
- Linux   : `$XDG_DATA_HOME/autocorrect` (default `~/.local/share/autocorrect`)

A pre-existing legacy `~/.autocorrect_desktop` on macOS/Linux is migrated
(moved) into the platform directory the first time it is resolved, so a user
who ran a source checkout earlier keeps their custom words and settings.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

LEGACY_DIR_NAME: Final[str] = ".autocorrect_desktop"
DATA_DIR_ENV_VAR: Final[str] = "AUTOCORRECT_DATA_DIR"


def legacy_data_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / LEGACY_DIR_NAME


def default_data_dir(
    platform: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Platform-conventional data directory (no filesystem side effects)."""
    plat = platform or sys.platform
    h = home or Path.home()
    e = os.environ if env is None else env
    override = e.get(DATA_DIR_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    if plat == "win32":
        return legacy_data_dir(h)
    if plat == "darwin":
        return h / "Library" / "Application Support" / "AutoCorrect"
    xdg = e.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else h / ".local" / "share"
    return base / "autocorrect"


def resolve_data_dir(
    explicit: Path | None = None,
    *,
    platform: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """
    Return the data directory to use, creating it and migrating a legacy
    `~/.autocorrect_desktop` on macOS/Linux when the new location is still empty.
    An explicit `--data-dir` is always honoured verbatim.
    """
    if explicit is not None:
        explicit.mkdir(parents=True, exist_ok=True)
        return explicit
    target = default_data_dir(platform=platform, home=home, env=env)
    legacy = legacy_data_dir(home)
    if target != legacy and legacy.is_dir() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy.rename(target)
        except OSError:
            # Cross-device (e.g. XDG_DATA_HOME on another mount): copy then leave
            # the legacy tree in place rather than risk losing user data.
            shutil.copytree(legacy, target)
    target.mkdir(parents=True, exist_ok=True)
    return target
