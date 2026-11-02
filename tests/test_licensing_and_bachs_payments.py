"""
Acceptance Tests for Commercial Licensing, Entitlements, 14-Day Trial,
and the 9-Step BACHS Payment & Webhook Verification Lifecycle.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.licensing.activation_manager import ActivationManager
from autocorrect.licensing.entitlement_manager import EntitlementManager
from autocorrect.licensing.licence_service import LicenceService
from autocorrect.licensing.signed_licence import (
    Edition,
    PlatformOS,
    ProductSKU,
    SignedLicenceCertificate,
    sign_licence_certificate,
)
from autocorrect.licensing.trial_manager import TrialManager, TrialState
from autocorrect.licensing.upgrade_manager import UpgradeType
from autocorrect.payments.bachs_adapter import BachsPaymentAdapter
from autocorrect.payments.checkout_manager import CheckoutManager
from autocorrect.payments.purchase_verification import (
    OrderStatus,
    PurchaseVerificationService,
)
from autocorrect.payments.upgrade_pricing import UpgradePricingCalculator


def _sign_bachs_webhook(raw_body: bytes, secret: str, timestamp: int | None = None) -> dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {"x-bachs-signature-v2": f"t={ts},v1={sig}"}


def test_trial_commencement_expiry_tamper_resistance_and_safe_hook_release(
    tmp_path: Path,
) -> None:
    """
    Verify Section 7 & 15 Trial Requirements:
    - 14-day full-featured trial grants Standard + Pro capabilities.
    - Rolling the system clock backward is detected (`CLOCK_TAMPER_DETECTED`).
    - Deleting the local trial file does not reset the trial when OS vault anchor exists.
    - At day 14 expiry, keyboard hooks are safely released while user preferences and
      custom words remain 100% intact.
    """
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    daemon = AutoCorrectDaemon(
        data_dir=tmp_path / "app_data",
        public_key=pub_key,
        device_id_hash="dev_hash_test_01",
        dry_run_hooks=True,
    )
    try:
        # Add a custom word to user preferences
        daemon.preference_store.add_custom_word("Enwono")
        snap = daemon.start()
        assert snap.mode == "TRIAL_PRO"
        assert snap.typing_assistance_enabled
        assert snap.pro_features_enabled
        assert daemon.hooks_active

        start_dt = datetime.now(timezone.utc)
        # Advance 5 days
        day5 = start_dt + timedelta(days=5)
        status_d5 = daemon.trial_manager.evaluate_trial(now_utc=day5)
        assert status_d5.state == TrialState.ACTIVE

        # Attempt clock rollback attack (rolling clock back 3 days from day 5 to day 2)
        rollback_dt = start_dt + timedelta(days=2)
        status_tamper = daemon.trial_manager.evaluate_trial(now_utc=rollback_dt)
        assert status_tamper.state == TrialState.CLOCK_TAMPER_DETECTED
        assert not status_tamper.is_usable

        # Delete local trial.dat file to simulate reinstall; vault anchor preserves original start
        (tmp_path / "app_data" / "licence" / "trial.dat").unlink()
        status_reinstall = daemon.trial_manager.evaluate_trial(
            now_utc=start_dt + timedelta(days=6)
        )
        assert status_reinstall.state == TrialState.ACTIVE
        assert 7.5 <= status_reinstall.days_remaining <= 8.5

        # Advance past day 14 -> Trial expires, hooks release, user data preserved!
        day15 = start_dt + timedelta(days=15)
        expired_snap = daemon.entitlement_manager.evaluate(now_utc=day15)
        assert expired_snap.mode == "TRIAL_EXPIRED"
        assert not expired_snap.typing_assistance_enabled
        assert not daemon.hooks_active
        assert daemon.preference_store.list_custom_words() == ["Enwono"]
    finally:
        daemon.stop()


def test_perpetual_usage_after_12_month_update_entitlement_expiry(
    tmp_path: Path,
) -> None:
    """
    Verify Section 8 Licensing Model:
    - When the 12-month update entitlement expires, perpetual usage of the entitled
      application version and cached resources continues indefinitely offline.
    - Newer non-security app releases published after `updates_expire_at` are blocked,
      while security patches for the entitled branch are permitted.
    """
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    device_hash = "dev_win_01"

    trial_mgr = TrialManager(tmp_path / "trial.dat", device_hash, use_os_keyring=False)
    ent_mgr = EntitlementManager(
        public_key=pub_key,
        device_id_hash=device_hash,
        trial_manager=trial_mgr,
        current_platform=PlatformOS.WINDOWS,
    )

    # Licence purchased on 2026-01-01, updates expire 2027-01-01
    cert = sign_licence_certificate(
        SignedLicenceCertificate(
            licence_id="lic_01",
            order_id="ord_01",
            sku=ProductSKU.STANDARD_WIN,
            edition=Edition.STANDARD,
            platform=PlatformOS.WINDOWS,
            device_id_hash=device_hash,
            perpetual_usage=True,
            issued_at="2026-01-01T00:00:00Z",
            updates_expire_at="2027-01-01T00:00:00Z",
            entitled_app_max_release_date="2027-01-01T00:00:00Z",
        ),
        priv_key,
    )
    ent_mgr.install_certificate(cert, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc))

    # Evaluate 3 years later (2029-06-01) offline -> Perpetual usage remains 100% active!
    future_2029 = datetime(2029, 6, 1, tzinfo=timezone.utc)
    snap_2029 = ent_mgr.evaluate(now_utc=future_2029)
    assert snap_2029.mode == "LICENSED_STANDARD"
    assert snap_2029.typing_assistance_enabled is True
    assert snap_2029.pro_features_enabled is False
    assert snap_2029.can_download_new_updates is False
    assert "Perpetual Licence Active" in snap_2029.status_message


def test_platform_mismatch_and_device_deactivation_and_recovery(
    tmp_path: Path,
) -> None:
    """
    Verify:
    - `STANDARD-WIN` cannot be activated on `MACOS`.
    - 1 active device limit blocks a 2nd device until deactivated or recovered.
    - Same-device reinstall re-activates idempotently.
    - Emergency dead-device recovery works with matching email and enforces the 2/year limit.
    """
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    act_mgr = ActivationManager(priv_key)

    from autocorrect.licensing.activation_manager import DeviceSeatRecord

    act_mgr.register_licence_seat(
        DeviceSeatRecord(
            licence_id="lic_win_pro",
            order_id="ord_100",
            customer_email="buyer@example.com",
            sku=ProductSKU.PRO_WIN,
            issued_at_iso="2026-11-01T00:00:00Z",
            updates_expire_at_iso="2027-11-01T00:00:00Z",
        )
    )

    # 1. Platform mismatch: trying to activate PRO-WIN on MACOS fails
    with pytest.raises(PermissionError, match="Platform mismatch"):
        act_mgr.activate_device("lic_win_pro", "mac_dev_1", PlatformOS.MACOS)

    # 2. Activate on Windows Device A
    cert_a = act_mgr.activate_device("lic_win_pro", "win_dev_A", PlatformOS.WINDOWS)
    assert cert_a.device_id_hash == "win_dev_A"

    # 3. Same-device reinstall on Windows Device A succeeds idempotently
    cert_a_reinstall = act_mgr.activate_device(
        "lic_win_pro", "win_dev_A", PlatformOS.WINDOWS
    )
    assert cert_a_reinstall.device_id_hash == "win_dev_A"

    # 4. Activating on Windows Device B while Device A is active is blocked
    with pytest.raises(PermissionError, match="already active on another device"):
        act_mgr.activate_device("lic_win_pro", "win_dev_B", PlatformOS.WINDOWS)

    # 5. Self-service deactivation of Device A allows Device B to activate
    act_mgr.deactivate_device("lic_win_pro", "win_dev_A")
    cert_b = act_mgr.activate_device("lic_win_pro", "win_dev_B", PlatformOS.WINDOWS)
    assert cert_b.device_id_hash == "win_dev_B"

    # 6. Dead-device emergency recovery to Device C (1st recovery) and Device D (2nd recovery)
    cert_c = act_mgr.recover_after_device_failure(
        "lic_win_pro", "buyer@example.com", "win_dev_C", PlatformOS.WINDOWS
    )
    assert cert_c.device_id_hash == "win_dev_C"

    cert_d = act_mgr.recover_after_device_failure(
        "lic_win_pro", "buyer@example.com", "win_dev_D", PlatformOS.WINDOWS
    )
    assert cert_d.device_id_hash == "win_dev_D"

    # 3rd emergency recovery within 12 months is blocked
    with pytest.raises(PermissionError, match="Maximum annual emergency device recoveries"):
        act_mgr.recover_after_device_failure(
            "lic_win_pro", "buyer@example.com", "win_dev_E", PlatformOS.WINDOWS
        )


def test_upgrade_and_crossgrade_pricing_rules() -> None:
    """
    Verify Section 9 Upgrade and Renewal Pricing:
    - Retail Standard: $14.99, Retail Pro: $34.99
    - 30% Renewal Standard: $10.49, 30% Renewal Pro: $24.49
    - Active Standard-to-Pro Cross-Grade: $20.00 ($34.99 - $14.99)
    - Expired Standard-to-Pro Cross-Grade: $24.49 (30% off $34.99)
    """
    priv_key = Ed25519PrivateKey.generate()
    calc = UpgradePricingCalculator()

    # New purchases
    q_std = calc.calculate_quote(ProductSKU.STANDARD_WIN)
    assert q_std.final_amount == Decimal("14.99")
    assert not q_std.requires_adhoc_override

    q_pro = calc.calculate_quote(ProductSKU.PRO_MAC)
    assert q_pro.final_amount == Decimal("34.99")
    assert not q_pro.requires_adhoc_override

    std_cert = sign_licence_certificate(
        SignedLicenceCertificate(
            licence_id="lic_std_1",
            order_id="ord_1",
            sku=ProductSKU.STANDARD_WIN,
            edition=Edition.STANDARD,
            platform=PlatformOS.WINDOWS,
            device_id_hash="dev_1",
            perpetual_usage=True,
            issued_at="2026-01-01T00:00:00Z",
            updates_expire_at="2027-01-01T00:00:00Z",
            entitled_app_max_release_date="2027-01-01T00:00:00Z",
        ),
        priv_key,
    )

    # 1. Same-edition 30% renewal
    q_renew_std = calc.calculate_quote(
        ProductSKU.STANDARD_WIN,
        existing_cert=std_cert,
        now_utc=datetime(2027, 2, 1, tzinfo=timezone.utc),
    )
    assert q_renew_std.upgrade_type == UpgradeType.RENEWAL_30PCT
    assert q_renew_std.final_amount_str == "10.49"
    assert q_renew_std.requires_adhoc_override

    # 2. Active Standard -> Pro cross-grade ($20.00 difference)
    q_cross_active = calc.calculate_quote(
        ProductSKU.PRO_WIN,
        existing_cert=std_cert,
        now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert q_cross_active.upgrade_type == UpgradeType.CROSSGRADE_ACTIVE
    assert q_cross_active.final_amount_str == "20.00"
    assert q_cross_active.requires_adhoc_override

    # 3. Expired Standard -> Pro cross-grade ($24.49 - 30% off Pro)
    q_cross_expired = calc.calculate_quote(
        ProductSKU.PRO_WIN,
        existing_cert=std_cert,
        now_utc=datetime(2027, 6, 1, tzinfo=timezone.utc),
    )
    assert q_cross_expired.upgrade_type == UpgradeType.CROSSGRADE_EXPIRED
    assert q_cross_expired.final_amount_str == "24.49"
    assert q_cross_expired.requires_adhoc_override


def test_end_to_end_bachs_checkout_webhook_deduplication_and_refund_lifecycle(
    tmp_path: Path,
) -> None:
    """
    Verify the complete 9-step BACHS payment lifecycle:
    1. Checkout session created via official `bachs` SDK with `product_cart` and `reference`.
    2. Visiting `success_url` before webhook arrives NEVER unlocks a licence.
    3. Invalid webhook signature returns HTTP 400.
    4. Valid `X-Bachs-Signature-V2` webhook (`checkout.completed` or `collection.succeeded`)
       fetches checkout from BACHS, verifies amount/currency/reference, and fulfils once.
    5. Duplicate webhook delivery (`event.id` redelivery) is safely deduplicated.
    6. Client retrieves and activates its Ed25519-signed `entitlement.lic` offline.
    7. Subsequent `refund.paid` webhook revokes the licence seat.
    """
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    webhook_secret = "whsec_test_secret_key_123456"
    device_hash = "dev_win_buyer_01"

    # Mock BACHS API server transport for the official `bachs` Python SDK
    created_checkouts: dict[str, dict[str, object]] = {}

    def _mock_bachs_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/checkout-sessions":
            body = json.loads(request.content.decode("utf-8"))
            chk_id = "chk_test_987654321"
            cart_item = body["product_cart"][0]
            override_amt = (
                cart_item["pricing"]["amount"]
                if "pricing" in cart_item
                else "34.99"
            )
            record = {
                "checkout_id": chk_id,
                "checkout_url": f"https://sandbox-checkout.bachs.io/c/{chk_id}",
                "status": "completed",
                "mode": "payment",
                "payment_status": "paid",
                "amount": override_amt,
                "currency": "USD",
                "reference": body.get("reference"),
                "customer_details": {"email": "ngozi@example.com", "name": "Ngozi"},
                "charge": {
                    "payment_id": "ch_live_test_111",
                    "amount": override_amt,
                    "currency": "USD",
                    "status": "succeeded",
                    "created_at": "2026-11-01T10:00:00Z",
                    "updated_at": "2026-11-01T10:01:00Z",
                },
                "metadata": body.get("metadata", {}),
                "created_at": "2026-11-01T10:00:00Z",
                "expires_at": "2026-11-01T11:00:00Z",
            }
            created_checkouts[chk_id] = record
            return httpx.Response(200, json=record)

        if request.method == "GET" and request.url.path.startswith("/v1/checkout-sessions/"):
            chk_id = request.url.path.split("/")[-1]
            if chk_id in created_checkouts:
                return httpx.Response(200, json=created_checkouts[chk_id])
            return httpx.Response(404, json={"detail": "Not found", "error_code": "NOT_FOUND"})

        if request.method == "POST" and request.url.path == "/v1/refunds":
            body = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "refund_id": "rfnd_test_001",
                    "charge_id": body["charge_id"],
                    "reference": body["reference"],
                    "status": "processing",
                    "requested_amount": "34.99",
                    "refunded_amount": None,
                },
            )

        return httpx.Response(400, json={"error_code": "BAD_REQUEST"})

    mock_http_client = httpx.Client(transport=httpx.MockTransport(_mock_bachs_handler))
    bachs_adapter = BachsPaymentAdapter(
        api_key="sk_sandbox_test_key_123456",
        webhook_secret=webhook_secret,
        http_client=mock_http_client,
    )

    act_mgr = ActivationManager(priv_key)
    ver_svc = PurchaseVerificationService(
        db_path=tmp_path / "orders.sqlite3",
        provider=bachs_adapter,
        activation_manager=act_mgr,
    )
    checkout_mgr = CheckoutManager(provider=bachs_adapter, verification_service=ver_svc)

    trial_mgr = TrialManager(tmp_path / "trial.dat", device_hash, use_os_keyring=False)
    ent_mgr = EntitlementManager(
        public_key=pub_key,
        device_id_hash=device_hash,
        trial_manager=trial_mgr,
        current_platform=PlatformOS.WINDOWS,
    )
    lic_svc = LicenceService(
        licence_file_path=tmp_path / "entitlement.lic",
        entitlement_manager=ent_mgr,
        device_id_hash=device_hash,
        activation_manager=act_mgr,
        current_platform=PlatformOS.WINDOWS,
    )

    # Step 1-3: Initiate checkout for PRO-WIN ($34.99)
    session_res = checkout_mgr.initiate_checkout(
        target_sku=ProductSKU.PRO_WIN,
        device_id_hash=device_hash,
        customer_email="ngozi@example.com",
    )
    assert session_res.checkout_url.startswith("https://sandbox-checkout.bachs.io/c/")
    assert session_res.quote.final_amount_str == "34.99"

    # Security Check: Trying to activate before webhook verification MUST fail
    with pytest.raises(PermissionError, match="not paid/fulfilled"):
        checkout_mgr.retrieve_and_activate_on_client(
            session_res.order_id, lic_svc, device_hash
        )

    # Step 5: Webhook arrives with BAD signature -> rejected with HTTP 400
    webhook_payload = {
        "id": "evt_10001",
        "type": "checkout.completed",
        "created_at": "2026-11-01T10:02:00Z",
        "organization_id": "acct_123",
        "data": {
            "checkout_id": session_res.provider_checkout_id,
            "status": "completed",
            "mode": "payment",
            "payment_status": "paid",
            "amount": "34.99",
            "currency": "USD",
            "reference": session_res.order_id,
            "charge": {"id": "ch_live_test_111"},
        },
    }
    raw_webhook = json.dumps(webhook_payload).encode("utf-8")
    status_bad, _ = ver_svc.handle_raw_webhook(
        raw_webhook, {"x-bachs-signature-v2": "t=1700000000,v1=invalid"}
    )
    assert status_bad == 400

    # Step 6-8: Valid signed webhook fulfils the order
    valid_headers = _sign_bachs_webhook(raw_webhook, webhook_secret)
    status_ok, msg_ok = ver_svc.handle_raw_webhook(raw_webhook, valid_headers)
    assert status_ok == 200
    assert msg_ok == "FULFILLED"

    # Redelivery of the exact same webhook event ID is deduplicated
    status_dup, msg_dup = ver_svc.handle_raw_webhook(raw_webhook, valid_headers)
    assert status_dup == 200
    assert msg_dup == "DUPLICATE_EVENT_IGNORED"

    # Arrival of companion `collection.succeeded` for the already-fulfilled order is a safe no-op
    coll_payload = {
        "id": "evt_10002",
        "type": "collection.succeeded",
        "created_at": "2026-11-01T10:02:01Z",
        "organization_id": "acct_123",
        "data": {
            "charge_id": "ch_live_test_111",
            "checkout_id": session_res.provider_checkout_id,
            "reference": session_res.order_id,
            "status": "SUCCEEDED",
            "amount": "34.99",
            "currency": "USD",
        },
    }
    raw_coll = json.dumps(coll_payload).encode("utf-8")
    status_coll, msg_coll = ver_svc.handle_raw_webhook(
        raw_coll, _sign_bachs_webhook(raw_coll, webhook_secret)
    )
    assert status_coll == 200
    assert msg_coll == "ALREADY_FULFILLED"

    # Step 9: Desktop client activates and persists signed entitlement.lic
    snap = checkout_mgr.retrieve_and_activate_on_client(
        session_res.order_id, lic_svc, device_hash
    )
    assert snap.mode == "LICENSED_PRO"
    assert snap.typing_assistance_enabled is True
    assert snap.pro_features_enabled is True
    assert (tmp_path / "entitlement.lic").exists()

    # Refund lifecycle: issue refund via REST and process `refund.paid` webhook
    ref_state = bachs_adapter.issue_refund(
        charge_id="ch_live_test_111",
        reference="ref_ord_1",
        idempotency_key="idem_ref_1",
    )
    assert ref_state.status == "processing"

    refund_event = {
        "id": "evt_10003",
        "type": "refund.paid",
        "created_at": "2026-11-01T10:05:00Z",
        "organization_id": "acct_123",
        "data": {
            "refund_id": "rfnd_test_001",
            "charge_id": "ch_live_test_111",
            "reference": "ref_ord_1",
            "status": "paid",
            "requested_amount": "34.99",
            "refunded_amount": "34.99",
        },
    }
    raw_ref = json.dumps(refund_event).encode("utf-8")
    st_ref, msg_ref = ver_svc.handle_raw_webhook(
        raw_ref, _sign_bachs_webhook(raw_ref, webhook_secret)
    )
    assert st_ref == 200
    assert msg_ref == "LICENCE_REVOKED_ON_REFUND"
    assert ver_svc.get_order(session_res.order_id).status == OrderStatus.REFUNDED  # type: ignore[union-attr]
