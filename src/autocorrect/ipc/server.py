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
from autocorrect.licensing.entitlement_manager import DONATE_URL
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
        """Feature gate seam. Tact is free software, so the entitlement manager always allows."""
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
            return {
                "app_version": APP_VERSION,
                "hooks_active": d.hooks_active,
                "hook_status": d.hook_status.to_dict(),
                "is_paused": d.session.is_paused,
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
            d.session.set_paused(paused)
            return {"is_paused": d.session.is_paused, "hooks_active": d.hooks_active}

        if method == "insights.set_enabled":
            enabled = bool(params.get("enabled", True))
            if enabled:
                self._require_pro("Local typing insights")
            d.insights.set_enabled(enabled)
            return {"enabled": d.insights.enabled}

        if method == "insights.reset":
            d.insights.reset()
            return {"ok": True}

        # --- 2. General Settings & Privacy Wipe ------------------------------
        if method == "general.get_settings":
            return {
                "launch_at_login": prefs.get_setting("launch_at_login", "false") == "true",
                "show_tray_icon": prefs.get_setting("show_tray_icon", "true") == "true",
                "rewrite_hotkey": prefs.get_setting("rewrite_hotkey", "Ctrl+Shift+R"),
                "pause_hotkey": prefs.get_setting("pause_hotkey", "Ctrl+Alt+P"),
                "settings_hotkey": prefs.get_setting("settings_hotkey", "Ctrl+Alt+,"),
            }

        if method == "general.update_settings":
            if "launch_at_login" in params:
                from autocorrect.daemon.startup import StartupManager

                enabled = bool(params["launch_at_login"])
                prefs.set_setting("launch_at_login", "true" if enabled else "false")
                if not d.dry_run_hooks:
                    StartupManager.set_launch_at_login(enabled)
            if "show_tray_icon" in params:
                prefs.set_setting("show_tray_icon", "true" if params["show_tray_icon"] else "false")
            for hk_key in ("rewrite_hotkey", "pause_hotkey", "settings_hotkey"):
                if hk_key in params and str(params[hk_key]).strip():
                    prefs.set_setting(hk_key, str(params[hk_key]).strip())
            return self._dispatch("general.get_settings", {})

        if method == "general.privacy_wipe":
            prefs.clear_all_preferences()
            d.insights.reset()
            return {"wiped": True, "custom_word_count": 0}

        # --- 3. Custom Dictionary & Suggested Words --------------------------
        if method == "dictionary.get_state":
            return {
                "words": prefs.list_custom_words(),
                "suggested": prefs.list_suggested_words(),
            }

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

            return {
                "active_region": prefs.overlay.active_region.name or "EN_GB",
                "available_regions": [
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
                        "examples": "colour, organize, centre,alyze",
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
            region_code = str(params.get("region", "EN_GB"))
            prefs.set_region_preference(region_code)
            d.session.set_active_region(prefs.overlay.active_region)
            return self._dispatch("languages.get_state", {})

        if method == "languages.set_domain_packs":
            raw_packs = params.get("pack_ids", [])
            pack_set = {str(p).strip().lower() for p in raw_packs if str(p).strip()}
            if pack_set:
                self._require_pro("Domain vocabulary packs")
            d.set_user_domain_packs(pack_set)
            prefs.set_setting("enabled_domain_packs", ",".join(sorted(pack_set)))
            return self._dispatch("languages.get_state", {})

        # --- 5. Corrections, Sensitivity, Rejected & Preferred Variants ------
        if method == "corrections.get_state":
            return {
                "enable_punctuation_assist": prefs.get_setting("enable_punctuation_assist", "true") == "true",
                "enable_double_space_period": prefs.get_setting("enable_double_space_period", "true")
                == "true",
                "enable_auto_capitalise": prefs.get_setting("enable_auto_capitalise", "true") == "true",
                "aggressiveness": float(prefs.get_setting("aggressiveness", "1.0")),
                "rejected_corrections": prefs.list_rejected_corrections(),
                "preferred_variants": [
                    {"source": k, "preferred": v} for k, v in prefs.list_preferred_variants().items()
                ],
            }

        if method == "corrections.update_features":
            punct = params.get("enable_punctuation_assist")
            dbl = params.get("enable_double_space_period")
            cap = params.get("enable_auto_capitalise")
            agg = params.get("aggressiveness")

            if punct is not None:
                prefs.set_setting("enable_punctuation_assist", "true" if punct else "false")
            if dbl is not None:
                prefs.set_setting("enable_double_space_period", "true" if dbl else "false")
            if cap is not None:
                prefs.set_setting("enable_auto_capitalise", "true" if cap else "false")
            if agg is not None:
                agg_val = max(0.5, min(1.5, float(agg)))
                prefs.set_setting("aggressiveness", f"{agg_val:.2f}")

            state = self._dispatch("corrections.get_state", {})
            d.session.configure_features(
                enable_punctuation_assist=bool(state["enable_punctuation_assist"]),
                enable_double_space_period=bool(state["enable_double_space_period"]),
                enable_auto_capitalise=bool(state["enable_auto_capitalise"]),
                aggressiveness=float(state["aggressiveness"]),
            )
            return state

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
            return {
                "profiles": [
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
                    for p in d.app_profiles.list_profiles()
                ]
            }

        if method == "profiles.upsert":
            self._require_pro("Per-application profiles")
            app_id = str(params.get("app_identifier", "")).strip().lower()
            if not app_id:
                raise ValueError("app_identifier is required")
            prof = ApplicationProfile(
                app_identifier=app_id,
                display_name=str(params.get("display_name") or app_id).strip(),
                enabled=bool(params.get("enabled", True)),
                enable_punctuation_assist=bool(params.get("enable_punctuation_assist", True)),
                enable_double_space_period=bool(params.get("enable_double_space_period", True)),
                enable_auto_capitalise=bool(params.get("enable_auto_capitalise", True)),
                aggressiveness=float(params.get("aggressiveness", 1.0)),
                active_domain_packs=frozenset(str(x) for x in params.get("active_domain_packs", [])),
            )
            d.app_profiles.set_profile(prof)
            return self._dispatch("profiles.list", {})

        if method == "profiles.delete":
            app_id = str(params.get("app_identifier", "")).strip().lower()
            if app_id:
                d.app_profiles.remove_profile(app_id)
            return self._dispatch("profiles.list", {})

        # --- 8. Text Expansion Snippets --------------------------------------
        if method == "snippets.list":
            return {
                "snippets": [
                    {
                        "trigger": s.trigger,
                        "expansion": s.expansion,
                        "description": s.description,
                    }
                    for s in d.snippet_engine.list_snippets()
                ]
            }

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
            return {
                "app": {
                    "current_version": APP_VERSION,
                    "released_at": APP_RELEASE_TIMESTAMP,
                    "channel": "stable",
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
                "source_url": "https://github.com/litlEMPEROR/AutoCorrect",
                "donate_url": DONATE_URL,
            }

        raise ValueError(f"Unknown IPC method: '{method}'")
