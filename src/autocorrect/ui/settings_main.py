"""
10-Screen Desktop Customisation Controller and On-Demand Subprocess Entry Point.
Communicates with `AutoCorrectDaemon` over authenticated `LocalIPCClient`
(Windows Named Pipes / Unix Domain Sockets) when the background service is running,
and seamlessly falls back to local stores in standalone/test mode.

Covers all 10 architecture screens:
1. Overview (Status, active language, edition, LocalInsightsStore statistics)
2. General (Startup at login, global hotkeys, one-click Privacy Wipe)
3. Dictionary (Custom words, reverted Suggested Words, CSV/JSON import/export)
4. Languages (Regional English variants EN_GB/EN_US/EN_CA/EN_AU/UNIVERSAL & 6 Domain Packs)
5. Corrections (Sensitivity/aggressiveness, rejected pairs, preferred variants, punctuation/undo)
6. Pro Intelligence (Layer 2 Local AI hardware/models & Layer 3 BYOK Cloud AI, OS Keyring, spend caps, Local-Only mode)
7. Profiles (Per-application typing & correction profiles)
8. Text Expansion (Pro custom snippets and `{{date}}`/`{{time}}` macros)
9. Updates (Independent App, Language Intelligence Library delta/rollback, and Local AI Model updates)
10. Licence (Edition, activation, Device Lock SHA-256 hash, 12-month update entitlement, and BACHS pricing)
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import Any

from autocorrect.ai.api_key_manager import ApiKeyManager
from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.ai.provider_manager import AIProviderId
from autocorrect.ai.spending_controls import SpendingController
from autocorrect.ai.usage_tracker import UsageTracker
from autocorrect.ipc.client import LocalIPCClient
from autocorrect.ipc.protocol import IPC_ENDPOINT_FILENAME, IPCConnectionError, IPCError
from autocorrect.ipc.server import AVAILABLE_DOMAIN_PACK_METADATA
from autocorrect.licensing.activation_manager import compute_local_device_id_hash
from autocorrect.licensing.entitlement_manager import EntitlementManager
from autocorrect.licensing.licence_service import LicenceService
from autocorrect.licensing.root_key import load_root_public_key
from autocorrect.licensing.signed_licence import (
    Edition,
    SignedLicenceCertificate,
    current_platform_sku,
)
from autocorrect.licensing.trial_manager import TrialManager
from autocorrect.payments.pricing_config import PricingConfig
from autocorrect.payments.upgrade_pricing import UpgradePricingCalculator
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.productivity.app_profiles import (
    ApplicationProfile,
    ApplicationProfileManager,
)
from autocorrect.productivity.local_insights import LocalInsightsStore
from autocorrect.productivity.snippet_engine import SnippetEngine
from autocorrect.version import APP_RELEASE_TIMESTAMP, APP_VERSION, BINARY_SCHEMA_VERSION

SCREEN_NAMES: tuple[str, ...] = (
    "Overview",
    "General",
    "Dictionary",
    "Languages",
    "Corrections",
    "Pro Intelligence",
    "Profiles",
    "Text Expansion",
    "Updates",
    "Licence",
)


class SettingsController:
    """
    Unified 10-Screen Controller backing the PySide6/QML Desktop UI, native fallback UI,
    and headless test automation.
    Automatically delegates to `LocalIPCClient` when `AutoCorrectDaemon` is active on `data_dir`.
    """

    def __init__(self, data_dir: Path, use_memory_keyring: bool = False) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._use_memory_keyring = use_memory_keyring

        self._ipc_client = LocalIPCClient(data_dir=self._data_dir, max_retries=1)
        self._prefs = SQLitePreferenceStore(self._data_dir / "preferences.sqlite3")
        self._api_keys = ApiKeyManager(use_memory_backend=use_memory_keyring)
        self._usage_tracker = UsageTracker(self._data_dir / "ai_usage.sqlite3")
        self._spending = SpendingController(usage_tracker=self._usage_tracker)
        self._local_ai = LocalModelManager(is_pro_entitled=False)  # synced from entitlement below
        self._profiles = ApplicationProfileManager()
        self._snippets = SnippetEngine()
        self._insights = LocalInsightsStore(enabled=True)
        self._pricing_config = PricingConfig()
        self._device_id_hash = compute_local_device_id_hash()

        self._public_key = load_root_public_key()
        self._trial_mgr = TrialManager(
            trial_file_path=self._data_dir / "licence" / "trial.dat",
            device_id_hash=self._device_id_hash,
            use_os_keyring=not use_memory_keyring,
        )
        self._entitlement_mgr = EntitlementManager(
            public_key=self._public_key,
            device_id_hash=self._device_id_hash,
            trial_manager=self._trial_mgr,
        )
        self._licence_service = LicenceService(
            licence_file_path=self._data_dir / "licence" / "entitlement.lic",
            entitlement_manager=self._entitlement_mgr,
            device_id_hash=self._device_id_hash,
        )
        self._licence_service.load_cached_licence_offline()
        self._local_ai.set_pro_entitled(self._entitlement_mgr.is_pro_enabled())

    def _offline_pro_enabled(self) -> bool:
        """Entitlement as seen by the UI process when the daemon is offline (same signed sources)."""
        snap = self._licence_service.load_cached_licence_offline()
        self._local_ai.set_pro_entitled(snap.pro_features_enabled)
        return snap.pro_features_enabled

    def _offline_require_pro(self, feature: str) -> None:
        if not self._offline_pro_enabled():
            raise PermissionError(f"{feature} require a Pro Edition licence (or the active 14-day trial).")

    @property
    def preferences(self) -> SQLitePreferenceStore:
        return self._prefs

    @property
    def api_keys(self) -> ApiKeyManager:
        return self._api_keys

    @property
    def ipc_client(self) -> LocalIPCClient:
        return self._ipc_client

    def is_daemon_ipc_connected(self) -> bool:
        """Return True if the background service IPC endpoint is active and reachable."""
        if not (self._data_dir / IPC_ENDPOINT_FILENAME).exists():
            return False
        return self._ipc_client.is_daemon_online()

    def _call_ipc_if_online(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not (self._data_dir / IPC_ENDPOINT_FILENAME).exists():
            return None
        try:
            return self._ipc_client.call(method, params or {}, retries=1)
        except IPCConnectionError:
            return None  # daemon offline: use the direct-SQLite fallback
        except IPCError as exc:
            # The daemon answered and *refused* (e.g. Pro gate). Never fall back to
            # the offline path here, or the UI would silently bypass the gate.
            if "Pro Edition" in str(exc):
                raise PermissionError(str(exc)) from exc
            raise

    def get_settings_summary(self) -> dict[str, object]:
        self._prefs.reload_into_overlay()
        return {
            "region": self._prefs.overlay.active_region.name,
            "custom_word_count": len(self._prefs.list_custom_words()),
            "openai_key_configured": self._api_keys.has_api_key("openai"),
            "anthropic_key_configured": self._api_keys.has_api_key("anthropic"),
            "gemini_key_configured": self._api_keys.has_api_key("gemini"),
            "screens_available": list(SCREEN_NAMES),
        }

    # =========================================================================
    # SCREEN 1: OVERVIEW
    # =========================================================================
    def get_overview(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("system.get_overview")
        if ipc_res is not None:
            return ipc_res
        self._prefs.reload_into_overlay()
        snap = self._licence_service.load_cached_licence_offline()
        ins = self._insights.get_summary()
        enabled_packs_raw = self._prefs.get_setting("enabled_domain_packs", "")
        enabled_packs = [p for p in enabled_packs_raw.split(",") if p]
        return {
            "app_version": APP_VERSION,
            "hooks_active": False,
            "hook_status": {
                "state": "inactive",
                "backend": "",
                "detail": "The background service is not running.",
                "remediation": "Start AutoCorrect Desktop (it normally launches at login).",
            },
            "is_paused": self._prefs.get_setting("is_paused", "false") == "true",
            "active_region": self._prefs.overlay.active_region.name or "EN_GB",
            "custom_word_count": len(self._prefs.list_custom_words()),
            "suggested_word_count": len(self._prefs.list_suggested_words()),
            "lexicon_word_count": 100_000,
            "resource_version": "1.2.0",
            "enabled_domain_packs": enabled_packs,
            "entitlement": {
                "mode": snap.mode,
                "typing_assistance_enabled": snap.typing_assistance_enabled,
                "pro_features_enabled": snap.pro_features_enabled,
                "can_download_new_updates": snap.can_download_new_updates,
                "updates_expire_at": (snap.updates_expire_at.isoformat() if snap.updates_expire_at else None),
                "status_message": snap.status_message,
            },
            "insights": {
                "enabled": self._insights.enabled,
                "words_evaluated": ins.words_evaluated,
                "spelling_corrections": ins.spelling_corrections,
                "contextual_corrections": ins.contextual_corrections,
                "punctuation_and_caps_fixes": ins.punctuation_and_caps_fixes,
                "snippets_expanded": ins.snippets_expanded,
                "corrections_undone": ins.corrections_undone,
                "keystrokes_saved": ins.keystrokes_saved,
            },
        }

    def set_paused(self, paused: bool) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("system.set_paused", {"paused": paused})
        if ipc_res is not None:
            return ipc_res
        self._prefs.set_setting("is_paused", "true" if paused else "false")
        return {"is_paused": paused, "hooks_active": False}

    def set_insights_enabled(self, enabled: bool) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("insights.set_enabled", {"enabled": enabled})
        if ipc_res is not None:
            return ipc_res
        self._insights.set_enabled(enabled)
        return {"enabled": self._insights.enabled}

    def reset_insights(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("insights.reset")
        if ipc_res is not None:
            return ipc_res
        self._insights.reset()
        return {"ok": True}

    # =========================================================================
    # SCREEN 2: GENERAL
    # =========================================================================
    def get_general_settings(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("general.get_settings")
        if ipc_res is not None:
            return ipc_res
        return {
            "launch_at_login": self._prefs.get_setting("launch_at_login", "false") == "true",
            "show_tray_icon": self._prefs.get_setting("show_tray_icon", "true") == "true",
            "rewrite_hotkey": self._prefs.get_setting("rewrite_hotkey", "Ctrl+Shift+R"),
            "pause_hotkey": self._prefs.get_setting("pause_hotkey", "Ctrl+Alt+P"),
            "settings_hotkey": self._prefs.get_setting("settings_hotkey", "Ctrl+Alt+,"),
        }

    def update_general_settings(
        self,
        *,
        launch_at_login: bool | None = None,
        show_tray_icon: bool | None = None,
        rewrite_hotkey: str | None = None,
        pause_hotkey: str | None = None,
        settings_hotkey: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if launch_at_login is not None:
            params["launch_at_login"] = launch_at_login
        if show_tray_icon is not None:
            params["show_tray_icon"] = show_tray_icon
        if rewrite_hotkey is not None:
            params["rewrite_hotkey"] = rewrite_hotkey
        if pause_hotkey is not None:
            params["pause_hotkey"] = pause_hotkey
        if settings_hotkey is not None:
            params["settings_hotkey"] = settings_hotkey

        ipc_res = self._call_ipc_if_online("general.update_settings", params)
        if ipc_res is not None:
            return ipc_res

        if launch_at_login is not None:
            self._prefs.set_setting("launch_at_login", "true" if launch_at_login else "false")
        if show_tray_icon is not None:
            self._prefs.set_setting("show_tray_icon", "true" if show_tray_icon else "false")
        if rewrite_hotkey is not None and rewrite_hotkey.strip():
            self._prefs.set_setting("rewrite_hotkey", rewrite_hotkey.strip())
        if pause_hotkey is not None and pause_hotkey.strip():
            self._prefs.set_setting("pause_hotkey", pause_hotkey.strip())
        if settings_hotkey is not None and settings_hotkey.strip():
            self._prefs.set_setting("settings_hotkey", settings_hotkey.strip())
        return self.get_general_settings()

    def privacy_wipe(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("general.privacy_wipe")
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return ipc_res
        self._prefs.clear_all_preferences()
        self._insights.reset()
        return {"wiped": True, "custom_word_count": 0}

    # =========================================================================
    # SCREEN 3: DICTIONARY (Custom Words, Reverted Suggestions, CSV/JSON)
    # =========================================================================
    def get_dictionary_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("dictionary.get_state")
        if ipc_res is not None:
            return ipc_res
        return {
            "words": self._prefs.list_custom_words(),
            "suggested": self._prefs.list_suggested_words(),
        }

    def list_custom_words(self) -> list[str]:
        """Return the user's custom dictionary words, sorted alphabetically."""
        ipc_res = self._call_ipc_if_online("dictionary.get_state")
        if ipc_res is not None and isinstance(ipc_res.get("words"), list):
            return [str(w) for w in ipc_res["words"]]
        return self._prefs.list_custom_words()

    def add_custom_word(self, word: str, category: str = "user") -> list[str]:
        """Add a manually typed word to the custom dictionary and return the list."""
        cleaned = word.strip()
        if cleaned and len(cleaned) <= 64 and " " not in cleaned:
            ipc_res = self._call_ipc_if_online("dictionary.add_word", {"word": cleaned, "category": category})
            if ipc_res is not None and isinstance(ipc_res.get("words"), list):
                self._prefs.reload_into_overlay()
                return [str(w) for w in ipc_res["words"]]
            self._prefs.add_custom_word(cleaned, category=category)
        return self._prefs.list_custom_words()

    def delete_custom_word(self, word: str) -> list[str]:
        """Delete a word so it is eligible for correction again; return the list."""
        ipc_res = self._call_ipc_if_online("dictionary.remove_word", {"word": word})
        if ipc_res is not None and isinstance(ipc_res.get("words"), list):
            self._prefs.reload_into_overlay()
            return [str(w) for w in ipc_res["words"]]
        self._prefs.remove_custom_word(word)
        return self._prefs.list_custom_words()

    def list_suggested_words(self) -> list[dict[str, object]]:
        """Return words the user reverted via double-Backspace."""
        ipc_res = self._call_ipc_if_online("dictionary.get_state")
        if ipc_res is not None and isinstance(ipc_res.get("suggested"), list):
            return [dict(item) for item in ipc_res["suggested"]]
        return self._prefs.list_suggested_words()

    def accept_suggested_word(self, word: str) -> list[str]:
        """Promote a suggested reverted word into the user's custom dictionary."""
        ipc_res = self._call_ipc_if_online("dictionary.accept_suggested", {"word": word})
        if ipc_res is not None and isinstance(ipc_res.get("words"), list):
            self._prefs.reload_into_overlay()
            return [str(w) for w in ipc_res["words"]]
        self._prefs.accept_suggested_word(word)
        return self._prefs.list_custom_words()

    def dismiss_suggested_word(self, word: str) -> list[dict[str, object]]:
        """Dismiss a suggested word without adding it to the custom dictionary."""
        ipc_res = self._call_ipc_if_online("dictionary.dismiss_suggested", {"word": word})
        if ipc_res is not None and isinstance(ipc_res.get("suggested"), list):
            self._prefs.reload_into_overlay()
            return [dict(item) for item in ipc_res["suggested"]]
        self._prefs.dismiss_suggested_word(word)
        return self._prefs.list_suggested_words()

    def export_dictionary_csv(self) -> str:
        ipc_res = self._call_ipc_if_online("dictionary.export_csv")
        if ipc_res is not None and "csv" in ipc_res:
            return str(ipc_res["csv"])
        return self._prefs.export_custom_words_csv()

    def import_dictionary_csv(self, csv_text: str) -> int:
        ipc_res = self._call_ipc_if_online("dictionary.import_csv", {"csv": csv_text})
        if ipc_res is not None and "imported_count" in ipc_res:
            self._prefs.reload_into_overlay()
            return int(ipc_res["imported_count"])
        return self._prefs.import_custom_words_csv(csv_text)

    def export_dictionary_json(self) -> str:
        ipc_res = self._call_ipc_if_online("dictionary.export_json")
        if ipc_res is not None and "json" in ipc_res:
            return str(ipc_res["json"])
        return self._prefs.export_json()

    def import_dictionary_json(self, json_text: str) -> None:
        ipc_res = self._call_ipc_if_online("dictionary.import_json", {"json": json_text})
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return
        self._prefs.import_json(json_text)

    # =========================================================================
    # SCREEN 4: LANGUAGES & DOMAIN PACKS
    # =========================================================================
    def get_languages_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("languages.get_state")
        if ipc_res is not None:
            return ipc_res
        self._prefs.reload_into_overlay()
        enabled_raw = self._prefs.get_setting("enabled_domain_packs", "")
        enabled_set = {p.strip() for p in enabled_raw.split(",") if p.strip()}
        return {
            "active_region": self._prefs.overlay.active_region.name or "EN_GB",
            "available_regions": [
                {"code": "EN_GB", "name": "British English (UK)"},
                {"code": "EN_US", "name": "American English (US)"},
                {"code": "EN_CA", "name": "Canadian English (CA)"},
                {"code": "EN_AU", "name": "Australian English (AU)"},
                {"code": "UNIVERSAL", "name": "Universal English"},
            ],
            "domain_packs": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "description": m["description"],
                    "enabled": m["id"] in enabled_set,
                }
                for m in AVAILABLE_DOMAIN_PACK_METADATA
            ],
            "pro_enabled": self._offline_pro_enabled(),
        }

    def set_region(self, region_code: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("languages.set_region", {"region": region_code})
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return ipc_res
        self._prefs.set_region_preference(region_code)
        return self.get_languages_state()

    def set_enabled_domain_packs(self, pack_ids: list[str] | set[str]) -> dict[str, Any]:
        norm = sorted({str(p).strip().lower() for p in pack_ids if str(p).strip()})
        ipc_res = self._call_ipc_if_online("languages.set_domain_packs", {"pack_ids": norm})
        if ipc_res is not None:
            return ipc_res
        if norm:
            self._offline_require_pro("Domain vocabulary packs")
        self._prefs.set_setting("enabled_domain_packs", ",".join(norm))
        return self.get_languages_state()

    # =========================================================================
    # SCREEN 5: CORRECTIONS, SENSITIVITY, REJECTED & PREFERRED VARIANTS
    # =========================================================================
    def get_corrections_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("corrections.get_state")
        if ipc_res is not None:
            return ipc_res
        return {
            "enable_punctuation_assist": self._prefs.get_setting("enable_punctuation_assist", "true")
            == "true",
            "enable_double_space_period": self._prefs.get_setting("enable_double_space_period", "true")
            == "true",
            "enable_auto_capitalise": self._prefs.get_setting("enable_auto_capitalise", "true") == "true",
            "aggressiveness": float(self._prefs.get_setting("aggressiveness", "1.0")),
            "rejected_corrections": self._prefs.list_rejected_corrections(),
            "preferred_variants": [
                {"source": k, "preferred": v} for k, v in self._prefs.list_preferred_variants().items()
            ],
        }

    def update_correction_features(
        self,
        *,
        enable_punctuation_assist: bool | None = None,
        enable_double_space_period: bool | None = None,
        enable_auto_capitalise: bool | None = None,
        aggressiveness: float | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if enable_punctuation_assist is not None:
            params["enable_punctuation_assist"] = enable_punctuation_assist
        if enable_double_space_period is not None:
            params["enable_double_space_period"] = enable_double_space_period
        if enable_auto_capitalise is not None:
            params["enable_auto_capitalise"] = enable_auto_capitalise
        if aggressiveness is not None:
            params["aggressiveness"] = aggressiveness

        ipc_res = self._call_ipc_if_online("corrections.update_features", params)
        if ipc_res is not None:
            return ipc_res

        if enable_punctuation_assist is not None:
            self._prefs.set_setting(
                "enable_punctuation_assist",
                "true" if enable_punctuation_assist else "false",
            )
        if enable_double_space_period is not None:
            self._prefs.set_setting(
                "enable_double_space_period",
                "true" if enable_double_space_period else "false",
            )
        if enable_auto_capitalise is not None:
            self._prefs.set_setting("enable_auto_capitalise", "true" if enable_auto_capitalise else "false")
        if aggressiveness is not None:
            clamped = max(0.5, min(1.5, float(aggressiveness)))
            self._prefs.set_setting("aggressiveness", f"{clamped:.2f}")
        return self.get_corrections_state()

    def add_rejected_correction(self, original: str, candidate: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online(
            "corrections.add_rejected", {"original": original, "candidate": candidate}
        )
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return ipc_res
        self._prefs.add_rejected_correction(original, candidate)
        return self.get_corrections_state()

    def remove_rejected_correction(self, original: str, candidate: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online(
            "corrections.remove_rejected",
            {"original": original, "candidate": candidate},
        )
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return ipc_res
        self._prefs.remove_rejected_correction(original, candidate)
        return self.get_corrections_state()

    def set_preferred_variant(self, source: str, preferred: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online(
            "corrections.set_preferred_variant",
            {"source": source, "preferred": preferred},
        )
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return ipc_res
        self._prefs.set_preferred_variant(source, preferred)
        return self.get_corrections_state()

    def remove_preferred_variant(self, source: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("corrections.remove_preferred_variant", {"source": source})
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return ipc_res
        self._prefs.remove_preferred_variant(source)
        return self.get_corrections_state()

    # =========================================================================
    # SCREEN 6: PRO INTELLIGENCE (Local AI & BYOK Cloud AI)
    # =========================================================================
    def get_ai_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("ai.get_state")
        if ipc_res is not None:
            return ipc_res
        hw = self._local_ai.detect_hardware_profile()
        day_u = self._usage_tracker.get_summary_since(0.0)
        return {
            "pro_enabled": self._offline_pro_enabled(),
            "local_ai": {
                "model_loaded": self._local_ai.is_model_loaded,
                "cpu_cores": hw.cpu_cores,
                "total_ram_mb": hw.total_ram_mb,
                "accelerator": hw.accelerator,
                "recommended_model_id": hw.recommended_model_id,
                "pause_pill_enabled": self._prefs.get_setting("pause_pill_enabled", "true") == "true",
            },
            "byok": {
                "local_only_mode": self._prefs.get_setting("local_only_mode", "false") == "true",
                "global_cloud_consent": self._prefs.get_setting("global_cloud_consent", "false") == "true",
                "daily_limit_usd": self._prefs.get_setting("daily_limit_usd", "2.00"),
                "monthly_limit_usd": self._prefs.get_setting("monthly_limit_usd", "15.00"),
                "active_provider": self._prefs.get_setting("active_ai_provider", "openai"),
                "active_model": self._prefs.get_setting("active_ai_model", "gpt-4o-mini"),
                "providers": {
                    p.value: {"has_key": self._api_keys.has_api_key(p.value)} for p in AIProviderId
                },
                "usage_24h": {
                    "requests": day_u.total_requests,
                    "prompt_tokens": day_u.prompt_tokens,
                    "completion_tokens": day_u.completion_tokens,
                    "estimated_cost_usd": str(day_u.estimated_cost_usd),
                },
                "usage_30d": {
                    "requests": day_u.total_requests,
                    "prompt_tokens": day_u.prompt_tokens,
                    "completion_tokens": day_u.completion_tokens,
                    "estimated_cost_usd": str(day_u.estimated_cost_usd),
                },
            },
        }

    def set_byok_api_key(self, provider: str, api_key: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("ai.set_api_key", {"provider": provider, "api_key": api_key})
        if ipc_res is not None:
            return ipc_res
        prov = provider.strip().lower()
        key = api_key.strip()
        if not key:
            self._api_keys.delete_api_key(prov)
        else:
            if not self._api_keys.validate_key_format(prov, key):
                raise ValueError(f"Invalid API key format for provider '{prov}'")
            self._api_keys.set_api_key(prov, key)
        return self.get_ai_state()

    def update_ai_settings(
        self,
        *,
        local_only_mode: bool | None = None,
        global_cloud_consent: bool | None = None,
        pause_pill_enabled: bool | None = None,
        daily_limit_usd: str | Decimal | None = None,
        monthly_limit_usd: str | Decimal | None = None,
        active_provider: str | None = None,
        active_model: str | None = None,
        load_local_model: bool = False,
        unload_local_model: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if local_only_mode is not None:
            params["local_only_mode"] = local_only_mode
        if global_cloud_consent is not None:
            params["global_cloud_consent"] = global_cloud_consent
        if pause_pill_enabled is not None:
            params["pause_pill_enabled"] = pause_pill_enabled
        if daily_limit_usd is not None:
            params["daily_limit_usd"] = str(daily_limit_usd)
        if monthly_limit_usd is not None:
            params["monthly_limit_usd"] = str(monthly_limit_usd)
        if active_provider is not None:
            params["active_provider"] = active_provider
        if active_model is not None:
            params["active_model"] = active_model
        if load_local_model:
            params["load_local_model"] = True
        if unload_local_model:
            params["unload_local_model"] = True

        ipc_res = self._call_ipc_if_online("ai.update_settings", params)
        if ipc_res is not None:
            return ipc_res

        if local_only_mode is not None:
            self._spending.set_local_only_mode(local_only_mode)
            self._prefs.set_setting("local_only_mode", "true" if local_only_mode else "false")
        if global_cloud_consent is not None:
            self._prefs.set_setting("global_cloud_consent", "true" if global_cloud_consent else "false")
        if pause_pill_enabled is not None:
            self._prefs.set_setting("pause_pill_enabled", "true" if pause_pill_enabled else "false")
        if daily_limit_usd is not None:
            self._prefs.set_setting("daily_limit_usd", f"{Decimal(str(daily_limit_usd)):.2f}")
        if monthly_limit_usd is not None:
            self._prefs.set_setting("monthly_limit_usd", f"{Decimal(str(monthly_limit_usd)):.2f}")
        if active_provider is not None:
            self._prefs.set_setting("active_ai_provider", active_provider)
        if active_model is not None:
            self._prefs.set_setting("active_ai_model", active_model)
        if load_local_model:
            self._local_ai.load_model()
        elif unload_local_model:
            self._local_ai.unload_model()
        return self.get_ai_state()

    # =========================================================================
    # SCREEN 7: APPLICATION PROFILES
    # =========================================================================
    def list_app_profiles(self) -> list[dict[str, Any]]:
        ipc_res = self._call_ipc_if_online("profiles.list")
        if ipc_res is not None and isinstance(ipc_res.get("profiles"), list):
            return list(ipc_res["profiles"])
        return [
            {
                "app_identifier": p.app_identifier,
                "display_name": p.display_name,
                "enabled": p.enabled,
                "enable_punctuation_assist": p.enable_punctuation_assist,
                "enable_double_space_period": p.enable_double_space_period,
                "enable_auto_capitalise": p.enable_auto_capitalise,
                "aggressiveness": p.aggressiveness,
                "active_domain_packs": sorted(p.active_domain_packs),
            }
            for p in self._profiles.list_profiles()
        ]

    def upsert_app_profile(
        self,
        app_identifier: str,
        display_name: str,
        *,
        enabled: bool = True,
        enable_punctuation_assist: bool = True,
        enable_double_space_period: bool = True,
        enable_auto_capitalise: bool = True,
        aggressiveness: float = 1.0,
        active_domain_packs: list[str] | set[str] = (),
    ) -> list[dict[str, Any]]:
        payload = {
            "app_identifier": app_identifier,
            "display_name": display_name,
            "enabled": enabled,
            "enable_punctuation_assist": enable_punctuation_assist,
            "enable_double_space_period": enable_double_space_period,
            "enable_auto_capitalise": enable_auto_capitalise,
            "aggressiveness": aggressiveness,
            "active_domain_packs": list(active_domain_packs),
        }
        ipc_res = self._call_ipc_if_online("profiles.upsert", payload)
        if ipc_res is not None and isinstance(ipc_res.get("profiles"), list):
            return list(ipc_res["profiles"])
        self._offline_require_pro("Per-application profiles")
        self._profiles.set_profile(
            ApplicationProfile(
                app_identifier=app_identifier.strip().lower(),
                display_name=display_name.strip() or app_identifier.strip(),
                enabled=enabled,
                enable_punctuation_assist=enable_punctuation_assist,
                enable_double_space_period=enable_double_space_period,
                enable_auto_capitalise=enable_auto_capitalise,
                aggressiveness=aggressiveness,
                active_domain_packs=frozenset(active_domain_packs),
            )
        )
        return self.list_app_profiles()

    def delete_app_profile(self, app_identifier: str) -> list[dict[str, Any]]:
        ipc_res = self._call_ipc_if_online("profiles.delete", {"app_identifier": app_identifier})
        if ipc_res is not None and isinstance(ipc_res.get("profiles"), list):
            return list(ipc_res["profiles"])
        self._profiles.remove_profile(app_identifier)
        return self.list_app_profiles()

    # =========================================================================
    # SCREEN 8: TEXT EXPANSION SNIPPETS
    # =========================================================================
    def list_snippets(self) -> list[dict[str, str]]:
        ipc_res = self._call_ipc_if_online("snippets.list")
        if ipc_res is not None and isinstance(ipc_res.get("snippets"), list):
            return list(ipc_res["snippets"])
        return [
            {
                "trigger": s.trigger,
                "expansion": s.expansion,
                "description": s.description,
            }
            for s in self._snippets.list_snippets()
        ]

    def upsert_snippet(self, trigger: str, expansion: str, description: str = "") -> list[dict[str, str]]:
        ipc_res = self._call_ipc_if_online(
            "snippets.upsert",
            {"trigger": trigger, "expansion": expansion, "description": description},
        )
        if ipc_res is not None and isinstance(ipc_res.get("snippets"), list):
            return list(ipc_res["snippets"])
        self._offline_require_pro("Text-expansion snippets")
        self._snippets.add_snippet(trigger=trigger, expansion=expansion, description=description)
        return self.list_snippets()

    def delete_snippet(self, trigger: str) -> list[dict[str, str]]:
        ipc_res = self._call_ipc_if_online("snippets.delete", {"trigger": trigger})
        if ipc_res is not None and isinstance(ipc_res.get("snippets"), list):
            return list(ipc_res["snippets"])
        self._snippets.remove_snippet(trigger)
        return self.list_snippets()

    # =========================================================================
    # SCREEN 9: INDEPENDENT UPDATES
    # =========================================================================
    def get_updates_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("updates.get_state")
        if ipc_res is not None:
            return ipc_res
        hw = self._local_ai.detect_hardware_profile()
        snap = self._licence_service.load_cached_licence_offline()
        return {
            "app": {
                "current_version": APP_VERSION,
                "released_at": APP_RELEASE_TIMESTAMP,
                "channel": "stable",
            },
            "language_resources": {
                "active_version": "1.2.0",
                "schema_version": BINARY_SCHEMA_VERSION,
                "released_at": APP_RELEASE_TIMESTAMP,
                "word_count": 100_000,
                "bundle_dir": "resources/en_base",
            },
            "local_models": {
                "recommended_model_id": hw.recommended_model_id,
                "accelerator": hw.accelerator,
                "is_loaded": self._local_ai.is_model_loaded,
            },
            "entitlement": {
                "can_download_new_updates": snap.can_download_new_updates,
                "updates_expire_at": (snap.updates_expire_at.isoformat() if snap.updates_expire_at else None),
            },
        }

    def rollback_language_resources(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("updates.rollback_resources")
        if ipc_res is not None:
            return ipc_res
        return self.get_updates_state()

    # =========================================================================
    # SCREEN 10: LICENCE & COMMERCIAL ENTITLEMENT
    # =========================================================================
    def get_licence_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("licence.get_state")
        if ipc_res is not None:
            return ipc_res
        snap = self._licence_service.load_cached_licence_offline()
        cert = self._entitlement_mgr.active_certificate
        calc = UpgradePricingCalculator(self._pricing_config)
        std_q = calc.calculate_quote(current_platform_sku(Edition.STANDARD), existing_cert=cert)
        pro_q = calc.calculate_quote(current_platform_sku(Edition.PRO), existing_cert=cert)
        return {
            "mode": snap.mode,
            "status_message": snap.status_message,
            "typing_assistance_enabled": snap.typing_assistance_enabled,
            "pro_features_enabled": snap.pro_features_enabled,
            "can_download_new_updates": snap.can_download_new_updates,
            "updates_expire_at": (snap.updates_expire_at.isoformat() if snap.updates_expire_at else None),
            "device_id_hash": self._device_id_hash,
            "certificate": cert.to_unsigned_dict() if cert is not None else None,
            "pricing": {
                "currency": self._pricing_config.primary_currency,
                "standard_quote_usd": std_q.final_amount_str,
                "standard_upgrade_type": std_q.upgrade_type.value,
                "pro_quote_usd": pro_q.final_amount_str,
                "pro_upgrade_type": pro_q.upgrade_type.value,
                "renewal_discount_pct": int(self._pricing_config.renewal_discount_fraction * 100),
                "regional_standard": {
                    k: f"{v:.2f}" for k, v in self._pricing_config.standard_regional_prices.items()
                },
                "regional_pro": {k: f"{v:.2f}" for k, v in self._pricing_config.pro_regional_prices.items()},
            },
        }

    def install_licence_certificate_json(self, certificate_json: str) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online(
            "licence.install_certificate_json",
            {"certificate_json": certificate_json},
        )
        if ipc_res is not None:
            return ipc_res
        cert = SignedLicenceCertificate.from_json(certificate_json)
        self._licence_service.save_and_activate_certificate(cert)
        return self.get_licence_state()

    def deactivate_device(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("licence.deactivate_device")
        if ipc_res is not None:
            return ipc_res
        self._licence_service.deactivate_current_device()
        return self.get_licence_state()


def _launch_native_fallback_ui(controller: SettingsController) -> int:
    """
    Launch a 10-Tab Native Window if PySide6-Essentials is not installed in the active
    developer environment, ensuring every customisation screen works out of the box.
    """
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("AutoCorrect Desktop — 10-Screen Settings & Customisation")
    root.geometry("920x640")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=12)

    for screen in SCREEN_NAMES:
        tab = ttk.Frame(notebook, padding=16)
        notebook.add(tab, text=screen)
        ttk.Label(
            tab,
            text=f"AutoCorrect Desktop — {screen}",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        if screen == "Dictionary":
            add_row = ttk.Frame(tab)
            add_row.pack(fill="x", pady=(6, 6))
            new_word_var = tk.StringVar()
            entry = ttk.Entry(add_row, textvariable=new_word_var)
            entry.pack(side="left", fill="x", expand=True)
            listbox = tk.Listbox(tab, height=12, activestyle="none")
            listbox.pack(fill="both", expand=True, pady=(4, 6))

            def refresh_list() -> None:
                listbox.delete(0, tk.END)
                for w in controller.list_custom_words():
                    listbox.insert(tk.END, w)

            def on_add() -> None:
                controller.add_custom_word(new_word_var.get())
                new_word_var.set("")
                refresh_list()

            def on_delete() -> None:
                sel = listbox.curselection()
                if sel:
                    controller.delete_custom_word(listbox.get(sel[0]))
                    refresh_list()

            ttk.Button(add_row, text="Add Word", command=on_add).pack(side="left", padx=(8, 0))
            ttk.Button(tab, text="Delete Selected Word", command=on_delete).pack(anchor="w")
            refresh_list()
        else:
            ov = controller.get_overview()
            ttk.Label(
                tab,
                text=f"Connected to local preferences & IPC ({ov.get('active_region')})",
            ).pack(anchor="w")

    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AutoCorrect Desktop Settings")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--headless-check", action="store_true")
    args = parser.parse_args(argv)

    from autocorrect.platform_paths import resolve_data_dir

    controller = SettingsController(resolve_data_dir(args.data_dir), use_memory_keyring=args.headless_check)
    if args.headless_check:
        summary = controller.get_settings_summary()
        print(f"Settings OK: {summary}")
        return 0

    try:
        from autocorrect.ui.qml_bridge import launch_pyside6_qml_ui

        return launch_pyside6_qml_ui(controller)
    except ImportError:
        try:
            return _launch_native_fallback_ui(controller)
        except Exception:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
