"""
Main Background Application Daemon (`AutoCorrectDaemon`).
Wires together:
- `ResourceManager` (zero-copy mmap language intelligence)
- `SQLitePreferenceStore` + `PreferenceMemoryOverlay`
- `AutocorrectEngine` (Layer 1 spelling, contextual confusion sets, punctuation, capitalisation)
- `EntitlementManager` + `TrialManager` + `LicenceService`
- `InputSessionManager`
- OS Keyboard/Mouse Hook (`Win32KeyboardMouseHook` / `QuartzEventTapManager`)
- Safe automatic hook release whenever the 14-day trial expires or the user pauses assistance.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from autocorrect.adapters import create_platform_focus_inspector, create_platform_injector
from autocorrect.adapters.macos.quartz_tap import QuartzEventTapManager
from autocorrect.adapters.windows.win32_hook import Win32KeyboardMouseHook
from autocorrect.ai.api_key_manager import ApiKeyManager
from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.ai.provider_manager import BYOKProviderManager
from autocorrect.ai.spending_controls import SpendingController
from autocorrect.ai.usage_tracker import UsageTracker
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.input.ports import KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.ipc.server import LocalIPCServer
from autocorrect.licensing.activation_manager import compute_local_device_id_hash
from autocorrect.env_config import load_env_file
from autocorrect.licensing.entitlement_manager import EntitlementManager, EntitlementSnapshot
from autocorrect.licensing.licence_service import LicenceService
from autocorrect.licensing.trial_manager import TrialManager
from autocorrect.payments.pricing_config import PricingConfig
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
        device_id_hash: str | None = None,
        dry_run_hooks: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._dry_run_hooks = dry_run_hooks
        # Optional `.env` (creator device hashes etc.); never overrides real env vars.
        load_env_file(self._data_dir)
        self._win_hook: Win32KeyboardMouseHook | None = None
        self._mac_tap: QuartzEventTapManager | None = None
        self._hooks_active: bool = False

        # Default embedded Ed25519 verification key if none injected
        if public_key is None:
            default_priv = Ed25519PrivateKey.from_private_bytes(
                b"AutoCorrect-Embedded-Root-Key-v1"
            )
            public_key = default_priv.public_key()
        self._public_key = public_key
        self._device_id_hash = device_id_hash or compute_local_device_id_hash()

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

        # 5. Initialize Trial & Commercial Entitlement managers
        self.trial_manager = TrialManager(
            trial_file_path=self._data_dir / "licence" / "trial.dat",
            device_id_hash=self._device_id_hash,
            use_os_keyring=not dry_run_hooks,
        )
        self.entitlement_manager = EntitlementManager(
            public_key=self._public_key,
            device_id_hash=self._device_id_hash,
            trial_manager=self.trial_manager,
            on_typing_disabled_callback=self._on_entitlement_suspended,
        )
        self.licence_service = LicenceService(
            licence_file_path=self._data_dir / "licence" / "entitlement.lic",
            entitlement_manager=self.entitlement_manager,
            device_id_hash=self._device_id_hash,
        )

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

        # 7. Initialize Independent Updaters & Commercial Pricing Config
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
        self.pricing_config = PricingConfig()

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

        # 9. Initialize Authenticated Local IPC Server for out-of-process Settings UI
        self.ipc_server = LocalIPCServer(daemon=self, data_dir=self._data_dir)

    @property
    def hooks_active(self) -> bool:
        return self._hooks_active

    @property
    def device_id_hash(self) -> str:
        return self._device_id_hash

    @property
    def dry_run_hooks(self) -> bool:
        return self._dry_run_hooks

    def start(self, start_ipc: bool = True) -> EntitlementSnapshot:
        """
        Evaluate offline licence/trial state, start Local IPC server, and attach OS keyboard hooks only if entitled.
        """
        snapshot = self.licence_service.load_cached_licence_offline()
        self.local_ai.set_pro_entitled(snapshot.pro_features_enabled)
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

    def _on_entitlement_suspended(self) -> None:
        """
        Invoked automatically when the 14-day trial expires.
        Immediately releases OS keyboard hooks without deleting any user data or resources.
        """
        self._release_os_hooks()
        self.session.reset_all_state()

    def _attach_os_hooks(self) -> None:
        if self._hooks_active:
            return
        self._hooks_active = True
        if self._dry_run_hooks:
            return
        if sys.platform == "win32":
            self._win_hook = Win32KeyboardMouseHook(
                on_key_event=self._dispatch_os_key,
                on_mouse_click=self.session.on_mouse_click_or_caret_move,
            )
            self._win_hook.start()
        elif sys.platform == "darwin":
            self._mac_tap = QuartzEventTapManager(
                on_key_event=self._dispatch_os_key,
                on_mouse_click=self.session.on_mouse_click_or_caret_move,
            )
            self._mac_tap.start()

    def _release_os_hooks(self) -> None:
        self._hooks_active = False
        if self._win_hook is not None:
            self._win_hook.stop()
            self._win_hook = None
        if self._mac_tap is not None:
            self._mac_tap.stop()
            self._mac_tap = None

    def _dispatch_os_key(self, event: KeyEvent) -> KeyAction:
        outcome = self.session.handle_key_event(event)
        return outcome.action


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="AutoCorrect System-Wide Desktop Background Daemon"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".autocorrect_desktop",
        help="Directory for local SQLite preferences, licence, and resource cache",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attach live OS keyboard/mouse hooks and run continuously until Ctrl+C",
    )
    args = parser.parse_args(argv)

    daemon = AutoCorrectDaemon(
        data_dir=args.data_dir,
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
