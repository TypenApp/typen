"""
Tact — Unified Executable Entry Point.

This is the single `main()` compiled into the frozen `AutoCorrectDesktop.exe`
(PyInstaller one-folder / Nuitka standalone). One executable, two modes:

    AutoCorrectDesktop.exe                 -> background daemon + system tray
    AutoCorrectDesktop.exe --settings      -> out-of-process Settings UI (10 screens)

The daemon mode:
  1. Acquires a single-instance lock (`<data_dir>/daemon.lock`).
  2. Starts `AutoCorrectDaemon` (mmap lexicon, SQLite prefs, Local IPC server, OS hooks).
  3. Blocks on the system-tray event loop until the user chooses *Quit*.
  4. Releases all OS keyboard/mouse hooks and the lock on exit.

The settings mode delegates to `autocorrect.ui.settings_main.main`, which talks to the
running daemon over authenticated Local IPC (falling back to direct SQLite access when
the daemon is offline).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

from autocorrect import __version__
from autocorrect.platform_paths import default_data_dir, resolve_data_dir

APP_DISPLAY_NAME: Final[str] = "Tact"
# Maturity is a property of the platform build, not of the version: the Windows
# build has been verified end to end and ships as stable; macOS and Linux are
# still in public beta and say so in their version string and tray tooltip.
RELEASE_CHANNEL: Final[str] = "stable" if sys.platform == "win32" else "beta"
IS_BETA_BUILD: Final[bool] = RELEASE_CHANNEL != "stable"
#: "1.2.0" on stable builds, "1.2.0-beta" on beta builds.
VERSION_LABEL: Final[str] = __version__ if not IS_BETA_BUILD else f"{__version__}-{RELEASE_CHANNEL}"
#: "Tact" on stable builds, "Tact (beta)" on beta builds.
STATUS_PREFIX: Final[str] = (
    APP_DISPLAY_NAME if not IS_BETA_BUILD else f"{APP_DISPLAY_NAME} ({RELEASE_CHANNEL})"
)
DEFAULT_DATA_DIR: Final[Path] = default_data_dir()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="AutoCorrectDesktop",
        description=f"{APP_DISPLAY_NAME} {VERSION_LABEL}",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=(f"Directory for local SQLite preferences and the resource cache (default: {DEFAULT_DATA_DIR})"),
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the Settings & Customisation window instead of the background daemon",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Run the daemon in the foreground without a tray icon (Ctrl+C to stop)",
    )
    parser.add_argument(
        "--headless-check",
        action="store_true",
        help="Initialise every subsystem, print a status line, and exit (CI smoke test)",
    )
    parser.add_argument(
        "--ibus",
        action="store_true",
        help="Run as an IBus input-method engine (Linux/Wayland; normally spawned by ibus-daemon)",
    )
    parser.add_argument(
        "--ibus-standalone",
        action="store_true",
        help="Run the IBus engine and register its component on the fly (developer testing)",
    )
    parser.add_argument("--version", action="version", version=f"{APP_DISPLAY_NAME} {VERSION_LABEL}")
    return parser


def _run_settings(data_dir: Path) -> int:
    from autocorrect.ui.settings_main import main as settings_main

    return settings_main(["--data-dir", str(data_dir)])


def _run_headless_check(data_dir: Path) -> int:
    from autocorrect.daemon.app import AutoCorrectDaemon

    daemon = AutoCorrectDaemon(data_dir=data_dir, dry_run_hooks=True)
    try:
        snapshot = daemon.start(start_ipc=False)
        bundle = daemon.resource_manager.active_bundle
        print(
            f"{APP_DISPLAY_NAME} {VERSION_LABEL} OK | "
            f"resources={bundle.bundle_dir} (v{bundle.version}, schema {bundle.schema_version}) | "
            f"entitlement={snapshot.status_message}"
        )
    finally:
        daemon.stop()
    return 0


def _run_daemon(data_dir: Path, with_tray: bool) -> int:
    import time

    from autocorrect.daemon.app import AutoCorrectDaemon
    from autocorrect.daemon.single_instance import SingleInstanceGuard
    from autocorrect.daemon.tray import SystemTrayController

    data_dir.mkdir(parents=True, exist_ok=True)
    guard = SingleInstanceGuard(data_dir / "daemon.lock")
    if not guard.acquire():
        # Another daemon owns the hooks; the friendliest action is to open Settings.
        return _run_settings(data_dir)

    daemon = AutoCorrectDaemon(data_dir=data_dir, dry_run_hooks=False)
    try:
        snapshot = daemon.start()

        def status_label() -> str:
            hook = daemon.hook_status
            if not hook.is_active and hook.state.value in ("failed", "unsupported"):
                return f"{STATUS_PREFIX} — Not correcting: {hook.remediation or hook.detail}"
            prefix = "Paused" if daemon.session.is_paused else "Active"
            return f"{STATUS_PREFIX} — {prefix} · {snapshot.status_message}"

        def toggle_pause() -> bool:
            daemon.session.set_paused(not daemon.session.is_paused)
            return daemon.session.is_paused

        if not with_tray:
            print(f"{APP_DISPLAY_NAME} {VERSION_LABEL}: {snapshot.status_message}")
            hook = daemon.hook_status
            if hook.is_active:
                print(f"System-wide keyboard hook active ({hook.backend}). Press Ctrl+C to stop.")
            else:
                print(f"WARNING: typing assistance is NOT running ({hook.state.value}): {hook.detail}")
                if hook.remediation:
                    print(f"  -> {hook.remediation}")
                print("Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            return 0

        tray = SystemTrayController(
            on_toggle_pause=toggle_pause,
            on_quit=lambda: None,
            get_status_label=status_label,
            data_dir=data_dir,
            is_paused=lambda: daemon.session.is_paused,
        )
        try:
            tray.run_blocking()
        except Exception:
            # Tray backend unavailable (e.g. headless session): degrade to foreground loop.
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        daemon.stop()
        guard.release()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    if args.settings:
        return _run_settings(data_dir)
    if args.headless_check:
        return _run_headless_check(data_dir)
    if args.ibus or args.ibus_standalone:
        if not sys.platform.startswith("linux"):
            print("--ibus is only available on Linux", file=sys.stderr)
            return 2
        from autocorrect.adapters.linux.ibus_main import main as ibus_main

        return ibus_main(data_dir, standalone=args.ibus_standalone)
    return _run_daemon(data_dir, with_tray=not args.no_tray)


if __name__ == "__main__":
    raise SystemExit(main())
