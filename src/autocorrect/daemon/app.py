"""
Main Background Application Daemon (`AutoCorrectDaemon`).
Wires together:
- `ResourceManager` (zero-copy mmap language intelligence)
- `SQLitePreferenceStore` + `PreferenceMemoryOverlay`
- `AutocorrectEngine` (Layer 1 spelling, contextual confusion sets, punctuation, capitalisation)
- `EntitlementManager` (Tact is free software: every feature is always allowed)
- `InputSessionManager`
- OS Keyboard/Mouse Hook (`Win32KeyboardMouseHook` / `QuartzEventTapManager`)
- Safe hook release whenever the user pauses assistance.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from autocorrect.adapters import create_platform_focus_inspector, create_platform_injector
from autocorrect.adapters.linux.session_type import LinuxSessionType, detect_linux_session
from autocorrect.adapters.linux.x11_hook import X11HookError, X11KeyboardMouseHook
from autocorrect.adapters.macos.quartz_tap import QuartzEventTapManager, QuartzTapError
from autocorrect.adapters.windows.win32_hook import Win32KeyboardMouseHook
from autocorrect.ai.api_key_manager import ApiKeyManager
from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.ai.provider_manager import BYOKProviderManager
from autocorrect.ai.spending_controls import SpendingController
from autocorrect.ai.usage_tracker import UsageTracker
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.daemon import hook_status
from autocorrect.daemon.focus_monitor import FocusMonitor
from autocorrect.daemon.hook_status import HookState, HookStatus
from autocorrect.env_config import load_env_file
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
        self.hook_status: HookStatus = hook_status.INACTIVE

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

        # 5. Entitlements: Tact is free software, so this always answers "allowed".
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

        # 9. Foreground-focus monitor: password fields, terminals, excluded apps, app profiles.
        self.focus_monitor = FocusMonitor(inspector=self.focus_inspector, on_change=self._on_focus_changed)
        self._user_domain_packs: set[str] = set()

        # 10. Initialize Authenticated Local IPC Server for out-of-process Settings UI
        self.ipc_server = LocalIPCServer(daemon=self, data_dir=self._data_dir)

    @property
    def hooks_active(self) -> bool:
        return self._hooks_active

    @property
    def dry_run_hooks(self) -> bool:
        return self._dry_run_hooks

    def start(self, start_ipc: bool = True) -> EntitlementSnapshot:
        """
        Start the Local IPC server and attach the OS keyboard hooks.
        """
        snapshot = self.entitlement_manager.evaluate()
        self.local_ai.set_pro_entitled(snapshot.pro_features_enabled)
        # Restore persisted correction preferences and (Pro) domain packs.
        self.apply_global_correction_settings()
        saved_packs = self.preference_store.get_setting("enabled_domain_packs", "")
        self.set_user_domain_packs({p for p in saved_packs.split(",") if p.strip()})
        if start_ipc:
            self.ipc_server.start()
        if snapshot.typing_assistance_enabled:
            self._attach_os_hooks()
        else:
            self._release_os_hooks()
        return snapshot

    def stop(self) -> None:
        """Release all OS keyboard/mouse hooks, stop Local IPC server, and close mmap files."""
        self._release_os_hooks()
        self.ipc_server.stop()
        self.resource_manager.close()

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

    def _attach_os_hooks(self) -> None:
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
            self.hook_status = HookStatus(
                HookState.FAILED,
                detail=f"{type(exc).__name__}: {exc}",
                remediation="Restart AutoCorrect. If the problem persists, check the log and report it.",
            )
        if self.hook_status.state in (HookState.FAILED, HookState.UNSUPPORTED):
            # Nothing is listening; keep the daemon (IPC, settings) alive
            # but do not pretend typing assistance is running.
            self._hooks_active = False
            self.focus_monitor.stop()

    def _install_platform_hook(self) -> HookStatus:
        """Install the right hook for this OS/session; return its status (never raises for known failures)."""
        if sys.platform == "win32":
            self._win_hook = Win32KeyboardMouseHook(
                on_key_event=self._dispatch_os_key,
                on_mouse_click=self.session.on_mouse_click_or_caret_move,
            )
            self._win_hook.start()
            return HookStatus(HookState.ACTIVE, backend="win32-ll-hook")

        if sys.platform == "darwin":
            self._mac_tap = QuartzEventTapManager(
                on_key_event=self._dispatch_os_key,
                on_mouse_click=self.session.on_mouse_click_or_caret_move,
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
                        "(Settings → Keyboard → Input Sources → add 'English (Tact)') "
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
                on_mouse_click=self.session.on_mouse_click_or_caret_move,
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
        self._hooks_active = False
        self.hook_status = hook_status.INACTIVE
        self.focus_monitor.stop()
        if self._win_hook is not None:
            self._win_hook.stop()
            self._win_hook = None
        if self._mac_tap is not None:
            self._mac_tap.stop()
            self._mac_tap = None
        if self._x11_hook is not None:
            self._x11_hook.stop()
            self._x11_hook = None

    def _dispatch_os_key(self, event: KeyEvent) -> KeyAction:
        """Blocking hooks (Win32 LL hook, Quartz tap) can swallow the delimiter keystroke."""
        outcome = self.session.handle_key_event(event)
        return outcome.action

    def _dispatch_os_key_passive(self, event: KeyEvent) -> KeyAction:
        """Passive observers (XRecord) see keys after delivery; plans must re-inject the delimiter."""
        outcome = self.session.handle_key_event(event, suppress_delimiter_on_replace=False)
        return outcome.action


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
