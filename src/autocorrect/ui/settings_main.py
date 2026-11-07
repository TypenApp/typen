"""
10-Screen Desktop Customisation Controller and On-Demand Subprocess Entry Point.
Communicates with `AutoCorrectDaemon` over authenticated `LocalIPCClient`
(Windows Named Pipes / Unix Domain Sockets) when the background service is running,
and seamlessly falls back to local stores in standalone/test mode.

Covers all 10 architecture screens:
1. Overview (Status, active language, LocalInsightsStore statistics)
2. General (Startup at login, global hotkeys, one-click Privacy Wipe)
3. Dictionary (Custom words, reverted Suggested Words, CSV/JSON import/export)
4. Languages (Regional English variants EN_GB/EN_US/EN_CA/EN_AU/UNIVERSAL & 6 Domain Packs)
5. Corrections (Sensitivity/aggressiveness, rejected pairs, preferred variants, punctuation/undo)
6. Intelligence (Layer 2 Local AI hardware/models & Layer 3 BYOK Cloud AI, OS Keyring, spend caps, Local-Only mode)
7. Profiles (Per-application typing & correction profiles)
8. Text Expansion (Custom snippets and `{{date}}`/`{{time}}` macros)
9. Updates (Independent App, Language Intelligence Library delta/rollback, and Local AI Model updates)
10. About (Version, licence, source and how to support the project)

Typen is free and open source: every screen is available to everyone.
"""

from __future__ import annotations

import argparse
import logging
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
from autocorrect.licensing.entitlement_manager import (
    DONATE_URL,
    GITHUB_REPO_URL,
    GITHUB_SPONSORS_URL,
    EntitlementManager,
)
from autocorrect.preferences import settings_schema
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.preferences.system_locale import detect_english_region
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
    "Language",
    "Corrections",
    "Dictionary",
    "Apps",
    "Text Expansion",
    "Intelligence",
    "Updates",
    "Feedback",
    "About",
)


def _bundled_manifest() -> dict[str, Any]:
    """
    The shipped `resources/en_base/manifest.json` (version, word_count, released_at),
    used for the offline fallbacks when the daemon is not running. Empty when unreadable.
    """
    try:
        import json

        from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR

        data = json.loads((DEFAULT_BUNDLED_DIR / "manifest.json").read_text(encoding="utf-8"))
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


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
        self._local_ai = LocalModelManager(is_pro_entitled=True)
        # Offline fallbacks read and write the same tables as the daemon.
        prefs = self._prefs
        self._profiles = ApplicationProfileManager(
            load=prefs.list_app_profiles, save=prefs.save_app_profile, delete=prefs.delete_app_profile
        )
        self._snippets = SnippetEngine(
            load=prefs.list_snippets, save=prefs.save_snippet, delete=prefs.delete_snippet
        )
        self._insights = LocalInsightsStore(
            enabled=bool(prefs.get_typed("insights_enabled")),
            retention_days=int(prefs.get_typed("insights_retention_days")),
            load=prefs.load_insights,
            save_day=None,  # read-only mirror of the daemon's counters
            prune=None,
            clear=prefs.clear_insights,
        )
        # Typen is free software: the entitlement manager always answers "allowed".
        self._entitlement_mgr = EntitlementManager()

    # =========================================================================
    # GENERIC SETTINGS (schema-driven; every screen's toggles go through here)
    # =========================================================================
    def get_settings_schema(self, group: str | None = None) -> list[dict[str, Any]]:
        return settings_schema.schema_as_dicts(group)

    def get_all_settings(self, group: str | None = None) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("settings.get_all", {"group": group} if group else {})
        if ipc_res is not None and isinstance(ipc_res.get("values"), dict):
            return dict(ipc_res["values"])
        return self._prefs.get_all_typed(group)

    def set_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        """Store (and, when the daemon is running, apply live) any schema keys in `values`."""
        clean = {k: v for k, v in values.items() if k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("settings.set", {"values": clean})
        if ipc_res is not None:
            self._prefs.reload_into_overlay()
            return dict(ipc_res.get("values") or self._prefs.get_all_typed())
        for key, value in clean.items():
            if key == "region":
                self._prefs.set_region_preference(str(settings_schema.coerce(key, value)))
            else:
                self._prefs.set_typed(key, value)
        return self._prefs.get_all_typed()

    def set_setting(self, key: str, value: Any) -> dict[str, Any]:
        return self.set_settings({key: value})

    def try_text(self, text: str) -> str:
        """Overview 'Try it': what the engine would make of `text` (daemon first, offline engine otherwise)."""
        ipc_res = self._call_ipc_if_online("corrections.try_text", {"text": text})
        if ipc_res is not None and "result" in ipc_res:
            return str(ipc_res["result"])
        return self._offline_try_text(text)

    def _offline_try_text(self, text: str) -> str:
        from autocorrect.core.engine import AutocorrectEngine
        from autocorrect.core.models import CorrectionFeatures
        from autocorrect.input.ports import KeyAction, KeyEvent
        from autocorrect.input.session_state import InputSessionManager
        from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager

        self._prefs.reload_into_overlay()
        rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
        try:
            engine = AutocorrectEngine(rm, preferences=self._prefs.overlay)
            session = InputSessionManager(engine=engine, active_region=self._prefs.overlay.active_region)
            session.configure_features(CorrectionFeatures.from_mapping(self._prefs.get_all_typed()))
            out: list[str] = []
            ts = 0.0
            for ch in text[:400]:
                ts += 80.0
                key = "Space" if ch == " " else ("Return" if ch == "\n" else ch)
                res = session.handle_key_event(
                    KeyEvent(key_name=key, char=ch, timestamp_ms=ts), suppress_delimiter_on_replace=True
                )
                if res.action == KeyAction.PASS_THROUGH:
                    out.append(ch)
                elif res.action == KeyAction.SUPPRESS_AND_INJECT and res.replacement_plan is not None:
                    for _ in range(res.replacement_plan.backspaces_to_send):
                        if out:
                            out.pop()
                    out.extend(res.replacement_plan.text_to_inject)
            return "".join(out)
        finally:
            rm.close()

    def _offline_pro_enabled(self) -> bool:
        """Feature-gate seam for the offline path; always True in Typen."""
        return self._entitlement_mgr.is_pro_enabled()

    def _offline_require_pro(self, feature: str) -> None:
        if not self._offline_pro_enabled():
            raise PermissionError(f"{feature} are not available in this build.")

    @property
    def preferences(self) -> SQLitePreferenceStore:
        return self._prefs

    @property
    def data_dir(self) -> Path:
        return self._data_dir

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
            # The daemon answered and *refused* (feature gate). Never fall back to
            # the offline path here, or the UI would silently bypass the gate.
            if "not available in this build" in str(exc):
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
        snap = self._entitlement_mgr.evaluate()
        ins = self._insights.get_summary()
        enabled_packs = list(self._prefs.get_typed("enabled_domain_packs"))
        stored_region = self._prefs.stored_region_name()
        bundle = _bundled_manifest()
        return {
            "app_version": APP_VERSION,
            "hooks_active": False,
            "hook_status": {
                "state": "inactive",
                "backend": "",
                "detail": "The background service is not running.",
                "remediation": "Start Typen (it normally launches at login).",
            },
            "is_paused": self._prefs.get_setting("is_paused", "false") == "true",
            "safe_mode": (self._data_dir / "safe_mode").exists(),
            "active_region": detect_english_region().name if stored_region == "AUTO" else stored_region,
            "hold_esc_seconds": float(self._prefs.get_typed("panic_hold_seconds")),
            "listening": None,
            "session": {"corrections": 0, "last_correction": None},
            "custom_word_count": len(self._prefs.list_custom_words()),
            "suggested_word_count": len(self._prefs.list_suggested_words()),
            "lexicon_word_count": int(bundle.get("word_count", 0) or 0),
            "resource_version": str(bundle.get("version", "")),
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

    def get_insights_daily(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("insights.get_daily")
        if ipc_res is not None:
            return ipc_res
        return {"days": self._insights.get_daily(), "retention_days": self._insights.retention_days}

    # =========================================================================
    # SCREEN 2: GENERAL
    # =========================================================================
    def get_general_settings(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("general.get_settings")
        if ipc_res is not None:
            return ipc_res
        out = self._prefs.get_all_typed("general")
        out["panic_hotkey_supported"] = False
        out["schema"] = settings_schema.schema_as_dicts("general")
        return out

    def update_general_settings(self, **changes: Any) -> dict[str, Any]:
        """Any general-group key (launch_at_login, hotkeys, Esc switch, toasts, theme, insights, updates)."""
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("general.update_settings", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
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
        dict_settings = self._prefs.get_all_typed("dictionary")
        return {
            "words": self._prefs.list_custom_words(),
            "suggested": self._prefs.list_suggested_words_detailed(
                min_reverts=int(dict_settings["suggest_after_reverts"]),
                repeated_threshold=(
                    int(dict_settings["learn_repeated_threshold"])
                    if dict_settings["learn_repeated_oov"]
                    else 0
                ),
            ),
            "settings": dict_settings,
            "schema": settings_schema.schema_as_dicts("dictionary"),
        }

    def update_dictionary_settings(self, **changes: Any) -> dict[str, Any]:
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("dictionary.update_settings", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
        return self.get_dictionary_state()

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
        lang = self._prefs.get_all_typed("language")
        enabled_set = set(lang["enabled_domain_packs"])
        stored = self._prefs.stored_region_name()
        system_region = detect_english_region().name
        return {
            "region_setting": stored,
            "active_region": system_region if stored == "AUTO" else stored,
            "system_region": system_region,
            "variant_enforcement": lang["variant_enforcement"],
            "uk_ize_spelling": lang["uk_ize_spelling"],
            "schema": settings_schema.schema_as_dicts("language"),
            "available_regions": [
                {"code": "AUTO", "name": "Follow system language"},
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

    def update_language_settings(self, **changes: Any) -> dict[str, Any]:
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("languages.update_settings", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
        return self.get_languages_state()

    def set_enabled_domain_packs(self, pack_ids: list[str] | set[str]) -> dict[str, Any]:
        norm = sorted({str(p).strip().lower() for p in pack_ids if str(p).strip()})
        ipc_res = self._call_ipc_if_online("languages.set_domain_packs", {"pack_ids": norm})
        if ipc_res is not None:
            return ipc_res
        if norm:
            self._offline_require_pro("Domain vocabulary packs")
        self._prefs.set_typed("enabled_domain_packs", norm)
        return self.get_languages_state()

    # =========================================================================
    # SCREEN 5: CORRECTIONS, SENSITIVITY, REJECTED & PREFERRED VARIANTS
    # =========================================================================
    def get_corrections_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("corrections.get_state")
        if ipc_res is not None:
            return ipc_res
        state: dict[str, Any] = self._prefs.get_all_typed("correction")
        state["rejected_corrections"] = self._prefs.list_rejected_corrections()
        state["preferred_variants"] = [
            {"source": k, "preferred": v} for k, v in self._prefs.list_preferred_variants().items()
        ]
        state["schema"] = settings_schema.schema_as_dicts("correction")
        state["effective"] = dict(state)
        return state

    def update_correction_features(self, **changes: Any) -> dict[str, Any]:
        """Any correction-group key (see `settings_schema.CORRECTION_KEYS`)."""
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("corrections.update_features", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
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
    def get_apps_state(self) -> dict[str, Any]:
        """Profiles plus the excluded / code process lists and (daemon only) the running apps."""
        ipc_res = self._call_ipc_if_online("profiles.list")
        if ipc_res is not None and isinstance(ipc_res.get("profiles"), list):
            return ipc_res
        apps = self._prefs.get_all_typed("apps")
        return {
            "profiles": [p.to_dict() for p in self._profiles.list_profiles()],
            "overridable_keys": list(settings_schema.PROFILE_OVERRIDABLE_KEYS),
            "schema": [s for s in settings_schema.schema_as_dicts() if s["profile_overridable"]],
            "excluded_processes": apps["excluded_processes"],
            "code_processes": apps["code_processes"],
            "browser_url_rules": apps["browser_url_rules"],
            "foreground_process": "",
            "running_apps": [],
        }

    def update_apps_settings(self, **changes: Any) -> dict[str, Any]:
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("profiles.update_settings", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
        return self.get_apps_state()

    def list_app_profiles(self) -> list[dict[str, Any]]:
        return list(self.get_apps_state()["profiles"])

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
        active_domain_packs: list[str] | set[str] | tuple[str, ...] = (),
        enable_auto_space_after_sentence: bool = True,
        overrides: dict[str, Any] | None = None,
        region: str = "",
    ) -> list[dict[str, Any]]:
        payload = {
            "app_identifier": app_identifier,
            "display_name": display_name,
            "enabled": enabled,
            "enable_punctuation_assist": enable_punctuation_assist,
            "enable_double_space_period": enable_double_space_period,
            "enable_auto_capitalise": enable_auto_capitalise,
            "enable_auto_space_after_sentence": enable_auto_space_after_sentence,
            "aggressiveness": aggressiveness,
            "active_domain_packs": list(active_domain_packs),
            "overrides": dict(overrides or {}),
            "region": region,
        }
        ipc_res = self._call_ipc_if_online("profiles.upsert", payload)
        if ipc_res is not None and isinstance(ipc_res.get("profiles"), list):
            return list(ipc_res["profiles"])
        self._offline_require_pro("Per-application profiles")
        self._profiles.set_profile(ApplicationProfile.from_dict(payload))
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
    def get_snippets_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("snippets.list")
        if ipc_res is not None and isinstance(ipc_res.get("snippets"), list):
            return ipc_res
        exp = self._prefs.get_all_typed("expansion")
        return {
            "snippets": [
                {"trigger": s.trigger, "expansion": s.expansion, "description": s.description}
                for s in self._snippets.list_snippets()
            ],
            "snippet_prefix": exp["snippet_prefix"],
            "snippet_case_matching": exp["snippet_case_matching"],
            "schema": settings_schema.schema_as_dicts("expansion"),
        }

    def update_snippet_settings(self, **changes: Any) -> dict[str, Any]:
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("snippets.update_settings", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
        return self.get_snippets_state()

    def list_snippets(self) -> list[dict[str, str]]:
        return list(self.get_snippets_state()["snippets"])

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
        snap = self._entitlement_mgr.evaluate()
        bundle = _bundled_manifest()
        return {
            "app": {
                "current_version": APP_VERSION,
                "released_at": APP_RELEASE_TIMESTAMP,
                "channel": self._prefs.get_typed("update_channel"),
                "check_on_launch": self._prefs.get_typed("updates_check_on_launch"),
                "auto_language_data": self._prefs.get_typed("updates_auto_language_data"),
            },
            "language_resources": {
                "active_version": str(bundle.get("version", "")),
                "schema_version": int(
                    bundle.get("schema_version", BINARY_SCHEMA_VERSION) or BINARY_SCHEMA_VERSION
                ),
                "released_at": str(bundle.get("released_at", APP_RELEASE_TIMESTAMP)),
                "word_count": int(bundle.get("word_count", 0) or 0),
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

    def update_updates_settings(self, **changes: Any) -> dict[str, Any]:
        params = {k: v for k, v in changes.items() if v is not None and k in settings_schema.SCHEMA_BY_KEY}
        ipc_res = self._call_ipc_if_online("updates.update_settings", params)
        if ipc_res is not None:
            return ipc_res
        self.set_settings(params)
        return self.get_updates_state()

    def rollback_language_resources(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("updates.rollback_resources")
        if ipc_res is not None:
            return ipc_res
        return self.get_updates_state()

    def check_for_updates(self) -> dict[str, Any]:
        """Check, then download and install when a signed newer build exists.

        The launch-time check stays check-only. This is the button.
        """
        checked = self._call_ipc_if_online("updates.check")
        if checked is None:
            return self.get_updates_state()
        app = checked.get("app") if isinstance(checked, dict) else None
        if isinstance(app, dict) and app.get("status") == "available":
            applied = self._call_ipc_if_online("updates.apply_app")
            if applied is not None:
                return applied
        return checked

    def apply_app_update(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("updates.apply_app")
        if ipc_res is not None:
            return ipc_res
        return self.get_updates_state()

    # =========================================================================
    # SCREEN 10: ABOUT & SUPPORT
    # =========================================================================
    def get_about_state(self) -> dict[str, Any]:
        ipc_res = self._call_ipc_if_online("about.get_state")
        if ipc_res is not None:
            return ipc_res
        snap = self._entitlement_mgr.evaluate()
        return {
            "mode": snap.mode,
            "status_message": snap.status_message,
            "typing_assistance_enabled": snap.typing_assistance_enabled,
            "pro_features_enabled": snap.pro_features_enabled,
            "app_version": APP_VERSION,
            "licence": "MIT",
            "source_url": GITHUB_REPO_URL,
            "donate_url": DONATE_URL,
            "sponsors_url": GITHUB_SPONSORS_URL,
        }

    def open_sponsors_page(self) -> str:
        """Open the official Typen GitHub Sponsors page in the user's default browser."""
        import webbrowser

        url = str(self.get_about_state().get("donate_url") or DONATE_URL)
        webbrowser.open(url)
        return url

    def open_source_repository(self) -> str:
        """Open the official Typen GitHub repository in the user's default browser."""
        import webbrowser

        url = str(self.get_about_state().get("source_url") or GITHUB_REPO_URL)
        webbrowser.open(url)
        return url


def _launch_native_fallback_ui(controller: SettingsController) -> int:
    """
    Launch a 10-Tab Native Window if PySide6-Essentials is not installed in the active
    developer environment, ensuring every customisation screen works out of the box.
    """
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Typen")
    root.geometry("920x640")
    # Never show Tk's stock feather: use the Typen mark (same drawing as the tray/app icon).
    try:
        from autocorrect.branding import draw_mark

        icon_file = controller.data_dir / "typen-window-icon-v2.png"
        draw_mark(256).save(icon_file)
        root.iconphoto(True, tk.PhotoImage(file=str(icon_file)))
    except Exception:
        logging.getLogger(__name__).debug("fallback window icon unavailable", exc_info=True)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=12)

    for screen in SCREEN_NAMES:
        tab = ttk.Frame(notebook, padding=16)
        notebook.add(tab, text=screen)
        ttk.Label(
            tab,
            text=f"Typen — {screen}",
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
                sel = listbox.curselection()  # type: ignore[no-untyped-call]
                if sel:
                    controller.delete_custom_word(listbox.get(sel[0]))
                    refresh_list()

            ttk.Button(add_row, text="Add Word", command=on_add).pack(side="left", padx=(8, 0))
            ttk.Button(tab, text="Delete Selected Word", command=on_delete).pack(anchor="w")
            refresh_list()
        elif screen == "About":
            about = controller.get_about_state()
            ttk.Label(
                tab,
                text=f"Typen v{about.get('app_version')} — {about.get('status_message')}",
                wraplength=820,
            ).pack(anchor="w", pady=(0, 6))
            ttk.Label(
                tab,
                text=f"Licence: {about.get('licence')}  •  Source: {about.get('source_url')}",
            ).pack(anchor="w", pady=(0, 4))
            ttk.Label(
                tab,
                text=f"GitHub Sponsors: {about.get('donate_url')}",
            ).pack(anchor="w", pady=(0, 12))
            btn_row = ttk.Frame(tab)
            btn_row.pack(anchor="w")
            ttk.Button(
                btn_row,
                text="Sponsor Typen on GitHub Sponsors",
                command=controller.open_sponsors_page,
            ).pack(side="left", padx=(0, 8))
            ttk.Button(
                btn_row,
                text="View Source on GitHub",
                command=controller.open_source_repository,
            ).pack(side="left")
        else:
            ov = controller.get_overview()
            ttk.Label(
                tab,
                text=f"Connected to local preferences & IPC ({ov.get('active_region')})",
            ).pack(anchor="w")

    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Typen Settings")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--headless-check", action="store_true")
    parser.add_argument("--screen", default=None, help="Screen to open on (e.g. overview, feedback)")
    args = parser.parse_args(argv)

    from autocorrect.platform_paths import resolve_data_dir

    controller = SettingsController(resolve_data_dir(args.data_dir), use_memory_keyring=args.headless_check)
    if args.headless_check:
        summary = controller.get_settings_summary()
        print(f"Settings OK: {summary}")
        return 0

    try:
        from autocorrect.ui.qml_bridge import launch_pyside6_qml_ui

        return launch_pyside6_qml_ui(controller, initial_screen=args.screen)
    except ImportError as exc:
        logging.getLogger(__name__).warning(
            "PySide6/QML Settings window unavailable (%s); using the native fallback window", exc
        )
        try:
            return _launch_native_fallback_ui(controller)
        except Exception:
            logging.getLogger(__name__).exception("native fallback Settings window failed")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
