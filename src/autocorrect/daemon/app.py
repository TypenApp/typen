"""
Main Background Application Daemon (`AutoCorrectDaemon`).
Wires together:
- `ResourceManager` (zero-copy mmap language intelligence)
- `SQLitePreferenceStore` + `PreferenceMemoryOverlay`
- `AutocorrectEngine` (Layer 1 spelling, contextual confusion sets, punctuation, capitalisation)
- `EntitlementManager` (Typen is free software: every feature is always allowed)
- `InputSessionManager`, driven from exactly one thread by `InputDispatcher`
- OS Keyboard/Mouse Hook (`Win32KeyboardMouseHook` / `QuartzEventTapManager` / X11)
- `KillSwitch` (hold Esc 10 s toggles pause/resume) and the persistent safe-mode marker
- Hook liveness/health: a hook thread that dies or keeps stalling is released
  and reported as FAILED instead of silently claiming "Active".
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from autocorrect.adapters import create_platform_focus_inspector, create_platform_injector
from autocorrect.adapters.linux.session_type import LinuxSessionType, detect_linux_session
from autocorrect.adapters.linux.x11_hook import X11HookError, X11KeyboardMouseHook
from autocorrect.adapters.macos.quartz_tap import QuartzEventTapManager, QuartzTapError
from autocorrect.adapters.windows.caret_probe import create_caret_probe
from autocorrect.adapters.windows.win32_hook import Win32HookError, Win32KeyboardMouseHook
from autocorrect.ai.api_key_manager import ApiKeyManager
from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.ai.provider_manager import BYOKProviderManager
from autocorrect.ai.spending_controls import SpendingController
from autocorrect.ai.usage_tracker import UsageTracker
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import CorrectionFeatures, CorrectionReason
from autocorrect.daemon import hook_status
from autocorrect.daemon.focus_monitor import FocusMonitor
from autocorrect.daemon.hook_status import HookState, HookStatus
from autocorrect.daemon.input_dispatcher import InputDispatcher
from autocorrect.daemon.kill_switch import KillSwitch, create_escape_probe, migrate_hold_seconds
from autocorrect.env_config import load_env_file
from autocorrect.input.diff_planner import ReplacementPlan
from autocorrect.input.hotkeys import Hotkey, parse_hotkey
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager, SessionEventOutcome
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.intelligence.schema import RegionFlag
from autocorrect.ipc.server import LocalIPCServer
from autocorrect.licensing.entitlement_manager import EntitlementManager, EntitlementSnapshot
from autocorrect.licensing.root_key import load_root_public_key
from autocorrect.preferences import settings_schema
from autocorrect.preferences.sqlite_store import REGION_NAME_TO_FLAG, SQLitePreferenceStore
from autocorrect.preferences.system_locale import detect_english_region
from autocorrect.productivity.app_profiles import ApplicationProfileManager
from autocorrect.productivity.local_insights import LocalInsightsStore
from autocorrect.productivity.snippet_engine import SnippetEngine
from autocorrect.updates.application_updater import ApplicationUpdater
from autocorrect.updates.coordinator import AppUpdateCoordinator
from autocorrect.updates.language_resource_updater import LanguageResourceUpdater
from autocorrect.updates.model_updater import ModelUpdater
from autocorrect.version import APP_VERSION as APP_VERSION_STR

log = logging.getLogger(__name__)

SAFE_MODE_FILENAME: Final[str] = "safe_mode"
PREF_FIRST_CORRECTION_SEEN: Final[str] = "first_correction_seen"
# How often the system locale is re-read when the language setting is "Follow system".
AUTO_REGION_RECHECK_S: Final[float] = 60.0
CLICK_SETTLE_S: Final[float] = 0.03
HOTKEY_ID_PAUSE: Final[int] = 1
HOTKEY_ID_SETTINGS: Final[int] = 2
SAFE_MODE_REMEDIATION: Final[str] = (
    "Typing assistance was switched off (safe mode). "
    "Choose 'Resume' in the tray menu, or run with --resume, to switch it back on."
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
        # Seconds left while Esc is being held (None once released/fired); for a tray countdown.
        self.on_hold_progress: Callable[[float | None], None] | None = None

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

        # 4. Productivity helpers, all persisted in the preference database.
        prefs = self.preference_store
        self.snippet_engine = SnippetEngine(
            load=prefs.list_snippets,
            save=prefs.save_snippet,
            delete=prefs.delete_snippet,
            case_matching=bool(prefs.get_typed("snippet_case_matching")),
        )
        self.app_profiles = ApplicationProfileManager(
            load=prefs.list_app_profiles,
            save=prefs.save_app_profile,
            delete=prefs.delete_app_profile,
        )
        self.insights = LocalInsightsStore(
            enabled=bool(prefs.get_typed("insights_enabled")),
            retention_days=int(prefs.get_typed("insights_retention_days")),
            load=prefs.load_insights,
            save_day=prefs.save_insights_day,
            prune=prefs.prune_insights,
            clear=prefs.clear_insights,
        )

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
        self.app_update_coordinator = AppUpdateCoordinator(
            updater=self.app_updater,
            state_path=self._data_dir / "staging_app" / "state.json",
            get_channel=lambda: str(self.preference_store.get_typed("update_channel")),
            get_updates_expire_at=lambda: self.entitlement_manager.evaluate().updates_expire_at,
            request_shutdown=self.request_shutdown,
        )
        self.model_updater = ModelUpdater(
            models_dir=self._data_dir / "models",
            public_key=self._public_key,
        )

        # 8. Initialize OS Injector, Focus Inspector, and Session State Machine
        self.injector = create_platform_injector()
        self.focus_inspector = create_platform_focus_inspector()
        # The session never injects by itself: the daemon applies each
        # ReplacementPlan after folding in keys typed while the plan was computed.
        self.session = InputSessionManager(
            engine=self.engine,
            injector=None,
            snippet_matcher=self.snippet_engine,
            entitlement_gate=self.entitlement_manager,
            active_region=self.preference_store.overlay.active_region,
        )
        # Observers (tray pulse, first-correction toast). Called off the hook thread.
        self.on_correction: Callable[[str, str, str], None] | None = None  # (original, replacement, reason)
        self.last_correction: tuple[str, str, str, float] | None = None
        self.session_correction_count: int = 0

        # 8b. Caret-context probe (Windows UI Automation): tells the session what
        # sits before the caret after a click / focus change, so the first word
        # of a typing sequence is capitalised exactly when it should be.
        self.caret_probe = create_caret_probe() if not dry_run_hooks else None

        # 9. Single worker thread that owns the session: hooks, mouse and focus all post to it.
        self.dispatcher = InputDispatcher(
            on_key_event=self._handle_key_on_worker,
            on_mouse_click=self._on_mouse_click_on_worker,
            on_focus_changed=self._on_focus_changed,
            on_overload=self._on_input_unhealthy,
        )

        # 10. Foreground-focus monitor: password fields, terminals, excluded apps, app profiles.
        self.focus_monitor = FocusMonitor(
            inspector=self.focus_inspector, on_change=self.dispatcher.post_focus
        )
        self._user_domain_packs: set[str] = set()
        self._auto_region_cache: RegionFlag | None = None
        self._auto_region_checked_at: float = 0.0

        # 11. Hold-Esc pause/resume toggle; polled independently of the hooks.
        self.kill_switch = KillSwitch(
            create_escape_probe() if not dry_run_hooks else None,
            on_trigger=self.on_escape_held,
            hold_seconds=migrate_hold_seconds(
                self.preference_store.get_setting, self.preference_store.set_setting
            ),
            on_hold_progress=self._on_hold_progress,
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
        self.apply_log_level()
        self.apply_global_correction_settings()
        self.set_user_domain_packs(set(self.preference_store.get_typed("enabled_domain_packs")))
        if start_ipc:
            self.ipc_server.start()
        self.dispatcher.start()
        if self.preference_store.get_typed("panic_hotkey_enabled"):
            self.kill_switch.start()
        if attach_hooks:
            self.attach_hooks()
        if self.preference_store.get_typed("start_paused"):
            self.session.set_paused(True)
            self._notify_state_changed()
        if self.preference_store.get_typed("updates_check_on_launch"):
            threading.Thread(
                target=self._check_app_updates_on_launch,
                name="typen-app-update-check",
                daemon=True,
            ).start()
        return snapshot

    def _check_app_updates_on_launch(self) -> None:
        try:
            self.app_update_coordinator.check()
        except Exception:
            log = logging.getLogger(__name__)
            log.exception("launch-time app update check failed")

    def apply_log_level(self) -> None:
        choice = str(self.preference_store.get_typed("log_level"))
        level = {"off": logging.CRITICAL + 10, "errors": logging.WARNING, "verbose": logging.DEBUG}.get(
            choice, logging.INFO
        )
        logging.getLogger("autocorrect").setLevel(level)

    # ------------------------------------------------------------ settings

    def apply_settings(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        """
        Store every known key in `changes` (validated and clamped by the schema)
        and apply the side effects at once: hotkeys, Esc switch, startup entry,
        region, domain packs, log level, and the live correction features.
        Returns the keys that were actually changed with their new typed values.
        """
        prefs = self.preference_store
        applied: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in settings_schema.SCHEMA_BY_KEY:
                continue
            new_value = settings_schema.coerce(key, value)
            if prefs.get_typed(key) == new_value:
                continue
            if key == "region":
                prefs.set_region_preference(str(new_value))
            else:
                prefs.set_typed(key, new_value)
            applied[key] = new_value
        if not applied:
            return applied

        if "launch_at_login" in applied and not self._dry_run_hooks:
            try:
                from autocorrect.daemon.startup import StartupManager

                StartupManager.set_launch_at_login(bool(applied["launch_at_login"]))
            except Exception:
                log.exception("could not update the launch-at-login entry")
        if any(k in applied for k in ("pause_hotkey", "settings_hotkey", "rewrite_hotkey")):
            self.reload_hotkeys()
        if "panic_hotkey_enabled" in applied:
            if applied["panic_hotkey_enabled"]:
                self.kill_switch.start()
            else:
                self.kill_switch.stop()
        if "panic_hold_seconds" in applied:
            self.kill_switch.set_hold_seconds(float(applied["panic_hold_seconds"]))
        if "log_level" in applied:
            self.apply_log_level()
        if "enabled_domain_packs" in applied:
            self.set_user_domain_packs(set(applied["enabled_domain_packs"]))
        if "insights_enabled" in applied:
            self.insights.set_enabled(bool(applied["insights_enabled"]))
        if "insights_retention_days" in applied:
            self.insights.set_retention_days(int(applied["insights_retention_days"]))
        self._reapply_features()
        self._notify_state_changed()
        return applied

    def try_text(self, text: str) -> str:
        """
        Run `text` through a throw-away session with the *current* features and
        region (Overview "Try it" field). Nothing is injected and the live
        session is untouched; returns what the field would contain.
        """
        text = text[:400]
        scratch = InputSessionManager(
            engine=self.engine, injector=None, active_region=self.session._active_region
        )
        scratch.configure_features(self.session.features)
        field_chars: list[str] = []
        ts = 0.0
        for ch in text:
            ts += 80.0
            key_name = "Space" if ch == " " else ("Return" if ch == "\n" else ch)
            outcome = scratch.handle_key_event(
                KeyEvent(key_name=key_name, char=ch, timestamp_ms=ts), suppress_delimiter_on_replace=True
            )
            if outcome.action == KeyAction.PASS_THROUGH:
                field_chars.append(ch)
            elif outcome.action == KeyAction.SUPPRESS_AND_INJECT and outcome.replacement_plan is not None:
                plan = outcome.replacement_plan
                for _ in range(plan.backspaces_to_send):
                    if field_chars:
                        field_chars.pop()
                field_chars.extend(plan.text_to_inject)
        return "".join(field_chars)

    def list_running_apps(self, limit: int = 60) -> list[dict[str, str]]:
        """Visible top-level windows → [{process, title}] for the Apps screen picker (Windows only)."""
        if sys.platform != "win32" or self._dry_run_hooks:
            return []
        try:
            from autocorrect.adapters.windows.window_list import list_visible_windows

            return list_visible_windows(limit=limit)
        except Exception:
            log.debug("list_visible_windows failed", exc_info=True)
            return []

    def _reapply_features(self) -> None:
        """Re-derive the live features for whatever is focused (profile or global)."""
        focus = self.focus_monitor.last_focus
        prof = None
        if focus is not None and self.entitlement_manager.is_pro_enabled():
            prof = self.app_profiles.get_profile(focus.process_name or focus.bundle_or_app_id)
        if prof is not None and prof.enabled:
            self.session.configure_features(prof.effective_features(self.global_features()))
            self.session.set_active_region(self.resolve_region(prof.region or None))
            self.snippet_engine.case_matching = bool(self.preference_store.get_typed("snippet_case_matching"))
            self._apply_process_lists()
        else:
            self.apply_global_correction_settings()

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

    def on_escape_held(self, reason: str = "Esc held") -> None:
        """
        Hold-Esc switch: flip between paused and active. Deliberately *not* an
        emergency stop any more: no safe-mode marker, hooks stay attached, and
        holding Esc again (or the tray / hotkey) brings corrections straight back.
        """
        hold = f"{self.kill_switch.hold_seconds:.0f}"
        notify = bool(self.preference_store.get_typed("notify_pause_resume"))
        if self.session.is_paused:
            if not self.preference_store.get_typed("panic_toggles_resume"):
                log.info("hold-Esc while paused ignored (panic_toggles_resume off)")
                return
            self.set_paused(False)
            log.info("hold-Esc: resumed (%s)", reason)
            if notify:
                self._notify("Typen resumed", "Corrections are back on.")
        else:
            self.set_paused(True)
            log.info("hold-Esc: paused (%s)", reason)
            if notify:
                self._notify(
                    "Typen paused",
                    f"Hold Esc for {hold} s again, or use the tray, to resume.",
                )

    def _on_hold_progress(self, remaining: float | None) -> None:
        if self.on_hold_progress is None:
            return
        try:
            self.on_hold_progress(remaining)
        except Exception:
            log.exception("on_hold_progress raised")

    def emergency_disable(self, reason: str = "emergency stop") -> None:
        """
        `--safe-mode` / health watchdog: release every OS hook, pause, and
        persist a safe-mode marker so the next start also comes up without hooks.
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
            f"{reason}. Corrections are off until you choose 'Resume' in the tray.",
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
                control_id=focus.control_id,
            )
        caret_before = None
        if not (effective.is_password_or_secure or effective.is_excluded_app):
            caret_before = self._read_caret_context()
        self.session.on_focus_changed(effective, caret_text_before=caret_before)

        if prof is not None and prof.enabled:
            self.session.configure_features(prof.effective_features(self.global_features()))
            self.session.set_active_region(self.resolve_region(prof.region or None))
        else:
            self.apply_global_correction_settings()
        self._apply_effective_domain_packs(focus)

    def _read_caret_context(self) -> str | None:
        """Text before the caret in the focused control, or None when unknown. Worker thread only."""
        probe = self.caret_probe
        if probe is None:
            return None
        try:
            ctx = probe.read()
        except Exception:
            log.debug("caret probe raised", exc_info=True)
            return None
        if ctx is None or ctx.is_password:
            return None
        return "" if ctx.is_empty_field else ctx.text_before

    def _on_mouse_click_on_worker(self) -> None:
        """
        A mouse button went down. The click lands *before* this runs, so by
        now the caret is where the user put it; read what precedes it and
        rebuild the sentence state. Also refreshes focus right away rather
        than waiting for the next monitor tick.
        """
        if self.session.is_paused:
            return
        if self.caret_probe is not None:
            # Give the target application a moment to place its caret before asking.
            time.sleep(CLICK_SETTLE_S)
        focus = self.focus_monitor.poll_once()
        if focus is not None:
            # poll_once already queued `_on_focus_changed`, which resyncs from the caret.
            return
        self.session.on_mouse_click_or_caret_move(caret_text_before=self._read_caret_context())

    def global_features(self) -> CorrectionFeatures:
        """The user's global correction behaviour, straight from the (validated) settings store."""
        prefs = self.preference_store
        values = prefs.get_all_typed("correction")
        values.update(prefs.get_all_typed("dictionary"))
        values.update(prefs.get_all_typed("language"))
        return CorrectionFeatures.from_mapping(values)

    def apply_global_correction_settings(self) -> None:
        """Push the user's global (non-profile) correction preferences into the session."""
        self.session.configure_features(self.global_features())
        self.session.set_active_region(self.resolve_region(None))
        prefs = self.preference_store
        self.snippet_engine.case_matching = bool(prefs.get_typed("snippet_case_matching"))
        self.insights.set_enabled(bool(prefs.get_typed("insights_enabled")))
        self.insights.set_retention_days(int(prefs.get_typed("insights_retention_days")))
        self._apply_process_lists()

    def _apply_process_lists(self) -> None:
        """Hand the user's excluded / code process names to the focus inspector."""
        prefs = self.preference_store
        inspector = self.focus_inspector
        excluded = [str(p).lower() for p in prefs.get_typed("excluded_processes")]
        code = [str(p).lower() for p in prefs.get_typed("code_processes")]
        if hasattr(inspector, "set_user_excluded_processes"):
            inspector.set_user_excluded_processes(excluded)
        if hasattr(inspector, "set_user_code_processes"):
            inspector.set_user_code_processes(code)

    # ------------------------------------------------------------ language

    def resolve_region(self, override: str | None) -> RegionFlag:
        """
        The variant to correct against: a profile override, else the stored
        choice, where "AUTO" means the system locale (re-detected at most once a
        minute). The preference overlay is kept in step for the engine's lookups.
        """
        name = (override or self.preference_store.stored_region_name()).upper()
        if name == "AUTO":
            region = self._auto_region()
        else:
            region = REGION_NAME_TO_FLAG.get(name, RegionFlag.EN_GB)
        self.preference_store.set_resolved_region(region)
        return region

    def _auto_region(self) -> RegionFlag:
        now = time.monotonic()
        if self._auto_region_cache is None or now - self._auto_region_checked_at > AUTO_REGION_RECHECK_S:
            self._auto_region_cache = detect_english_region()
            self._auto_region_checked_at = now
        return self._auto_region_cache

    def resolved_region_name(self) -> str:
        return str(self.resolve_region(None).name)

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
        outcome = self.session.handle_key_event(event, suppress_delimiter_on_replace=False)
        self._apply_outcome(outcome)

    def _apply_outcome(self, outcome: SessionEventOutcome) -> None:
        """
        Apply a session outcome on the worker thread: record insights, inject
        the replacement (folding in keys the user typed in the meantime), and
        notify observers.
        """
        decision = outcome.decision
        if decision is not None:
            self.insights.record_word_evaluated()
            self._maybe_suggest_dictionary_word(outcome)
        if outcome.reverted_word is not None:
            self.insights.record_undo()
            if outcome.replacement_plan is not None and not outcome.replacement_plan.is_noop:
                self._inject_with_compensation(outcome.replacement_plan, outcome)
            self._after_revert(outcome.reverted_word)
            return

        plan = outcome.replacement_plan
        if plan is None or plan.is_noop:
            return

        if not self._inject_with_compensation(plan, outcome):
            self.session.abandon_last_correction()
            return

        # Bookkeeping after a successful correction. Auto-space housekeeping
        # (swallowing the user's own Space, re-attaching '..."') is not a
        # correction and is neither counted nor announced.
        original, replacement, reason = _describe_outcome(outcome)
        if reason.startswith("AUTO_SPACE_"):
            return
        self._record_insight(reason, original, replacement)
        self.session_correction_count += 1
        self.last_correction = (original, replacement, reason, time.time())
        cb = self.on_correction
        if cb is not None and self.preference_store.get_typed("tray_pulse_on_correction"):
            try:
                cb(original, replacement, reason)
            except Exception:
                log.exception("on_correction raised")
        self._announce_first_correction(original, replacement)

    def _after_revert(self, word: str) -> None:
        """
        Revert-driven learning: once a word has been reverted `suggest_after_reverts`
        times it is surfaced (and optionally announced); at `auto_learn_after_reverts`
        (0 = never) it goes straight into the custom dictionary.
        """
        word = word.strip()
        if not word or " " in word:
            return
        prefs = self.preference_store
        count = prefs.overlay.revert_count(word)
        if count <= 0:
            return
        auto_at = int(prefs.get_typed("auto_learn_after_reverts"))
        if auto_at > 0 and count >= auto_at:
            prefs.add_custom_word(word)
            prefs.dismiss_suggested_word(word)
            if prefs.get_typed("notify_suggested_word"):
                self._notify("Added to your dictionary", f"'{word}' will not be corrected again.")
            return
        suggest_at = int(prefs.get_typed("suggest_after_reverts"))
        if count == suggest_at and prefs.get_typed("notify_suggested_word"):
            self._notify("Keep this word?", f"You reverted '{word}'. Add it in Typen > Dictionary.")

    def _maybe_suggest_dictionary_word(self, outcome: SessionEventOutcome) -> None:
        """
        Repeated-OOV learning: a word Typen keeps seeing but does not know is a
        candidate for the custom dictionary. Counted here (never the sentence),
        and surfaced on the Dictionary screen; optionally announced.
        """
        decision = outcome.decision
        if decision is None or decision.should_replace:
            return
        if decision.reason != CorrectionReason.INSUFFICIENT_CONFIDENCE:
            return
        word = decision.original_token
        if len(word) < 3 or not word.isalpha():
            return
        prefs = self.preference_store
        if not prefs.get_typed("learn_repeated_oov"):
            return
        threshold = int(prefs.get_typed("learn_repeated_threshold"))
        try:
            reached = prefs.note_repeated_oov(word, threshold)
        except Exception:
            log.debug("note_repeated_oov failed", exc_info=True)
            return
        if reached and prefs.get_typed("notify_suggested_word"):
            self._notify(
                "New word for your dictionary?", f"You keep typing '{word}'. Add it in Typen > Dictionary."
            )

    def _announce_first_correction(self, original: str, replacement: str) -> None:
        """Once per installation: confirm the very first fix so the user knows it is working."""
        prefs = self.preference_store
        if prefs.get_setting(PREF_FIRST_CORRECTION_SEEN, "false") == "true":
            return
        prefs.set_setting(PREF_FIRST_CORRECTION_SEEN, "true")
        if not prefs.get_typed("notify_first_correction"):
            return
        if original and replacement and original != replacement:
            detail = f"'{original}' became '{replacement}'."
        else:
            detail = "A fix just landed."
        self._notify(
            "Typen is working",
            f"{detail} The tray icon blinks red each time. Hold Esc for "
            f"{self.kill_switch.hold_seconds:.0f} s to pause or resume.",
        )

    def _inject_with_compensation(self, plan: ReplacementPlan, outcome: SessionEventOutcome) -> bool:
        """
        Inject `plan`, extended by any printable keys already queued behind the
        triggering delimiter (they have landed on screen, after the text the
        plan expects to be last). Returns False when something non-printable is
        pending, in which case nothing is injected.
        """
        pending = self.dispatcher.take_pending_printable()
        if pending is None:
            log.debug("skipping correction: caret/selection may have moved")
            return False
        if self._dry_run_hooks:
            # Nothing to inject in dry-run; still feed the late keys through.
            for ev in pending:
                self._handle_key_on_worker(ev)
            return True
        if pending:
            extra = "".join(ev.char for ev in pending)
            plan = ReplacementPlan(
                backspaces_to_send=plan.backspaces_to_send + len(extra),
                text_to_inject=plan.text_to_inject + extra,
                common_prefix_len=plan.common_prefix_len,
                original_full=plan.original_full + extra,
                target_full=plan.target_full + extra,
            )
        try:
            self.injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
        except Exception:
            log.exception("injection failed")
            return False
        # The late keys are now part of the field exactly as typed; run them
        # through the session so the word buffer and sentence state include them.
        for ev in pending:
            self._handle_key_on_worker(ev)
        return True

    def _record_insight(self, reason: str, original: str, replacement: str) -> None:
        if reason in (
            CorrectionReason.CONTEXTUAL_CONFUSION.value,
            CorrectionReason.GRAMMAR_AGREEMENT.value,
        ):
            self.insights.record_contextual_correction()
        elif reason in (
            CorrectionReason.SENTENCE_CAPITALISATION.value,
            CorrectionReason.PRONOUN_CAPITALISATION.value,
            CorrectionReason.EXACT_BRAND_CASING.value,
            CorrectionReason.PUNCTUATION_SPACING.value,
            CorrectionReason.DOUBLE_SPACE_PERIOD.value,
            CorrectionReason.CONTRACTION_RESTORED.value,
            "AUTO_SPACE",
        ):
            self.insights.record_punctuation_or_caps()
        elif reason == CorrectionReason.SNIPPET_EXPANSION.value:
            self.insights.record_snippet_expansion(len(original), len(replacement))
        else:
            self.insights.record_spelling_correction(chars_saved=max(1, len(original)))


def _describe_outcome(outcome: SessionEventOutcome) -> tuple[str, str, str]:
    """(original, replacement, reason) for logging/notification; never includes surrounding text."""
    d = outcome.decision
    plan = outcome.replacement_plan
    if d is not None and d.should_replace:
        return d.original_token, d.replacement_token, d.reason.value
    if plan is not None:
        return plan.original_full.strip(), plan.target_full.strip(), outcome.reason_tag or "CORRECTION"
    return "", "", outcome.reason_tag or "CORRECTION"


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
