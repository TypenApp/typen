"""
Detached apply helpers: after the daemon exits, replace the install and relaunch.

Windows Inno: silent setup with /UPDATEDBYAPP=1 (installer relaunches Typen).
Archives / AppImage / deb: a short helper script waits for our PID, swaps files, relaunches.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from autocorrect.updates.install_layout import InstallLayout, install_root


def spawn_apply(
    *,
    layout: InstallLayout,
    package_path: Path,
    current_pid: int,
    executable: Path | None = None,
) -> None:
    """Start a detached process that applies `package_path` after `current_pid` exits."""
    exe = (executable or Path(sys.executable)).resolve()
    root = install_root(layout, exe)
    if layout == InstallLayout.WINDOWS_INSTALLED:
        _spawn_windows_installer(package_path)
        return
    if layout == InstallLayout.LINUX_DEB:
        _spawn_linux_deb(package_path, relaunch=str(exe))
        return
    if sys.platform.startswith("win"):
        script = _write_windows_archive_helper(package_path, root, exe, current_pid)
        _detach(["cmd.exe", "/c", str(script)])
        return
    script = _write_posix_helper(layout, package_path, root, exe, current_pid)
    _detach(["/bin/bash", str(script)])


def windows_installer_command(setup_exe: Path) -> list[str]:
    return [
        str(setup_exe),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/UPDATEDBYAPP=1",
    ]


def _spawn_windows_installer(setup_exe: Path) -> None:
    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen(  # noqa: S603
        windows_installer_command(setup_exe),
        close_fds=True,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_linux_deb(deb_path: Path, *, relaunch: str) -> None:
    script = Path(tempfile.gettempdir()) / f"typen-apply-deb-{os.getpid()}.sh"
    script.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                f'pkexec dpkg -i "{deb_path}"',
                f'nohup "{relaunch}" >/dev/null 2>&1 &',
                f'rm -f "{script}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    _detach(["/bin/bash", str(script)])


def _write_windows_archive_helper(package: Path, root: Path, exe: Path, pid: int) -> Path:
    script = Path(tempfile.gettempdir()) / f"typen-apply-{pid}.cmd"
    # Expand zip into a temp dir then robocopy over the install root.
    lines = [
        "@echo off",
        f":wait\n tasklist /FI \"PID eq {pid}\" | find \"{pid}\" >nul && (timeout /t 1 /nobreak >nul & goto wait)",
        f'set "SRC={package}"',
        f'set "DST={root}"',
        f'set "TMP=%TEMP%\\typen-update-{pid}"',
        "rmdir /s /q \"%TMP%\" 2>nul",
        "mkdir \"%TMP%\"",
        "powershell -NoProfile -Command \"Expand-Archive -LiteralPath $env:SRC -DestinationPath $env:TMP -Force\"",
        "robocopy \"%TMP%\" \"%DST%\" /E /IS /IT /NFL /NDL /NJH /NJS /nc /ns /np >nul",
        "rmdir /s /q \"%TMP%\" 2>nul",
        f'start \"\" \"{exe}\"',
        f'del \"%~f0\"',
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return script


def _write_posix_helper(
    layout: InstallLayout,
    package: Path,
    root: Path,
    exe: Path,
    pid: int,
) -> Path:
    script = Path(tempfile.gettempdir()) / f"typen-apply-{pid}.sh"
    if layout == InstallLayout.LINUX_APPIMAGE:
        body = [
            f'while kill -0 {pid} 2>/dev/null; do sleep 0.5; done',
            f'chmod +x "{package}"',
            f'mv -f "{package}" "{root}"',
            f'nohup "{root}" >/dev/null 2>&1 &',
        ]
    elif layout == InstallLayout.MACOS_APP:
        # Zip contains Typen.app (or a folder with it).
        body = [
            f'while kill -0 {pid} 2>/dev/null; do sleep 0.5; done',
            f'TMP=$(mktemp -d)',
            f'unzip -qo "{package}" -d "$TMP"',
            f'APP=$(find "$TMP" -maxdepth 2 -name "*.app" -type d | head -n 1)',
            f'if [ -z "$APP" ]; then echo "no .app in archive"; exit 1; fi',
            f'rm -rf "{root}"',
            f'mv "$APP" "{root}"',
            f'rm -rf "$TMP"',
            f'open "{root}"',
        ]
    else:
        # Portable tar.gz / zip extract over root.
        body = [
            f'while kill -0 {pid} 2>/dev/null; do sleep 0.5; done',
            f'TMP=$(mktemp -d)',
            f'case "{package}" in',
            f'  *.tar.gz|*.tgz) tar -xzf "{package}" -C "$TMP" ;;',
            f'  *) unzip -qo "{package}" -d "$TMP" ;;',
            f'esac',
            f'INNER=$(find "$TMP" -mindepth 1 -maxdepth 1 | head -n 1)',
            f'if [ -d "$INNER" ]; then SRC="$INNER"; else SRC="$TMP"; fi',
            f'rsync -a --delete "$SRC"/ "{root}"/ 2>/dev/null || cp -R "$SRC"/. "{root}"/',
            f'rm -rf "$TMP"',
            f'nohup "{exe}" >/dev/null 2>&1 &',
        ]
    script.write_text(
        "#!/bin/bash\nset -euo pipefail\n" + "\n".join(body) + f'\nrm -f "{script}"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _detach(argv: list[str]) -> None:
    kwargs: dict = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }
    if sys.platform.startswith("win"):
        kwargs.pop("start_new_session", None)
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        kwargs["creationflags"] = flags
    subprocess.Popen(argv, **kwargs)  # noqa: S603
