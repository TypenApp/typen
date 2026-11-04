"""
File logging for the frozen, console-less desktop build.

`AutoCorrectDesktop.exe` is built with `console=False`, so without this every
traceback, hook failure and watchdog decision vanished. Logs go to
`<data_dir>/logs/typen.log` (rotating, 1 MB x 5) and, when a console exists,
to stderr as well. Unhandled exceptions on any thread are logged too.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from typing import Final

LOG_DIR_NAME: Final[str] = "logs"
LOG_FILE_NAME: Final[str] = "typen.log"
ENV_LOG_LEVEL: Final[str] = "TYPEN_LOG_LEVEL"
_configured_for: Path | None = None


def log_file_path(data_dir: Path) -> Path:
    return data_dir / LOG_DIR_NAME / LOG_FILE_NAME


def configure_logging(data_dir: Path, *, mode: str = "daemon", level: int | None = None) -> Path | None:
    """
    Idempotent. Returns the log file path (None if the directory is not writable).
    `mode` is recorded in every line so the daemon and the Settings process can
    share one file.
    """
    global _configured_for
    if level is None:
        name = os.environ.get(ENV_LOG_LEVEL, "INFO").upper()
        level = getattr(logging, name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(
        f"%(asctime)s %(levelname)-7s [{mode} %(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    path: Path | None = None
    if _configured_for != data_dir:
        try:
            log_dir = data_dir / LOG_DIR_NAME
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / LOG_FILE_NAME
            fh = logging.handlers.RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=5, encoding="utf-8", delay=True
            )
            fh.setFormatter(fmt)
            fh.setLevel(level)
            root.addHandler(fh)
            _configured_for = data_dir
        except OSError:
            path = None

    if sys.stderr is not None and not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers
    ):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(level)
        root.addHandler(sh)

    _install_excepthooks()
    return path if path is not None else (log_file_path(data_dir) if _configured_for == data_dir else None)


_hooks_installed = False


def _install_excepthooks() -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    log = logging.getLogger("autocorrect.unhandled")

    def _sys_hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical("unhandled exception on main thread", exc_info=(exc_type, exc, tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        log.critical(
            "unhandled exception on thread %s: %r",
            args.thread.name if args.thread else "?",
            args.exc_value,
            exc_info=args.exc_value if args.exc_value is not None else True,
        )

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook
