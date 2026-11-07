"""
Authenticated Local IPC Server (`LocalIPCServer`).
Runs on a lightweight background daemon thread inside `AutoCorrectDaemon`.
Handles requests from the out-of-process Settings UI (`autocorrect-settings`)
across all 10 customisation screens without the UI ever opening SQLite writes,
`mmap` lexicon files, or OS keyboard hooks directly.
"""

from __future__ import annotations

import hmac
import json
import os
import stat
import threading
import time
from decimal import Decimal
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autocorrect.ai.provider_manager import AIProviderId
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR
from autocorrect.ipc.protocol import (
    IPC_ENDPOINT_FILENAME,
    IPC_PROTOCOL_VERSION,
    IPC_TOKEN_FILENAME,
    IPCRequest,
    IPCResponse,
    compute_default_ipc_address,
    create_and_persist_auth_token,
)
from autocorrect.licensing.entitlement_manager import (
    DONATE_URL,
    GITHUB_REPO_URL,
    GITHUB_SPONSORS_URL,
)
from autocorrect.preferences import settings_schema
from autocorrect.preferences.system_locale import detect_english_region
from autocorrect.productivity.app_profiles import ApplicationProfile
from autocorrect.version import APP_RELEASE_TIMESTAMP, APP_VERSION, BINARY_SCHEMA_VERSION

if TYPE_CHECKING:
    from autocorrect.daemon.app import AutoCorrectDaemon

AVAILABLE_DOMAIN_PACK_METADATA: list[dict[str, str]] = [
    {
        "id": "programming",
        "name": "Programming & DevOps",
        "description": "Cloud-native, languages, frameworks, CLI tooling, and engineering terminology.",
    },
    {
        "id": "medicine",
        "name": "Medicine & Clinical",
        "description": "Anatomy, pharmacology, pathology, diagnostics, and clinical nomenclature.",
    },
    {
        "id": "finance",
        "name": "Finance & Accounting",
        "description": "Corporate finance, capital markets, IFRS/GAAP accounting, and fintech terms.",
    },
    {
        "id": "law",
        "name": "Law & Legal Practice",
        "description": "Litigation, contracts, jurisprudence, Latin maxims, and regulatory terms.",
    },
    {
        "id": "business",
        "name": "Business & Operations",
        "description": "Enterprise strategy, project management, procurement, and executive comms.",
    },
    {
        "id": "academic",
        "name": "Academic & Research",
        "description": "Peer-reviewed publishing, methodology, statistics, and humanities terminology.",
    },
]


class LocalIPCServer:
    """
    Thread-safe Local IPC Server exposing the 10-screen configuration surface
    over Windows Named Pipes (`AF_PIPE`) or Unix Domain Sockets (`AF_UNIX`).
    """

    def __init__(self, daemon: AutoCorrectDaemon, data_dir: Path) -> None:
        self._daemon = daemon
        self._data_dir = data_dir
        self._lock = threading.RLock()
        self._running = False
        self._auth_token = ""
        self._listener: Listener | None = None
        self._address: str | tuple[str, int] = ""
        self._family: str = ""
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def address(self) -> str | tuple[str, int]:
        return self._address

    @property
    def family(self) -> str:
        return self._family

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._auth_token = create_and_persist_auth_token(self._data_dir)
            addr, family = compute_default_ipc_address(self._data_dir)

            if family == "AF_UNIX" and os.path.exists(addr):
                try:
                    os.unlink(addr)
                except OSError:
                    pass

            try:
                self._listener = Listener(address=addr, family=family)
                self._address = addr
                self._family = family
                if family == "AF_UNIX" and os.path.exists(addr):
                    try:
                        os.chmod(addr, stat.S_IRUSR | stat.S_IWUSR)
                    except OSError:
                        pass
            except Exception:
                # Fallback to ephemeral localhost socket only if OS pipe/unix socket creation is restricted
                self._listener = Listener(address=("127.0.0.1", 0), family="AF_INET")
                self._address = self._listener.address  # type: ignore[assignment]
                self._family = "AF_INET"

            endpoint_meta = {
                "protocol_version": IPC_PROTOCOL_VERSION,
                "family": self._family,
                "address": (list(self._address) if isinstance(self._address, tuple) else self._address),
                "pid": os.getpid(),
            }
            ep_path = self._data_dir / IPC_ENDPOINT_FILENAME
            ep_path.write_text(json.dumps(endpoint_meta, indent=2), encoding="utf-8")
            try:
                os.chmod(ep_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

            self._running = True
            self._thread = threading.Thread(
                target=self._accept_loop,
                name="AutoCorrect-LocalIPCServer",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            addr = self._address
            family = self._family
            listener = self._listener
            self._listener = None

        # Wake up blocking accept() with a dummy connection if needed
        try:
            if addr and family:
                with Client(address=addr, family=family):
                    pass
        except Exception:
            pass

        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

        if family == "AF_UNIX" and isinstance(addr, str) and os.path.exists(addr):
            try:
                os.unlink(addr)
            except OSError:
                pass
        for fname in (IPC_ENDPOINT_FILENAME, IPC_TOKEN_FILENAME):
            try:
                (self._data_dir / fname).unlink(missing_ok=True)
            except OSError:
                pass

    def _accept_loop(self) -> None:
        while self._running and self._listener is not None:
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                if not self._running:
                    break
                continue
            if not self._running:
                try:
                    conn.close()
                except Exception:
                    pass
                break
            client_thread = threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            )
            client_thread.start()

    def _handle_connection(self, conn: Connection) -> None:
        try:
            while self._running:
                try:
                    raw = conn.recv_bytes()
                except EOFError:
                    break
                resp = self.handle_raw_request(raw)
                conn.send_bytes(resp.to_json_bytes())
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def handle_raw_request(self, raw: bytes) -> IPCResponse:
        """Parse, authenticate, and dispatch a single raw IPC request."""
        try:
            req = IPCRequest.from_json_bytes(raw)
        except Exception as exc:
            return IPCResponse(
                request_id="",
                ok=False,
                error=f"Malformed IPC request: {exc}",
            )

        if req.protocol_version != IPC_PROTOCOL_VERSION:
            return IPCResponse(
                request_id=req.request_id,
                ok=False,
                error=f"Unsupported IPC protocol_version '{req.protocol_version}' (expected '{IPC_PROTOCOL_VERSION}')",
            )

        if not self._auth_token or not hmac.compare_digest(req.auth_token, self._auth_token):
            return IPCResponse(
                request_id=req.request_id,
                ok=False,
                error="Unauthorized: invalid IPC authentication token",
            )

        try:
            with self._lock:
                result = self._dispatch(req.method, req.params)
            return IPCResponse(
                request_id=req.request_id,
                ok=True,
                result=result,
            )
        except Exception as exc:
            return IPCResponse(
                request_id=req.request_id,
                ok=False,
                error=str(exc),
            )

    def _require_pro(self, feature: str) -> None:
        """Feature gate seam. Typen is free software, so the entitlement manager always allows."""
        if not self._daemon.entitlement_manager.is_pro_enabled():
            raise PermissionError(f"{feature} are not available in this build.")

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        d = self._daemon
        prefs = d.preference_store

        # --- 1. Overview & Daemon Control ------------------------------------
        if method == "system.get_overview":
            snap = d.entitlement_manager.evaluate()
            ins = d.insights.get_summary()
            bundle = d.resource_manager.active_bundle
            focus = d.focus_monitor.last_focus
            last = d.last_correction
            return {
                "app_version": APP_VERSION,
                "hooks_active": d.hooks_active,
                "hook_status": d.hook_status.to_dict(),
                "is_paused": d.session.is_paused,
                "safe_mode": d.in_safe_mode,
                "hold_esc_seconds": d.kill_switch.hold_seconds,
                "listening": {
                    "process_name": focus.process_name if focus else "",
                    "window_title": focus.window_title if focus else "",
                    "is_excluded": bool(focus.is_excluded_app) if focus else False,
                    "is_code_or_terminal": bool(focus.is_terminal_or_code) if focus else False,
                    "is_secure": bool(focus.is_password_or_secure) if focus else False,
                },
                "session": {
                    "corrections": d.session_correction_count,
                    "last_correction": (
                        {
                            "original": last[0],
                            "replacement": last[1],
                            "reason": last[2],
                            "age_s": max(0.0, time.time() - last[3]),
                        }
                        if last
                        else None
                    ),
                },
                "active_region": prefs.overlay.active_region.name or "EN_GB",
                "custom_word_count": len(prefs.list_custom_words()),
                "suggested_word_count": len(prefs.list_suggested_words()),
                "lexicon_word_count": bundle.lexicon.word_count,
                "resource_version": bundle.version,
                "enabled_domain_packs": sorted(bundle.domain_packs.keys()),
                "entitlement": {
                    "mode": snap.mode,
                    "typing_assistance_enabled": snap.typing_assistance_enabled,
                    "pro_features_enabled": snap.pro_features_enabled,
                    "can_download_new_updates": snap.can_download_new_updates,
                    "updates_expire_at": (
                        snap.updates_expire_at.isoformat() if snap.updates_expire_at else None
                    ),
                    "status_message": snap.status_message,
                },
                "insights": {
                    "enabled": d.insights.enabled,
                    "words_evaluated": ins.words_evaluated,
                    "spelling_corrections": ins.spelling_corrections,
                    "contextual_corrections": ins.contextual_corrections,
                    "punctuation_and_caps_fixes": ins.punctuation_and_caps_fixes,
                    "snippets_expanded": ins.snippets_expanded,
                    "corrections_undone": ins.corrections_undone,
                    "keystrokes_saved": ins.keystrokes_saved,
                },
            }

        if method == "system.set_paused":
            paused = bool(params.get("paused", False))
            d.set_paused(paused)
            return {
                "is_paused": d.session.is_paused,
                "hooks_active": d.hooks_active,
                "hook_status": d.hook_status.to_dict(),
                "safe_mode": d.in_safe_mode,
            }

        if method == "system.get_health":
            return d.health_snapshot()

        if method == "system.shutdown":
            d.request_shutdown()
            return {"ok": True}

        if method == "insights.set_enabled":
            enabled = bool(params.get("enabled", True))
            if enabled:
                self._require_pro("Local typing insights")
            d.apply_settings({"insights_enabled": enabled})
            return {"enabled": d.insights.enabled}

        if method == "insights.reset":
            d.insights.reset()
            return {"ok": True}

        if method == "insights.get_daily":
            return {"days": d.insights.get_daily(), "retention_days": d.insights.retention_days}

        # --- 2. Settings (schema-driven) & Privacy Wipe ----------------------
        if method == "settings.schema":
            group = params.get("group")
            return {"schema": settings_schema.schema_as_dicts(str(group) if group else None)}

        if method == "settings.get_all":
            group = params.get("group")
            return {
                "values": prefs.get_all_typed(str(group) if group else None),
                "schema": settings_schema.schema_as_dicts(str(group) if group else None),
            }

        if method == "settings.set":
            changes = params.get("values")
            if not isinstance(changes, dict):
                changes = {k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY}
            applied = d.apply_settings(changes)
            return {"applied": applied, "values": prefs.get_all_typed()}

        if method == "general.get_settings":
            out = prefs.get_all_typed("general")
            out["panic_hold_seconds"] = d.kill_switch.hold_seconds
            out["panic_hotkey_supported"] = d.kill_switch.is_supported
            out["schema"] = settings_schema.schema_as_dicts("general")
            return out

        if method == "general.update_settings":
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("general.get_settings", {})

        if method == "general.privacy_wipe":
            prefs.clear_all_preferences()
            d.insights.reset()
            d.apply_global_correction_settings()
            return {"wiped": True, "custom_word_count": 0}

        # --- 3. Custom Dictionary & Suggested Words --------------------------
        if method == "dictionary.get_state":
            dict_settings = prefs.get_all_typed("dictionary")
            return {
                "words": prefs.list_custom_words(),
                "suggested": prefs.list_suggested_words_detailed(
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

        if method == "dictionary.update_settings":
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("dictionary.get_state", {})

        if method == "dictionary.add_word":
            word = str(params.get("word", "")).strip()
            category = str(params.get("category", "user")).strip() or "user"
            if word and len(word) <= 64 and " " not in word:
                prefs.add_custom_word(word, category=category)
            return self._dispatch("dictionary.get_state", {})

        if method == "dictionary.remove_word":
            word = str(params.get("word", "")).strip()
            if word:
                prefs.remove_custom_word(word)
            return self._dispatch("dictionary.get_state", {})

        if method == "dictionary.accept_suggested":
            word = str(params.get("word", "")).strip()
            if word:
                prefs.accept_suggested_word(word)
            return self._dispatch("dictionary.get_state", {})

        if method == "dictionary.dismiss_suggested":
            word = str(params.get("word", "")).strip()
            if word:
                prefs.dismiss_suggested_word(word)
            return self._dispatch("dictionary.get_state", {})

        if method == "dictionary.export_csv":
            return {"csv": prefs.export_custom_words_csv()}

        if method == "dictionary.import_csv":
            csv_text = str(params.get("csv", ""))
            imported = prefs.import_custom_words_csv(csv_text)
            state = self._dispatch("dictionary.get_state", {})
            state["imported_count"] = imported
            return state

        if method == "dictionary.export_json":
            return {"json": prefs.export_json()}

        if method == "dictionary.import_json":
            json_text = str(params.get("json", ""))
            prefs.import_json(json_text)
            d.session.set_active_region(prefs.overlay.active_region)
            return self._dispatch("dictionary.get_state", {})

        # --- 4. Languages & Domain Vocabulary Packs --------------------------
        if method == "languages.get_state":
            bundle = d.resource_manager.active_bundle
            active_packs = set(bundle.domain_packs.keys())
            packs_dir = bundle.bundle_dir / "packs"
            if not packs_dir.exists():
                packs_dir = DEFAULT_BUNDLED_DIR / "packs"

            packs_info: list[dict[str, Any]] = []
            for meta in AVAILABLE_DOMAIN_PACK_METADATA:
                pid = meta["id"]
                word_cnt = 0
                typo_cnt = 0
                pfile = packs_dir / f"{pid}.pack.json"
                if pfile.exists():
                    try:
                        raw = json.loads(pfile.read_text(encoding="utf-8"))
                        word_cnt = len(raw.get("words", {}))
                        typo_cnt = len(raw.get("direct_typos", {}))
                    except Exception:
                        pass
                packs_info.append(
                    {
                        "id": pid,
                        "name": meta["name"],
                        "description": meta["description"],
                        "enabled": pid in active_packs,
                        "word_count": word_cnt,
                        "typo_count": typo_cnt,
                    }
                )

            lang_settings = prefs.get_all_typed("language")
            return {
                "region_setting": prefs.stored_region_name(),
                "active_region": d.resolved_region_name(),
                "system_region": detect_english_region().name,
                "variant_enforcement": lang_settings["variant_enforcement"],
                "uk_ize_spelling": lang_settings["uk_ize_spelling"],
                "schema": settings_schema.schema_as_dicts("language"),
                "available_regions": [
                    {
                        "code": "AUTO",
                        "name": "Follow system language",
                        "examples": f"Currently {str(detect_english_region().name).replace('_', '-')}",
                    },
                    {
                        "code": "EN_GB",
                        "name": "British English (UK)",
                        "examples": "colour, organise, centre, programme",
                    },
                    {
                        "code": "EN_US",
                        "name": "American English (US)",
                        "examples": "color, organize, center, program",
                    },
                    {
                        "code": "EN_CA",
                        "name": "Canadian English (CA)",
                        "examples": "colour, organize, centre, analyze",
                    },
                    {
                        "code": "EN_AU",
                        "name": "Australian English (AU)",
                        "examples": "colour, organise, centre, labour",
                    },
                    {
                        "code": "UNIVERSAL",
                        "name": "Universal English (Accept All Variants)",
                        "examples": "Both colour & color accepted as valid",
                    },
                ],
                "domain_packs": packs_info,
                "pro_enabled": d.entitlement_manager.is_pro_enabled(),
            }

        if method == "languages.set_region":
            region_code = str(params.get("region", "AUTO"))
            d.apply_settings({"region": region_code})
            return self._dispatch("languages.get_state", {})

        if method == "languages.update_settings":
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("languages.get_state", {})

        if method == "languages.set_domain_packs":
            raw_packs = params.get("pack_ids", [])
            pack_set = {str(p).strip().lower() for p in raw_packs if str(p).strip()}
            if pack_set:
                self._require_pro("Domain vocabulary packs")
            d.apply_settings({"enabled_domain_packs": sorted(pack_set)})
            return self._dispatch("languages.get_state", {})

        # --- 5. Corrections, Sensitivity, Rejected & Preferred Variants ------
        if method == "corrections.get_state":
            state = prefs.get_all_typed("correction")
            state["rejected_corrections"] = prefs.list_rejected_corrections()
            state["preferred_variants"] = [
                {"source": k, "preferred": v} for k, v in prefs.list_preferred_variants().items()
            ]
            state["schema"] = settings_schema.schema_as_dicts("correction")
            state["effective"] = d.session.features.as_dict()
            return state

        if method == "corrections.update_features":
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("corrections.get_state", {})

        if method == "corrections.try_text":
            # Overview "Try it" field: evaluate a sentence offline, never touching the real session.
            return {"result": d.try_text(str(params.get("text", "")))}

        if method == "corrections.add_rejected":
            orig = str(params.get("original", "")).strip()
            cand = str(params.get("candidate", "")).strip()
            if orig and cand:
                prefs.add_rejected_correction(orig, cand)
            return self._dispatch("corrections.get_state", {})

        if method == "corrections.remove_rejected":
            orig = str(params.get("original", "")).strip()
            cand = str(params.get("candidate", "")).strip()
            if orig and cand:
                prefs.remove_rejected_correction(orig, cand)
            return self._dispatch("corrections.get_state", {})

        if method == "corrections.set_preferred_variant":
            src = str(params.get("source", "")).strip()
            pref = str(params.get("preferred", "")).strip()
            if src and pref:
                prefs.set_preferred_variant(src, pref)
            return self._dispatch("corrections.get_state", {})

        if method == "corrections.remove_preferred_variant":
            src = str(params.get("source", "")).strip()
            if src:
                prefs.remove_preferred_variant(src)
            return self._dispatch("corrections.get_state", {})

        # --- 6. Pro Intelligence (Local AI & BYOK Cloud AI) ------------------
        if method == "ai.get_state":
            hw = d.local_ai.detect_hardware_profile()
            now = time.time()
            day_usage = d.usage_tracker.get_summary_since(now - 86400.0)
            month_usage = d.usage_tracker.get_summary_since(now - 30 * 86400.0)
            return {
                "pro_enabled": d.entitlement_manager.is_pro_enabled(),
                "local_ai": {
                    "model_loaded": d.local_ai.is_model_loaded,
                    "cpu_cores": hw.cpu_cores,
                    "total_ram_mb": hw.total_ram_mb,
                    "accelerator": hw.accelerator,
                    "recommended_model_id": hw.recommended_model_id,
                    "pause_pill_enabled": prefs.get_setting("pause_pill_enabled", "true") == "true",
                },
                "byok": {
                    "local_only_mode": d.spending_controller.local_only_mode,
                    "global_cloud_consent": d.byok_manager.global_cloud_consent,
                    "daily_limit_usd": prefs.get_setting("daily_limit_usd", "2.00"),
                    "monthly_limit_usd": prefs.get_setting("monthly_limit_usd", "15.00"),
                    "active_provider": prefs.get_setting("active_ai_provider", "openai"),
                    "active_model": prefs.get_setting("active_ai_model", "gpt-4o-mini"),
                    "providers": {
                        p.value: {
                            "has_key": d.api_key_manager.has_api_key(p.value),
                        }
                        for p in AIProviderId
                    },
                    "usage_24h": {
                        "requests": day_usage.total_requests,
                        "prompt_tokens": day_usage.prompt_tokens,
                        "completion_tokens": day_usage.completion_tokens,
                        "estimated_cost_usd": str(day_usage.estimated_cost_usd),
                    },
                    "usage_30d": {
                        "requests": month_usage.total_requests,
                        "prompt_tokens": month_usage.prompt_tokens,
                        "completion_tokens": month_usage.completion_tokens,
                        "estimated_cost_usd": str(month_usage.estimated_cost_usd),
                    },
                },
            }

        if method == "ai.set_api_key":
            provider = str(params.get("provider", "")).strip().lower()
            api_key = str(params.get("api_key", "")).strip()
            if not api_key:
                d.api_key_manager.delete_api_key(provider)
            else:
                if not d.api_key_manager.validate_key_format(provider, api_key):
                    raise ValueError(f"Invalid API key format for provider '{provider}'")
                d.api_key_manager.set_api_key(provider, api_key)
            return self._dispatch("ai.get_state", {})

        if method == "ai.update_settings":
            if "local_only_mode" in params:
                lom = bool(params["local_only_mode"])
                d.spending_controller.set_local_only_mode(lom)
                prefs.set_setting("local_only_mode", "true" if lom else "false")
            if "global_cloud_consent" in params:
                consent = bool(params["global_cloud_consent"])
                d.byok_manager.set_global_cloud_consent(consent)
                prefs.set_setting("global_cloud_consent", "true" if consent else "false")
            if "pause_pill_enabled" in params:
                prefs.set_setting(
                    "pause_pill_enabled",
                    "true" if params["pause_pill_enabled"] else "false",
                )
            if "daily_limit_usd" in params or "monthly_limit_usd" in params:
                d_str = str(params.get("daily_limit_usd", prefs.get_setting("daily_limit_usd", "2.00")))
                m_str = str(
                    params.get(
                        "monthly_limit_usd",
                        prefs.get_setting("monthly_limit_usd", "15.00"),
                    )
                )
                d_dec = Decimal(d_str)
                m_dec = Decimal(m_str)
                d.spending_controller.set_limits(d_dec, m_dec)
                prefs.set_setting("daily_limit_usd", f"{d_dec:.2f}")
                prefs.set_setting("monthly_limit_usd", f"{m_dec:.2f}")
            if "active_provider" in params:
                prefs.set_setting("active_ai_provider", str(params["active_provider"]))
            if "active_model" in params:
                prefs.set_setting("active_ai_model", str(params["active_model"]))
            if params.get("load_local_model"):
                d.local_ai.load_model()
            elif params.get("unload_local_model"):
                d.local_ai.unload_model()
            return self._dispatch("ai.get_state", {})

        # --- 7. Application-Specific Profiles --------------------------------
        if method == "profiles.list":
            focus = d.focus_monitor.last_focus
            apps_settings = prefs.get_all_typed("apps")
            return {
                "profiles": [p.to_dict() for p in d.app_profiles.list_profiles()],
                "overridable_keys": list(settings_schema.PROFILE_OVERRIDABLE_KEYS),
                "schema": [s for s in settings_schema.schema_as_dicts() if s["profile_overridable"]],
                "excluded_processes": apps_settings["excluded_processes"],
                "code_processes": apps_settings["code_processes"],
                "browser_url_rules": apps_settings["browser_url_rules"],
                "foreground_process": (focus.process_name if focus else ""),
                "running_apps": d.list_running_apps(),
            }

        if method == "profiles.upsert":
            self._require_pro("Per-application profiles")
            app_id = str(params.get("app_identifier", "")).strip().lower()
            if not app_id:
                raise ValueError("app_identifier is required")
            prof = ApplicationProfile.from_dict(dict(params, app_identifier=app_id))
            d.app_profiles.set_profile(prof)
            d._reapply_features()
            return self._dispatch("profiles.list", {})

        if method == "profiles.delete":
            app_id = str(params.get("app_identifier", "")).strip().lower()
            if app_id:
                d.app_profiles.remove_profile(app_id)
                d._reapply_features()
            return self._dispatch("profiles.list", {})

        if method == "profiles.update_settings":
            # excluded_processes / code_processes / browser_url_rules
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("profiles.list", {})

        # --- 8. Text Expansion Snippets --------------------------------------
        if method == "snippets.list":
            exp_settings = prefs.get_all_typed("expansion")
            return {
                "snippets": [
                    {
                        "trigger": s.trigger,
                        "expansion": s.expansion,
                        "description": s.description,
                    }
                    for s in d.snippet_engine.list_snippets()
                ],
                "snippet_prefix": exp_settings["snippet_prefix"],
                "snippet_case_matching": exp_settings["snippet_case_matching"],
                "schema": settings_schema.schema_as_dicts("expansion"),
            }

        if method == "snippets.update_settings":
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("snippets.list", {})

        if method == "snippets.upsert":
            self._require_pro("Text-expansion snippets")
            trigger = str(params.get("trigger", "")).strip()
            expansion = str(params.get("expansion", ""))
            desc = str(params.get("description", "")).strip()
            d.snippet_engine.add_snippet(trigger=trigger, expansion=expansion, description=desc)
            return self._dispatch("snippets.list", {})

        if method == "snippets.delete":
            trigger = str(params.get("trigger", "")).strip()
            if trigger:
                d.snippet_engine.remove_snippet(trigger)
            return self._dispatch("snippets.list", {})

        # --- 9. Independent Updates (App, Language Resources, Models) --------
        if method == "updates.get_state":
            bundle = d.resource_manager.active_bundle
            snap = d.entitlement_manager.evaluate()
            hw = d.local_ai.detect_hardware_profile()
            app_update = d.app_update_coordinator.snapshot()
            return {
                "app": {
                    "current_version": APP_VERSION,
                    "released_at": APP_RELEASE_TIMESTAMP,
                    "channel": prefs.get_typed("update_channel"),
                    "check_on_launch": prefs.get_typed("updates_check_on_launch"),
                    "auto_language_data": prefs.get_typed("updates_auto_language_data"),
                    "status": app_update.get("status", "idle"),
                    "available_version": app_update.get("available_version"),
                    "release_tag": app_update.get("release_tag"),
                    "signed": bool(app_update.get("signed")),
                    "download_progress": float(app_update.get("download_progress") or 0),
                    "error": app_update.get("error"),
                    "reason": app_update.get("reason"),
                    "checked_at": app_update.get("checked_at"),
                    "download_page_url": app_update.get("download_page_url")
                    or "https://typen.org/download",
                },
                "language_resources": {
                    "active_version": bundle.version,
                    "schema_version": BINARY_SCHEMA_VERSION,
                    "released_at": bundle.released_at,
                    "word_count": bundle.lexicon.word_count,
                    "bundle_dir": str(bundle.bundle_dir),
                },
                "local_models": {
                    "recommended_model_id": hw.recommended_model_id,
                    "accelerator": hw.accelerator,
                    "is_loaded": d.local_ai.is_model_loaded,
                },
                "entitlement": {
                    "can_download_new_updates": snap.can_download_new_updates,
                    "updates_expire_at": (
                        snap.updates_expire_at.isoformat() if snap.updates_expire_at else None
                    ),
                },
            }

        if method == "updates.check":
            d.app_update_coordinator.check()
            return self._dispatch("updates.get_state", {})

        if method == "updates.apply_app":
            d.app_update_coordinator.apply()
            return self._dispatch("updates.get_state", {})

        if method == "updates.update_settings":
            d.apply_settings({k: v for k, v in params.items() if k in settings_schema.SCHEMA_BY_KEY})
            return self._dispatch("updates.get_state", {})

        if method == "updates.rollback_resources":
            d.resource_updater.rollback_to_last_known_good()
            return self._dispatch("updates.get_state", {})

        # --- 10. About & Support --------------------------------------------
        if method == "about.get_state":
            snap = d.entitlement_manager.evaluate()
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

        raise ValueError(f"Unknown IPC method: '{method}'")
