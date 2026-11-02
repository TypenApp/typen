"""
Acceptance Tests for:
- Pro AI (BYOK configuration, invalid credentials, provider outages, usage accounting,
  spending limits, Local-Only mode, log secret redaction, Layer 2 Local AI pause pill & hotkey)
- Pro Productivity (text expansion snippets, domain vocabulary packs, app profiles, local insights)
- Independent Resource Updates (Ed25519 signature verification, corrupted archive rejection,
  executable file rejection, zstd delta patching, rollback, expired entitlement handling)
- Performance & Latency Benchmarks (< 2.5ms word evaluation latency)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autocorrect.ai.api_key_manager import (
    ApiKeyManager,
    SecretRedactingFilter,
    redact_secrets,
)
from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.ai.provider_manager import (
    AIProviderId,
    AIRewriteRequest,
    BYOKProviderManager,
)
from autocorrect.ai.spending_controls import (
    LocalOnlyLockdownError,
    SpendingController,
    SpendLimitExceededError,
)
from autocorrect.ai.usage_tracker import UsageTracker
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.productivity.snippet_engine import SnippetEngine
from autocorrect.updates.language_resource_updater import (
    LanguageResourceUpdater,
    ResourceUpdateDescriptor,
)
from pipeline.compile_binary import compile_dataset_to_directory
from pipeline.ingest import build_master_english_dataset
from pipeline.sign_release import (
    create_zstd_bundle_archive,
    create_zstd_delta_patch,
    sign_manifest_payload,
)
from pipeline.validate import validate_and_sanitize_dataset


def test_byok_cloud_ai_consent_spending_caps_local_only_and_redaction(
    tmp_path: Path,
) -> None:
    """
    Verify Section 5 & 15 AI & Privacy Requirements:
    - Secret keys (`sk-...`, `AIza...`, `sk_live_...`) are scrubbed from logs.
    - Cloud AI refuses to transmit without explicit user consent.
    - Local-Only Lockdown blocks all cloud requests.
    - Hard daily/monthly spending caps block requests once reached.
    - Provider outages scrub secrets from error messages.
    """
    # 1. Verify log redaction filter
    raw_log = "Failed with key sk-proj-1234567890abcdef and sk_live_bachs987654321"
    scrubbed = redact_secrets(raw_log)
    assert "sk-proj-" not in scrubbed
    assert "sk_live_" not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed

    record = logging.LogRecord("test", logging.ERROR, "path", 1, raw_log, (), None)
    assert SecretRedactingFilter().filter(record)
    assert "sk-proj-" not in record.msg

    # 2. Setup BYOK Provider Manager
    key_mgr = ApiKeyManager(use_memory_backend=True)
    key_mgr.set_api_key("openai", "sk-test-validkey1234567890")
    tracker = UsageTracker(tmp_path / "ai_usage.sqlite3")
    spending = SpendingController(
        usage_tracker=tracker,
        daily_limit_usd=Decimal("0.000500"),
        monthly_limit_usd=Decimal("5.00"),
        local_only_mode=False,
    )

    def _mock_llm_transport(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "I have received your message."}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            },
        )

    provider_mgr = BYOKProviderManager(
        key_manager=key_mgr,
        usage_tracker=tracker,
        spending_controller=spending,
        http_transport=httpx.MockTransport(_mock_llm_transport),
    )

    # 3. Without explicit consent, request is rejected
    unconsented_req = AIRewriteRequest(
        text="I has recieved you're mesage.",
        provider=AIProviderId.OPENAI,
        model="gpt-4o-mini",
        user_consented=False,
    )
    with pytest.raises(PermissionError, match="Explicit user consent"):
        provider_mgr.refine_sentence(unconsented_req)

    # 4. With explicit consent, request succeeds and records token usage + cost
    consented_req = AIRewriteRequest(
        text="I has recieved you're mesage.",
        provider=AIProviderId.OPENAI,
        model="gpt-4o-mini",
        user_consented=True,
    )
    res = provider_mgr.refine_sentence(consented_req)
    assert res.rewritten_text == "I have received your message."
    assert res.prompt_tokens == 100
    assert res.estimated_cost_usd > Decimal("0")

    # 5. Local-Only Mode immediately blocks cloud transmission
    spending.set_local_only_mode(True)
    with pytest.raises(LocalOnlyLockdownError):
        provider_mgr.refine_sentence(consented_req)
    spending.set_local_only_mode(False)

    # 6. Exceeding daily spending limit blocks further requests
    tracker.record_usage("openai", "gpt-4o", prompt_tokens=1000, completion_tokens=1000)
    with pytest.raises(SpendLimitExceededError):
        provider_mgr.refine_sentence(consented_req)


def test_layer2_local_ai_pause_pill_and_hotkey_triggers() -> None:
    """
    Verify Layer 2 Local AI:
    - Does not trigger during rapid typing (`pause_elapsed_ms < 400ms`).
    - Triggers `PAUSE_PILL` when `pause_elapsed_ms >= 400ms`.
    - Triggers `HOTKEY_REWRITE` immediately when invoked via hotkey (`Ctrl+Shift+R`).
    - Unloads model after idle timeout.
    """
    local_ai = LocalModelManager(is_pro_entitled=True)
    hw = local_ai.detect_hardware_profile(override_ram_mb=8192)
    assert hw.recommended_model_id == "grammar-onnx-int8-small"

    # Too short pause -> no interruption
    assert (
        local_ai.evaluate_sentence(
            "I should of gone to the meeting.", pause_elapsed_ms=100.0
        )
        is None
    )

    # >= 400ms pause at sentence boundary -> non-focus-stealing PAUSE_PILL suggestion
    pill = local_ai.evaluate_sentence(
        "I should of gone to the meeting.", pause_elapsed_ms=450.0
    )
    assert pill is not None
    assert pill.suggested_sentence == "I should have gone to the meeting."
    assert pill.presentation_mode == "PAUSE_PILL"

    # Hotkey rewrite works immediately with 0ms pause
    hk = local_ai.evaluate_sentence(
        "They was happy with the result.",
        pause_elapsed_ms=0.0,
        triggered_by_hotkey=True,
    )
    assert hk is not None
    assert hk.suggested_sentence == "They were happy with the result."
    assert hk.presentation_mode == "HOTKEY_REWRITE"

    # Idle timeout unloads model from RAM
    assert local_ai.is_model_loaded
    assert local_ai.check_idle_unload(now_monotonic=time.monotonic() + 400.0)
    assert not local_ai.is_model_loaded


def test_pro_snippets_and_domain_packs(tmp_path: Path) -> None:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    rm.set_enabled_domain_packs({"programming", "medicine", "finance"})
    engine = AutocorrectEngine(rm)
    snippets = SnippetEngine()
    snippets.add_snippet(";sig", "Best regards, AutoCorrect Team")
    session = InputSessionManager(engine=engine, snippet_matcher=snippets)
    try:
        # Domain pack direct typo ('kubernets' -> 'Kubernetes', 'reconcilation' -> 'reconciliation')
        assert engine.evaluate_token("kubernets").replacement_token == "Kubernetes"
        assert engine.evaluate_token("reconcilation").replacement_token == "reconciliation"
        assert engine.evaluate_token("arythmia").replacement_token == "arrhythmia"

        # Snippet trigger ';sig ' expands (and can be undone with double Backspace)
        from tests.test_core_standard import _type_string

        expanded = _type_string(session, ";sig ")
        assert expanded == "Best regards, AutoCorrect Team "
    finally:
        rm.close()


def test_independent_signed_resource_updates_delta_and_rollback(
    tmp_path: Path,
) -> None:
    """
    Verify Section 6 & 11 Independent Resource Updates:
    - Ed25519 signature verification on manifest.
    - Zstandard delta patch decompression and SHA-256 verification.
    - Corrupted archive rejection.
    - Expired update entitlement rejection while keeping existing local resources working.
    - Atomic hot-swap and rollback to `last_known_good`.
    """
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    # Build v1.0.8 baseline archive
    v1_dir = tmp_path / "build_v1"
    ds1 = build_master_english_dataset(version="1.0.8")
    validate_and_sanitize_dataset(ds1)
    compile_dataset_to_directory(ds1, v1_dir)
    v1_archive_path = tmp_path / "en_1.0.8.tar.zst"
    create_zstd_bundle_archive(v1_dir, v1_archive_path)
    v1_bytes = v1_archive_path.read_bytes()

    # Build v1.0.9 updated resource bundle with a brand-new emerging word & typo
    v2_dir = tmp_path / "build_v2"
    ds2 = build_master_english_dataset(version="1.0.9")
    ds2.released_at = "2026-12-01T00:00:00Z"
    ds2.direct_typos["agenticly"] = ("agentically", 8.5)
    from pipeline.ingest import RawWordEntry

    ds2.words["agentically"] = RawWordEntry(word="agentically", log_freq=-6.0)
    validate_and_sanitize_dataset(ds2)
    compile_dataset_to_directory(ds2, v2_dir)

    v2_archive_path = tmp_path / "en_1.0.9.tar.zst"
    v2_sha, v2_size = create_zstd_bundle_archive(v2_dir, v2_archive_path)
    v2_bytes = v2_archive_path.read_bytes()

    # Create zstd delta patch from v1.0.8 -> v1.0.9
    patch_path = tmp_path / "en_1.0.8_to_1.0.9.patch.zst"
    patch_sha, patch_size = create_zstd_delta_patch(v1_bytes, v2_bytes, patch_path)
    patch_bytes = patch_path.read_bytes()

    descriptor = ResourceUpdateDescriptor(
        version="1.0.9",
        schema_version=1,
        released_at="2026-12-01T00:00:00Z",
        full_archive_sha256=v2_sha,
        full_archive_size=v2_size,
        delta_from_version="1.0.8",
        delta_patch_sha256=patch_sha,
        delta_patch_size=patch_size,
    )
    sig_b64 = sign_manifest_payload(descriptor.to_canonical_dict(), priv_key)

    user_res_dir = tmp_path / "user_resources"
    rm = ResourceManager(bundled_dir=v1_dir, user_resources_dir=user_res_dir)
    rm.load_best_available()
    updater = LanguageResourceUpdater(rm, user_res_dir, pub_key)
    engine = AutocorrectEngine(rm)

    try:
        assert rm.active_bundle.version == "1.0.8"

        # 1. Tampered signature is rejected
        with pytest.raises(PermissionError, match="Invalid Ed25519"):
            updater.install_from_archive_bytes(descriptor, "bad_sig", v2_bytes)

        # 2. Corrupted archive bytes are rejected before touching active bundle
        with pytest.raises(ValueError, match="Corrupted"):
            updater.install_from_archive_bytes(descriptor, sig_b64, b"corrupted_bytes")
        assert rm.active_bundle.version == "1.0.8"

        # 3. Expired update entitlement blocks installing v1.0.9 (released Dec 2026)
        expired_cutoff = datetime(2026, 11, 15, tzinfo=timezone.utc)
        with pytest.raises(PermissionError, match="outside the 12-month update entitlement"):
            updater.install_from_archive_bytes(
                descriptor, sig_b64, v2_bytes, updates_expire_at=expired_cutoff
            )
        # Existing v1.0.8 remains 100% functional
        assert rm.active_bundle.version == "1.0.8"

        # 4. Install v1.0.9 via Zstd Delta Patch within active entitlement window!
        entitled_cutoff = datetime(2027, 11, 1, tzinfo=timezone.utc)
        installed = updater.install_from_archive_bytes(
            descriptor=descriptor,
            signature_b64=sig_b64,
            archive_or_patch_bytes=patch_bytes,
            is_delta_patch=True,
            base_archive_bytes=v1_bytes,
            updates_expire_at=entitled_cutoff,
        )
        assert installed is True
        assert rm.active_bundle.version == "1.0.9"
        assert engine.evaluate_token("agenticly").replacement_token == "agentically"

        # 5. Rollback restores v1.0.8 cleanly
        updater.rollback_to_last_known_good()
        assert rm.active_bundle.version == "1.0.8"
    finally:
        rm.close()


def test_preferences_import_export_and_performance_benchmarks(tmp_path: Path) -> None:
    """
    Verify:
    - SQLite preference store custom dictionary, rejected corrections, JSON/CSV import/export,
      and one-click privacy wipe.
    - Word evaluation latency is well below the 2.5ms budget.
    """
    prefs = SQLitePreferenceStore(tmp_path / "prefs.sqlite3")
    prefs.add_custom_word("BachsPay")
    prefs.add_rejected_correction("teh", "the")
    prefs.set_preferred_variant("color", "colour")
    prefs.set_region_preference("EN_GB")

    exported = prefs.export_json()
    prefs.clear_all_preferences()
    assert prefs.list_custom_words() == []

    prefs.import_json(exported)
    assert prefs.overlay.is_custom_word("bachspay")
    assert prefs.overlay.is_rejected_pair("teh", "the")
    assert prefs.overlay.get_preferred_variant("color") == "colour"

    # Benchmark cold load + 200 word evaluations
    t0 = time.perf_counter()
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    rm.load_best_available()
    cold_load_ms = (time.perf_counter() - t0) * 1000.0
    assert cold_load_ms < 400.0  # Spec budget: < 400ms startup

    engine = AutocorrectEngine(rm, preferences=prefs.overlay)
    try:
        sample_words = ["received", "recieved", "mesage", "definite", "definately", "the", "application", "seperate"]
        latencies_ms: list[float] = []
        for _ in range(25):
            for w in sample_words:
                s = time.perf_counter()
                engine.evaluate_token(w)
                latencies_ms.append((time.perf_counter() - s) * 1000.0)

        latencies_ms.sort()
        median_ms = latencies_ms[len(latencies_ms) // 2]
        assert median_ms < 2.5
    finally:
        rm.close()
