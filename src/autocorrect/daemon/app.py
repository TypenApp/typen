"""
Main Background Application Daemon (`AutoCorrectDaemon`).
Wires together:
- `ResourceManager` (zero-copy mmap language intelligence)
- `SQLitePreferenceStore` + `PreferenceMemoryOverlay`
- `AutocorrectEngine` (Layer 1 spelling, contextual confusion sets, punctuation, capitalisation)
- `EntitlementManager` (Typen is free software: every feature is always allowed)
- `InputSessionManager`, driven from exactly one thread by `InputDispatcher`
- OS Keyboard/Mouse Hook (`Win32KeyboardMouseHook` / `QuartzEventTapManager` / X11)
- `KillSwitch` (hold Esc 15 s) and the persistent safe-mode marker it writes
- Hook liveness/health: a hook thread that dies or keeps stalling is released
  and reported as FAILED instead of silently claiming "Active".
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from autocorrect.adapters import create_platform_focus_inspector, create_platform_injector
from autocorrect.adapters.linux.session_type import LinuxSessionType, detect_linux_session
from autocorrect.adapters.linux.x11_hook import X11HookError, X11KeyboardMouseHook
from autocorrect.adapters.macos.quartz_tap import QuartzEventTapManager, QuartzTapError
from autocorrect.adapters.windows.win32_hook import Win32HookError, Win32KeyboardMouseHook
from autocorrect.ai.api_key_manager import ApiKeyManager
from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.ai.provider_manager import BYOKProviderManager
from autocorrect.ai.spending_controls import SpendingController
from autocorrect.ai.usage_tracker import UsageTracker
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.daemon import hook_status
from autocorrect.daemon.focus_monitor import FocusMonitor
from autocorrect.daemon.hook_status import HookState, HookStatus
from autocorrect.daemon.input_dispatcher import InputDispatcher
from autocorrect.daemon.kill_switch import (
    PREF_KEY_ENABLED,
    PREF_KEY_HOLD_SECONDS,
    KillSwitch,
    clamp_hold_seconds,
    create_escape_probe,
)
from autocorrect.env_config import load_env_file
from autocorrect.input.hotkeys import Hotkey, parse_hotkey
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.ipc.server import LocalIPCServer
from autocorrect.licensing.entitlement_manager import EntitlementManager, EntitlementSnapshot
from autocorrect.licensing.root_key import load_root_public_key
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.productivity.app_profiles import ApplicationProfileManager
from autocorrect.productivity.local_insights import LocalInsightsStore
from autocorrect.productivity.snippet_engine import SnippetEngine
from autocorrect.updates.application_updater import ApplicationUpdater
from autocorrect.updates.language_resource_updater import LanguageResourceUpdater
from autocorrect.updates.model_updater import ModelUpdater
from autocorrect.version import APP_VERSION as APP_VERSION_STR

log = logging.getLogger(__name__)

SAFE_MODE_FILENAME: Final[str] = "safe_mode"
HOTKEY_ID_PAUSE: Final[int] = 1
HOTKEY_ID_SETTINGS: Final[int] = 2
SAFE_MODE_REMEDIATION: Final[str] = (
    "Typing assistance was switched off by the emergency stop (Esc held). "
    "Choose 'Resume typing assistance' in the tray menu, or run with --resume, to switch it back on."
)
DEGRADED_REMEDIATION: Final[str] = (
    "Typing assistance switched itself off because it was slowing down input. "
    "Choose 'Resume typing assistance' in the tray to try again; if it keeps happening, "
    "send logs/typen.log with a bug report."
)


class AutoCorrectDaemon:
    """
    Top-level background daemon lifecycle controller.
    """

    def __init__(
        self,
        data_dir: Path,
        bundled_resources_dir: Path = DEFAULT_BUNDLED_DIR,
        public_key: Ed25519PublicKey | None = None,
        dry_run_hooks: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._dry_run_hooks = dry_run_hooks
        # Development-only `.env` (ignored in frozen builds); never overrides real env vars.
        load_env_file()
        self._win_hook: Win32KeyboardMouseHook | None = None
        self._mac_tap: QuartzEventTapManager | None = None
        self._x11_hook: X11KeyboardMouseHook | None = None
        self._hooks_active: bool = False
        self._hook_lock = threading.RLock()
        self.hook_status: HookStatus = hook_status.INACTIVE
        # UI callbacks (set by the launcher/tray). All optional; invoked off the hook threads.
        self.on_state_changed: Callable[[], None] | None = None
        self.on_notify: Callable[[str, str], None] | None = None  # (title, message)
        self.on_open_settings_requested: Callable[[], None] | None = None
        self.on_quit_requested: Callable[[], None] | None = None

        # Embedded Ed25519 *public* root key that verifies signed updates, unless injected.
        self._public_key = public_key or load_root_public_key()

        # 1. Load zero-copy mmap language resources
        self.resource_manager = ResourceManager(
            bundled_dir=bundled_resources_dir,
            user_resources_dir=self._data_dir / "resources",
        )
        self.resource_manager.load_best_available()

        # 2. Load local preferences & custom vocabulary
        self.preference_store = SQLitePreferenceStore(self._data_dir / "preferences.sqlite3")

        # 3. Initialize core autocorrection engine
        self.engine = AutocorrectEngine(
            resource_manager=self.resource_manager,
            preferences=self.preference_store.overlay,
        )

        # 4. Initialize Pro productivity helpers
        self.snippet_engine = SnippetEngine()
        self.app_profiles = ApplicationProfileManager()
        self.insights = LocalInsightsStore(enabled=True)

        # 5. Entitlements: Typen is free software, so this always answers "allowed".
        self.entitlement_manager = EntitlementManager()

        # 6. Initialize Pro AI (Layer 2 Local AI & Layer 3 BYOK Cloud AI)
        self.local_ai = LocalModelManager(is_pro_entitled=True)
        self.api_key_manager = ApiKeyManager(use_memory_backend=dry_run_hooks)
        self.usage_tracker = UsageTracker(self._data_dir / "ai_usage.sqlite3")
        self.spending_controller = SpendingController(usage_tracker=self.usage_tracker)
        self.byok_manager = BYOKProviderManager(
            key_manager=self.api_key_manager,
            usage_tracker=self.usage_tracker,
            spending_controller=self.spending_controller,
            is_pro_entitled_fn=self.entitlement_manager.is_pro_enabled,
        )

        # 7. Initialize Independent Updaters
        self.resource_updater = LanguageResourceUpdater(
            resource_manager=self.resource_manager,
            user_resources_dir=self._data_dir / "resources",
            public_key=self._public_key,
        )
        self.app_updater = ApplicationUpdater(
            staging_dir=self._data_dir / "staging_app",
            public_key=self._public_key,
        )
        self.model_updater = ModelUpdater(
            models_dir=self._data_dir / "models",
            public_key=self._public_key,
        )

        # 8. Initialize OS Injector, Focus Inspector, and Session State Machine
        self.injector = create_platform_injector()
        self.focus_inspector = create_platform_focus_inspector()
        self.session = InputSessionManager(
            engine=self.engine,
            injector=self.injector if not dry_run_hooks else None,
            snippet_matcher=self.snippet_engine,
            entitlement_gate=self.entitlement_manager,
            active_region=self.preference_store.overlay.active_region,
        )

        # 9. Single worker thread that owns the session: hooks, mouse and focus all post to it.
        self.dispatcher = InputDispatcher(
            on_key_event=self._handle_key_on_worker,
            on_mouse_click=self.session.on_mouse_click_or_caret_move,
            on_focus_changed=self._on_focus_changed,
            on_overload=self._on_input_unhealthy,
        )

        # 10. Foreground-focus monitor: password fields, terminals, excluded apps, app profiles.
        self.focus_monitor = FocusMonitor(
            inspector=self.focus_inspector, on_change=self.dispatcher.post_focus
        )
        self._user_domain_packs: set[str] = set()

        # 11. Emergency stop: hold Esc; polled independently of the hooks.
        self.kill_switch = KillSwitch(
            create_escape_probe() if not dry_run_hooks else None,
            on_trigger=self.emergency_disable,
            hold_seconds=clamp_hold_seconds(self.preference_store.get_setting(PREF_KEY_HOLD_SECONDS, "15")),
        )

        # 12. Initialize Authenticated Local IPC Server for out-of-process Settings UI
        self.ipc_server = LocalIPCServer(daemon=self, data_dir=self._data_dir)

    @property
    def hooks_active(self) -> bool:
        return self._hooks_active

    @property
    def dry_run_hooks(self) -> bool:
        return self._dry_run_hooks

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    # ----------------------------------------------------------- safe mode

    @property
    def safe_mode_path(self) -> Path:
        return self._data_dir / SAFE_MODE_FILENAME

    @property
    def in_safe_mode(self) -> bool:
        return self.safe_mode_path.exists()

    def enter_safe_mode(self, reason: str) -> None:
        payload = {"reason": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "version": APP_VERSION_STR}
        try:
            self.safe_mode_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            log.exception("could not write safe-mode marker")

    def leave_safe_mode(self) -> None:
        try:
            self.safe_mode_path.unlink(missing_ok=True)
        except OSError:
            log.exception("could not remove safe-mode marker")

    # ------------------------------------------------------------ lifecycle

    def start(self, start_ipc: bool = True, attach_hooks: bool = True) -> EntitlementSnapshot:
        """
        Start the Local IPC server, dispatcher and kill switch, then (unless
        `attach_hooks=False`, in which case the launcher calls `attach_hooks()`
        once the tray is visible) the OS keyboard hooks.
        """
        snapshot = self.entitlement_manager.evaluate()
        self._snapshot = snapshot
        self.local_ai.set_pro_entitled(snapshot.pro_features_enabled)
        # Restore persisted correction preferences and (Pro) domain packs.
        self.apply_global_correction_settings()
        saved_packs = self.preference_store.get_setting("enabled_domain_packs", "")
        self.set_user_domain_packs({p for p in saved_packs.split(",") if p.strip()})
        if start_ipc:
            self.ipc_server.start()
        self.dispatcher.start()
        if self.preference_store.get_setting(PREF_KEY_ENABLED, "true") == "true":
            self.kill_switch.start()
        if attach_hooks:
            self.attach_hooks()
        return snapshot

    def attach_hooks(self) -> HookStatus:
        """Go live: honour safe mode / entitlement, otherwise install the platform hook."""
        snapshot = getattr(self, "_snapshot", None) or self.entitlement_manager.evaluate()
        if self.in_safe_mode:
            log.warning("safe mode active (%s): not attaching hooks", self.safe_mode_path)
            self.session.set_paused(True)
            self.hook_status = HookStatus(
                HookState.DISABLED,
                detail="safe-mode marker present",
                remediation=SAFE_MODE_REMEDIATION,
            )
        elif snapshot.typing_assistance_enabled:
            self._attach_os_hooks()
        else:
            self._release_os_hooks()
        return self.hook_status

    def stop(self) -> None:
        """Release all OS keyboard/mouse hooks, stop Local IPC server, and close mmap files."""
        self.kill_switch.stop()
        self._release_os_hooks()
        self.dispatcher.stop()
        self.ipc_server.stop()
        self.resource_manager.close()

    # ------------------------------------------------------- pause / resume

    def set_paused(self, paused: bool) -> bool:
        """
        Pause or resume typing assistance. Resuming also leaves safe mode and
        re-attaches hooks that were released by the kill switch or the health
        watchdog, so one tray action always brings the daemon back.
        """
        if paused:
            self.dispatcher.run_sync(lambda: self.session.set_paused(True))
        else:
            if self.in_safe_mode:
                self.leave_safe_mode()
            self.dispatcher.run_sync(lambda: self.session.set_paused(False))
            if not self._hooks_active and self.hook_status.state in (
                HookState.DISABLED,
                HookState.FAILED,
                HookState.INACTIVE,
            ):
                self.hook_status = hook_status.INACTIVE
                self._attach_os_hooks()
        self._notify_state_changed()
        return self.session.is_paused

    def toggle_pause(self) -> bool:
        return self.set_paused(not self.session.is_paused)

    def emergency_disable(self, reason: str = "emergency stop") -> None:
        """
        Kill switch / `--safe-mode`: release every OS hook, pause, and persist a
        safe-mode marker so the next start also comes up without hooks.
        """
        log.warning("EMERGENCY DISABLE: %s", reason)
        self.enter_safe_mode(reason)
        self._release_os_hooks()
        try:
            self.dispatcher.run_sync(lambda: self.session.set_paused(True))
        except Exception:
            self.session.set_paused(True)
        self.hook_status = HookStatus(HookState.DISABLED, detail=reason, remediation=SAFE_MODE_REMEDIATION)
        self._notify(
            "Typen typing assistance disabled",
            f"{reason}. Corrections are off until you choose 'Resume typing assistance' in the tray.",
        )
        self._notify_state_changed()

    def request_shutdown(self) -> None:
        """`--stop` / IPC `system.shutdown`: ask the owner (tray loop) to exit."""
        log.info("shutdown requested")
        if self.on_quit_requested is not None:
            threading.Thread(target=self.on_quit_requested, name="autocorrect-quit", daemon=True).start()

    def _notify(self, title: str, message: str) -> None:
        if self.on_notify is None:
            return
        try:
            self.on_notify(title, message)
        except Exception:
            log.exception("on_notify raised")

    def _notify_state_changed(self) -> None:
        if self.on_state_changed is None:
            return
        try:
            self.on_state_changed()
        except Exception:
            log.exception("on_state_changed raised")

    def health_snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "hook_status": self.hook_status.to_dict(),
            "hooks_active": self._hooks_active,
            "is_paused": self.session.is_paused,
            "dispatcher": self.dispatcher.stats.snapshot(),
            "dispatcher_queue_depth": self.dispatcher.queue_depth,
            "kill_switch": {
                "supported": self.kill_switch.is_supported,
                "running": self.kill_switch.is_running,
                "hold_seconds": self.kill_switch.hold_seconds,
            },
            "safe_mode": self.in_safe_mode,
        }
        if self._win_hook is not None:
            out["hook"] = self._win_hook.stats.snapshot()
        return out

    # ------------------------------------------------------------------ focus
    def set_user_domain_packs(self, pack_ids: set[str]) -> None:
        """Record the user's globally enabled packs and apply them (plus any app-profile packs)."""
        self._user_domain_packs = {p.strip().lower() for p in pack_ids if p.strip()}
        self._apply_effective_domain_packs(self.focus_monitor.last_focus)

    def _apply_effective_domain_packs(self, focus: FocusContext | None) -> None:
        packs = set(self._user_domain_packs)
        if focus is not None and self.entitlement_manager.is_pro_enabled():
            prof = self.app_profiles.get_profile(focus.process_name or focus.bundle_or_app_id)
            if prof is not None and prof.enabled:
                packs |= set(prof.active_domain_packs)
        if not self.entitlement_manager.is_pro_enabled():
            packs = set()  # Domain packs are a Pro feature.
        if packs != set(self.resource_manager.active_bundle.domain_packs.keys()):
            self.resource_manager.set_enabled_domain_packs(packs)

    def _on_focus_changed(self, focus: FocusContext) -> None:
        """
        Called by `FocusMonitor` whenever the foreground app/control changes.
        Flushes typing state, applies security flags, and (Pro) the matching
        application profile's correction settings and domain packs.
        """
        effective = focus
        prof = None
        if self.entitlement_manager.is_pro_enabled():
            prof = self.app_profiles.get_profile(focus.process_name or focus.bundle_or_app_id)
        if prof is not None and not prof.enabled:
            # A disabled profile means "never correct in this app".
            effective = FocusContext(
                process_name=focus.process_name,
                window_title=focus.window_title,
                bundle_or_app_id=focus.bundle_or_app_id,
                is_password_or_secure=focus.is_password_or_secure,
                is_terminal_or_code=focus.is_terminal_or_code,
                is_excluded_app=True,
            )
        self.session.on_focus_changed(effective)

        if prof is not None and prof.enabled:
            self.session.configure_features(
                enable_punctuation_assist=prof.enable_punctuation_assist,
                enable_double_space_period=prof.enable_double_space_period,
                enable_auto_capitalise=prof.enable_auto_capitalise,
                aggressiveness=prof.aggressiveness,
            )
        else:
            self.apply_global_correction_settings()
        self._apply_effective_domain_packs(focus)

    def apply_global_correction_settings(self) -> None:
        """Push the user's global (non-profile) correction preferences into the session."""
        prefs = self.preference_store
        self.session.configure_features(
            enable_punctuation_assist=prefs.get_setting("enable_punctuation_assist", "true") == "true",
            enable_double_space_period=prefs.get_setting("enable_double_space_period", "true") == "true",
            enable_auto_capitalise=prefs.get_setting("enable_auto_capitalise", "true") == "true",
            aggressiveness=max(0.5, min(1.5, float(prefs.get_setting("aggressiveness", "1.0")))),
        )

    # ------------------------------------------------------------- hotkeys

    def configured_hotkeys(self) -> dict[int, Hotkey]:
        """Global hotkeys from preferences, keyed by the id the OS hook reports back."""
        prefs = self.preference_store
        out: dict[int, Hotkey] = {}
        pause = parse_hotkey(prefs.get_setting("pause_hotkey", "Ctrl+Alt+P"))
        if pause is not None:
            out[HOTKEY_ID_PAUSE] = pause
        settings = parse_hotkey(prefs.get_setting("settings_hotkey", "Ctrl+Alt+,"))
        if settings is not None:
            out[HOTKEY_ID_SETTINGS] = settings
        return out

    def _on_hotkey(self, hotkey_id: int) -> None:
        # Called on the hook thread: hand off immediately.
        if hotkey_id == HOTKEY_ID_PAUSE:
            threading.Thread(target=self.toggle_pause, name="autocorrect-hotkey-pause", daemon=True).start()
        elif hotkey_id == HOTKEY_ID_SETTINGS and self.on_open_settings_requested is not None:
            threading.Thread(
                target=self.on_open_settings_requested, name="autocorrect-hotkey-settings", daemon=True
            ).start()

    def reload_hotkeys(self) -> None:
        """Re-register hotkeys after Settings changed them (Windows re-creates the hook thread)."""
        if self._hooks_active and self._win_hook is not None:
            with self._hook_lock:
                self._release_os_hooks()
                self._attach_os_hooks()
            self._notify_state_changed()

    # ------------------------------------------------------- hook lifecycle

    def _attach_os_hooks(self) -> None:
        with self._hook_lock:
            if self._hooks_active:
                return
            self._hooks_active = True
            if self._dry_run_hooks:
                self.hook_status = HookStatus(HookState.DRY_RUN, backend="dry-run")
                return
            self.focus_monitor.start()
            try:
                self.hook_status = self._install_platform_hook()
            except Exception as exc:  # pragma: no cover - defensive: never take the daemon down
                log.exception("hook installation raised")
                self.hook_status = HookStatus(
                    HookState.FAILED,
                    detail=f"{type(exc).__name__}: {exc}",
                    remediation="Restart Typen. If the problem persists, send logs/typen.log with a bug report.",
                )
            if self.hook_status.state in (HookState.FAILED, HookState.UNSUPPORTED):
                # Nothing is listening; keep the daemon (IPC, settings) alive
                # but do not pretend typing assistance is running.
                self._hooks_active = False
                self.focus_monitor.stop()
                log.warning("hook not active: %s / %s", self.hook_status.state.value, self.hook_status.detail)
            else:
                log.info("hook active: %s", self.hook_status.backend)

    def _on_hook_thread_exit(self, exc: BaseException | None) -> None:
        """A hook thread ended. If we did not ask for it, degrade to FAILED instead of lying."""
        with self._hook_lock:
            if not self._hooks_active:
                return  # deliberate stop() in progress
            detail = f"hook thread exited: {exc!r}" if exc else "hook thread exited unexpectedly"
            log.error(detail)
            self._hooks_active = False
            self.focus_monitor.stop()
            self._win_hook = None
            self._mac_tap = None
            self._x11_hook = None
            self.hook_status = HookStatus(
                HookState.FAILED,
                backend=self.hook_status.backend,
                detail=detail,
                remediation="Choose 'Resume typing assistance' in the tray to reinstall the hook.",
            )
        self._notify_state_changed()

    def _on_input_unhealthy(self, reason: str) -> None:
        """Hook/dispatcher watchdog: input is being slowed down. Release the hooks, keep the daemon."""

        def _degrade() -> None:
            with self._hook_lock:
                if not self._hooks_active:
                    return
                self._release_os_hooks()
                self.hook_status = HookStatus(
                    HookState.FAILED, detail=reason, remediation=DEGRADED_REMEDIATION
                )
            self._notify("Typen paused itself", f"{reason}. Resume from the tray when ready.")
            self._notify_state_changed()

        # Never unhook from a hook or worker thread.
        threading.Thread(target=_degrade, name="autocorrect-degrade", daemon=True).start()

    def _install_platform_hook(self) -> HookStatus:
        """Install the right hook for this OS/session; return its status (never raises for known failures)."""
        if sys.platform == "win32":
            self._win_hook = Win32KeyboardMouseHook(
                on_key_event=self._dispatch_os_key,
                on_mouse_click=self.dispatcher.post_mouse_click,
                hotkeys=self.configured_hotkeys(),
                on_hotkey=self._on_hotkey,
                on_thread_exit=self._on_hook_thread_exit,
                on_unhealthy=self._on_input_unhealthy,
            )
            try:
                self._win_hook.start()
            except Win32HookError as exc:
                self._win_hook = None
                return HookStatus(
                    HookState.FAILED,
                    backend="win32-ll-hook",
                    detail=str(exc),
                    remediation=exc.remediation,
                )
            return HookStatus(HookState.ACTIVE, backend="win32-ll-hook")

        if sys.platform == "darwin":
            self._mac_tap = QuartzEventTapManager(
                on_key_event=self._dispatch_os_key,
                on_mouse_click=self.dispatcher.post_mouse_click,
                on_thread_exit=self._on_hook_thread_exit,
            )
            try:
                self._mac_tap.start()
            except QuartzTapError as exc:
                self._mac_tap = None
                return HookStatus(
                    HookState.FAILED,
                    backend="quartz-event-tap",
                    detail=str(exc),
                    remediation=exc.remediation,
                )
            return HookStatus(HookState.ACTIVE, backend="quartz-event-tap")

        if sys.platform.startswith("linux"):
            session_type = detect_linux_session()
            if session_type == LinuxSessionType.WAYLAND:
                return HookStatus(
                    HookState.UNSUPPORTED,
                    backend="ibus",
                    detail="Wayland session: compositors do not allow global key hooks.",
                    remediation=(
                        "Enable the AutoCorrect IBus input method "
                        "(Settings → Keyboard → Input Sources → add 'English (Typen)') "
                        "and select it as your active input source."
                    ),
                )
            if session_type == LinuxSessionType.HEADLESS:
                return HookStatus(
                    HookState.UNSUPPORTED,
                    detail="No DISPLAY/WAYLAND_DISPLAY in the environment.",
                    remediation="Start AutoCorrect from inside a graphical desktop session.",
                )
            self._x11_hook = X11KeyboardMouseHook(
                on_key_event=self._dispatch_os_key_passive,
                on_mouse_click=self.dispatcher.post_mouse_click,
                on_thread_exit=self._on_hook_thread_exit,
            )
            try:
                self._x11_hook.start()
            except X11HookError as exc:
                self._x11_hook = None
                return HookStatus(
                    HookState.FAILED,
                    backend="x11-xrecord",
                    detail=str(exc),
                    remediation=exc.remediation,
                )
            return HookStatus(HookState.ACTIVE, backend="x11-xrecord")

        return HookStatus(
            HookState.UNSUPPORTED,
            detail=f"No input hook for platform {sys.platform!r}.",
            remediation="AutoCorrect supports Windows, macOS and Linux desktops.",
        )

    def _release_os_hooks(self) -> None:
        with self._hook_lock:
            self._hooks_active = False
            self.hook_status = hook_status.INACTIVE
            self.focus_monitor.stop()
            win, mac, x11 = self._win_hook, self._mac_tap, self._x11_hook
            self._win_hook = self._mac_tap = self._x11_hook = None
        # Stop outside the lock: stop() joins the hook thread, which may be inside _on_hook_thread_exit.
        for hook in (win, mac, x11):
            if hook is not None:
                try:
                    hook.stop()
                except Exception:
                    log.exception("hook stop raised")

    # ------------------------------------------------------------ dispatch

    def _dispatch_os_key(self, event: KeyEvent) -> KeyAction:
        """
        Called on the OS hook thread. Never evaluates anything there: the event
        is queued for the dispatcher worker and the keystroke is passed through.
        Corrections therefore run in *passive* mode on every platform (the
        delimiter has already been delivered and is deleted and re-typed by the
        replacement plan), exactly as X11 always has.
        """
        self.dispatcher.post_key(event)
        return KeyAction.PASS_THROUGH

    # XRecord was always passive; it now shares the exact same path.
    _dispatch_os_key_passive = _dispatch_os_key

    def _handle_key_on_worker(self, event: KeyEvent) -> None:
        self.session.handle_key_event(event, suppress_delimiter_on_replace=False)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(description="AutoCorrect System-Wide Desktop Background Daemon")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory for local SQLite preferences and the resource cache",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attach live OS keyboard/mouse hooks and run continuously until Ctrl+C",
    )
    args = parser.parse_args(argv)

    from autocorrect.platform_paths import resolve_data_dir

    daemon = AutoCorrectDaemon(
        data_dir=resolve_data_dir(args.data_dir),
        dry_run_hooks=not args.live,
    )
    snap = daemon.start()
    print(f"AutoCorrect Daemon initialized: {snap.status_message}")
    if not args.live:
        daemon.stop()
        return 0

    print("System-wide keyboard hooks ACTIVE. Type in any app (Notepad, Chrome, Word).")
    print("Press Ctrl+C in this terminal at any time to unhook and stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping AutoCorrect Daemon and releasing OS keyboard hooks...")
    finally:
        daemon.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
