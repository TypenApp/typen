"""
Typen — Unified Executable Entry Point.

This is the single `main()` compiled into the frozen `AutoCorrectDesktop.exe`
(PyInstaller one-folder / Nuitka standalone). One executable, two modes:

    AutoCorrectDesktop.exe                 -> background daemon + system tray
    AutoCorrectDesktop.exe --settings      -> out-of-process Settings UI (10 screens)
    AutoCorrectDesktop.exe --stop          -> ask the running daemon to quit
    AutoCorrectDesktop.exe --safe-mode     -> start with typing assistance switched off
    AutoCorrectDesktop.exe --resume        -> clear safe mode and start normally

The daemon mode:
  1. Configures file logging (`<data_dir>/logs/typen.log`).
  2. Acquires a single-instance lock (named mutex on Windows + `<data_dir>/daemon.lock`).
  3. Starts `AutoCorrectDaemon` (mmap lexicon, SQLite prefs, Local IPC server, kill switch).
  4. Shows the system-tray icon FIRST, then attaches the OS hooks from the tray's
     ready callback, so the user always has a menu before any hook is live.
  5. Blocks on the tray event loop until the user chooses *Quit* (or `--stop` asks).
  6. Releases all OS keyboard/mouse hooks and the lock on exit.

The settings mode delegates to `autocorrect.ui.settings_main.main`, which talks to the
running daemon over authenticated Local IPC (falling back to direct SQLite access when
the daemon is offline).
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path
from typing import Final

from autocorrect import __version__
from autocorrect.platform_paths import default_data_dir, resolve_data_dir

log = logging.getLogger(__name__)

APP_DISPLAY_NAME: Final[str] = "Typen"
# Maturity is a property of the platform build, not of the version: the Windows
# build has been verified end to end and ships as stable; macOS and Linux are
# still in public beta and say so in their version string and tray tooltip.
RELEASE_CHANNEL: Final[str] = "stable" if sys.platform == "win32" else "beta"
IS_BETA_BUILD: Final[bool] = RELEASE_CHANNEL != "stable"
#: "1.2.0" on stable builds, "1.2.0-beta" on beta builds.
VERSION_LABEL: Final[str] = __version__ if not IS_BETA_BUILD else f"{__version__}-{RELEASE_CHANNEL}"
#: "Typen" on stable builds, "Typen (beta)" on beta builds.
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
        "--stop",
        action="store_true",
        help="Ask the running background daemon to quit (releases all keyboard hooks) and exit",
    )
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="Start with typing assistance switched off (no keyboard hooks) until you resume from the tray",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Clear a previous emergency stop / safe mode and start normally",
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


def _run_stop(data_dir: Path) -> int:
    """`--stop`: ask the daemon over IPC to quit; fall back to terminating the PID from the lock file."""
    import time

    from autocorrect.daemon.single_instance import SingleInstanceGuard, is_pid_running, terminate_pid
    from autocorrect.ipc.client import LocalIPCClient

    guard = SingleInstanceGuard(data_dir / "daemon.lock")
    pid = guard.read_owner_pid()
    if pid is None or not is_pid_running(pid):
        print(f"{APP_DISPLAY_NAME}: no running daemon found.")
        return 0
    try:
        LocalIPCClient(data_dir).call("system.shutdown", {}, retries=1)
        for _ in range(40):  # up to ~10 s for a clean exit
            if not is_pid_running(pid):
                print(f"{APP_DISPLAY_NAME}: daemon (pid {pid}) stopped.")
                return 0
            time.sleep(0.25)
    except Exception as exc:
        log.warning("IPC shutdown failed (%s); terminating pid %d", exc, pid)
    if terminate_pid(pid):
        print(f"{APP_DISPLAY_NAME}: daemon (pid {pid}) terminated.")
        return 0
    print(f"{APP_DISPLAY_NAME}: could not stop daemon (pid {pid}).", file=sys.stderr)
    return 1


def _run_daemon(data_dir: Path, with_tray: bool, *, safe_mode: bool = False, resume: bool = False) -> int:
    from autocorrect.daemon.app import AutoCorrectDaemon
    from autocorrect.daemon.single_instance import SingleInstanceGuard
    from autocorrect.daemon.tray import SystemTrayController

    data_dir.mkdir(parents=True, exist_ok=True)
    guard = SingleInstanceGuard(data_dir / "daemon.lock")
    if not guard.acquire():
        # Another daemon owns the hooks; the friendliest action is to open Settings.
        log.info("daemon already running (pid %s); opening Settings instead", guard.read_owner_pid())
        return _run_settings(data_dir)

    log.info("%s %s starting (data_dir=%s, tray=%s)", APP_DISPLAY_NAME, VERSION_LABEL, data_dir, with_tray)
    daemon = AutoCorrectDaemon(data_dir=data_dir, dry_run_hooks=False)
    if resume:
        daemon.leave_safe_mode()
    if safe_mode:
        daemon.enter_safe_mode("--safe-mode")
    quit_event = threading.Event()
    try:
        # Everything except the OS hooks: IPC, dispatcher, kill switch. Hooks are
        # attached later, once the user has a tray menu (or immediately when --no-tray).
        snapshot = daemon.start(attach_hooks=not with_tray)

        def status_label() -> str:
            hook = daemon.hook_status
            if hook.needs_attention:
                return f"{STATUS_PREFIX} — Not correcting: {hook.remediation or hook.detail}"
            prefix = "Paused" if daemon.session.is_paused else "Active"
            return f"{STATUS_PREFIX} — {prefix} · {snapshot.status_message}"

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
            if daemon.kill_switch.is_supported:
                print(f"Emergency stop: hold Esc for {daemon.kill_switch.hold_seconds:.0f} s.")
            daemon.on_quit_requested = quit_event.set
            try:
                while not quit_event.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
            return 0

        tray = SystemTrayController(
            on_toggle_pause=daemon.toggle_pause,
            on_quit=lambda: None,
            get_status_label=status_label,
            data_dir=data_dir,
            is_paused=lambda: daemon.session.is_paused,
            needs_attention=lambda: daemon.hook_status.needs_attention,
        )
        daemon.on_state_changed = tray.refresh
        daemon.on_notify = tray.notify

        def open_settings() -> None:
            tray.launch_settings_subprocess()

        daemon.on_open_settings_requested = open_settings
        daemon.on_quit_requested = tray.stop

        def on_tray_ready() -> None:
            # The user can now reach Pause/Quit: it is safe to go live.
            daemon.attach_hooks()
            tray.refresh()
            _first_run(daemon, tray)

        try:
            tray.run_blocking(on_ready=on_tray_ready)
        except Exception:
            # Tray backend unavailable (no AppIndicator on GNOME, headless session...).
            log.exception("tray unavailable; running without a menu (kill switch and --stop still work)")
            daemon.attach_hooks()
            daemon.on_quit_requested = quit_event.set
            try:
                while not quit_event.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        log.info("shutting down")
        daemon.stop()
        guard.release()


def _first_run(daemon: object, tray: object) -> None:
    """Open Settings and say hello the first time the daemon ever runs on this machine."""
    from autocorrect.daemon.app import AutoCorrectDaemon
    from autocorrect.daemon.tray import SystemTrayController

    assert isinstance(daemon, AutoCorrectDaemon) and isinstance(tray, SystemTrayController)
    prefs = daemon.preference_store
    if prefs.get_setting("first_run_done", "false") == "true":
        return
    prefs.set_setting("first_run_done", "true")
    log.info("first run: opening Settings")
    tray.notify(
        f"{APP_DISPLAY_NAME} is running",
        "Look for the Aa icon in the system tray. Right-click it to pause, open Settings or quit. "
        f"Emergency stop: hold Esc for {daemon.kill_switch.hold_seconds:.0f} seconds.",
    )
    tray.launch_settings_subprocess()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    from autocorrect.logging_setup import configure_logging

    mode = "settings" if args.settings else ("check" if args.headless_check else "daemon")
    configure_logging(data_dir, mode=mode)
    if args.settings:
        return _run_settings(data_dir)
    if args.headless_check:
        return _run_headless_check(data_dir)
    if args.stop:
        return _run_stop(data_dir)
    if args.ibus or args.ibus_standalone:
        if not sys.platform.startswith("linux"):
            print("--ibus is only available on Linux", file=sys.stderr)
            return 2
        from autocorrect.adapters.linux.ibus_main import main as ibus_main

        return ibus_main(data_dir, standalone=args.ibus_standalone)
    return _run_daemon(data_dir, with_tray=not args.no_tray, safe_mode=args.safe_mode, resume=args.resume)


if __name__ == "__main__":
    raise SystemExit(main())
