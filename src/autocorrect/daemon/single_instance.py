"""
Single-Instance Daemon Lock.
Ensures only one instance of AutoCorrect monitors the system keyboard at any time.
"""

from __future__ import annotations

import os
from pathlib import Path


class SingleInstanceGuard:
    """
    Atomic lockfile / PID guard preventing duplicate background daemon instances.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._acquired = False

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._lock_path.exists():
            try:
                old_pid = int(self._lock_path.read_text(encoding="utf-8").strip())
                if old_pid != os.getpid() and self._is_pid_running(old_pid):
                    return False
            except Exception:
                pass
        self._lock_path.write_text(str(os.getpid()), encoding="utf-8")
        self._acquired = True
        return True

    def release(self) -> None:
        if self._acquired:
            self._lock_path.unlink(missing_ok=True)
            self._acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
