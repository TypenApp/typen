"""
Single-Instance Daemon Lock.
Ensures only one instance of AutoCorrect monitors the system keyboard at any time.

Windows: a named mutex (`Local\\Typen-Daemon-<hash of data dir>`) is the real
guard; the kernel releases it the instant the owning process dies, so a crash
can never leave a stale lock. The PID file is kept purely so `--stop` and
Settings can find the daemon.

POSIX: PID file + `os.kill(pid, 0)` existence probe (signal 0 delivers nothing).
Never call `os.kill(pid, 0)` on Windows: there it means `CTRL_C_EVENT` and
either interrupts the console or raises, which made the old guard a no-op in
the frozen build and let several daemons (each with its own hooks) stack up.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any


def _mutex_name(lock_path: Path) -> str:
    # Not security-relevant: just a stable, short, path-derived kernel object name.
    digest = hashlib.sha256(str(lock_path.resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return f"Local\\Typen-Daemon-{digest}"


def is_pid_running(pid: int) -> bool:
    """Portable, side-effect-free process existence probe."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        from autocorrect.adapters.windows import win32_api as w32

        if w32.kernel32 is None:
            return False
        handle = w32.kernel32.OpenProcess(w32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED (5) means it exists but belongs to someone else.
            return w32.last_error() == 5
        try:
            import ctypes

            code = ctypes.c_ulong(0)
            if not w32.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == w32.STILL_ACTIVE
        finally:
            w32.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def terminate_pid(pid: int) -> bool:
    """Forcefully end a process (last-resort fallback for `--stop`)."""
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        from autocorrect.adapters.windows import win32_api as w32

        if w32.kernel32 is None:
            return False
        handle = w32.kernel32.OpenProcess(w32.PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(w32.kernel32.TerminateProcess(handle, 1))
        finally:
            w32.kernel32.CloseHandle(handle)
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


class SingleInstanceGuard:
    """
    Atomic lockfile / PID guard preventing duplicate background daemon instances.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._acquired = False
        self._mutex: Any = None

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def read_owner_pid(self) -> int | None:
        """PID recorded in the lock file, or None."""
        try:
            return int(self._lock_path.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    def owner_is_running(self) -> bool:
        pid = self.read_owner_pid()
        return pid is not None and pid != os.getpid() and is_pid_running(pid)

    def acquire(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32" and not self._acquire_windows_mutex():
            return False
        if sys.platform != "win32" and self._lock_path.exists() and self.owner_is_running():
            return False
        self._lock_path.write_text(str(os.getpid()), encoding="utf-8")
        self._acquired = True
        return True

    def _acquire_windows_mutex(self) -> bool:
        from autocorrect.adapters.windows import win32_api as w32

        if w32.kernel32 is None:  # pragma: no cover - sys.platform says win32 but no kernel32
            return True
        handle = w32.kernel32.CreateMutexW(None, True, _mutex_name(self._lock_path))
        err = w32.last_error()
        if not handle:
            # Could not even create the mutex: fall back to the PID probe rather than refuse to start.
            return not (self._lock_path.exists() and self.owner_is_running())
        if err == w32.ERROR_ALREADY_EXISTS:
            w32.kernel32.CloseHandle(handle)
            return False
        self._mutex = handle
        return True

    def release(self) -> None:
        if self._mutex is not None:
            from autocorrect.adapters.windows import win32_api as w32

            try:
                w32.kernel32.ReleaseMutex(self._mutex)
                w32.kernel32.CloseHandle(self._mutex)
            finally:
                self._mutex = None
        if self._acquired:
            self._lock_path.unlink(missing_ok=True)
            self._acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:  # backwards-compatible alias
        return is_pid_running(pid)
