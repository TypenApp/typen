"""
Creator lifetime entitlement is a *signed certificate*, not an environment variable.

Only the root private key can mint one; the old `.env` device-hash list is gone
and frozen builds never read a `.env` at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pipeline.issue_licence import issue_certificate

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.env_config import load_env_file, parse_env_text
from autocorrect.licensing.entitlement_manager import EntitlementManager
from autocorrect.licensing.signed_licence import (
    Edition,
    PlatformOS,
    ProductSKU,
    detect_current_platform,
)
from autocorrect.licensing.trial_manager import TrialManager

DEVICE = "bd3fb66fb7d7d8dd399e95837194ca78803d806ca358c6dfc4fb55a46dfc15b3"
OTHER = "0" * 64


def _manager(tmp_path: Path, device_hash: str, pub) -> EntitlementManager:
    trial = TrialManager(
        trial_file_path=tmp_path / "trial.dat", device_id_hash=device_hash, use_os_keyring=False
    )
    return EntitlementManager(public_key=pub, device_id_hash=device_hash, trial_manager=trial)


def test_parse_env_text_handles_comments_quotes_and_export() -> None:
    parsed = parse_env_text('# c\n\nA=1 # inline\nexport B="two words"\nBROKEN\nEMPTY=\n')
    assert parsed == {"A": "1", "B": "two words", "EMPTY": ""}


def test_frozen_builds_never_load_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("AUTOCORRECT_ROOT_PUBLIC_KEY_HEX=" + "a" * 64, encoding="utf-8")
    monkeypatch.setenv("AUTOCORRECT_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.delenv("AUTOCORRECT_ROOT_PUBLIC_KEY_HEX", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert load_env_file() is None
    import os

    assert "AUTOCORRECT_ROOT_PUBLIC_KEY_HEX" not in os.environ


def test_creator_certificate_grants_lifetime_pro(tmp_path: Path) -> None:
    priv = Ed25519PrivateKey.generate()
    sku = ProductSKU.for_platform(Edition.PRO, detect_current_platform())
    cert = issue_certificate(priv, sku, DEVICE, order_id="GIFT", creator=True)
    assert cert.is_creator_certificate and cert.edition == Edition.PRO

    mgr = _manager(tmp_path, DEVICE, priv.public_key())
    snap = mgr.install_certificate(cert)
    assert snap.mode == "CREATOR_LIFETIME"
    assert snap.typing_assistance_enabled and snap.pro_features_enabled
    assert snap.can_download_new_updates and snap.updates_expire_at is None
    assert mgr.is_creator_device()


def test_creator_certificate_is_device_bound(tmp_path: Path) -> None:
    priv = Ed25519PrivateKey.generate()
    sku = ProductSKU.for_platform(Edition.PRO, detect_current_platform())
    cert = issue_certificate(priv, sku, DEVICE, order_id="GIFT", creator=True)
    with pytest.raises(PermissionError):
        _manager(tmp_path, OTHER, priv.public_key()).install_certificate(cert)


def test_creator_prefix_without_root_signature_is_rejected(tmp_path: Path) -> None:
    attacker = Ed25519PrivateKey.generate()
    root = Ed25519PrivateKey.generate()
    sku = ProductSKU.for_platform(Edition.PRO, detect_current_platform())
    forged = issue_certificate(attacker, sku, DEVICE, order_id="X", creator=True)
    with pytest.raises(PermissionError, match="Invalid Ed25519"):
        _manager(tmp_path, DEVICE, root.public_key()).install_certificate(forged)


def test_old_dev_seed_certificates_no_longer_verify(tmp_path: Path) -> None:
    """The beta.2 embedded seed must be useless against the production root key."""
    old_dev = Ed25519PrivateKey.from_private_bytes(b"AutoCorrect-Embedded-Root-Key-v1")
    sku = ProductSKU.for_platform(Edition.PRO, detect_current_platform())
    forged = issue_certificate(old_dev, sku, DEVICE, order_id="X")
    daemon = AutoCorrectDaemon(data_dir=tmp_path / "data", dry_run_hooks=True, device_id_hash=DEVICE)
    try:
        with pytest.raises(PermissionError):
            daemon.entitlement_manager.install_certificate(forged)
        assert daemon.start(start_ipc=False).mode == "TRIAL_PRO"
    finally:
        daemon.stop()


def test_daemon_loads_creator_certificate_from_data_dir(tmp_path: Path) -> None:
    priv = Ed25519PrivateKey.generate()
    sku = ProductSKU.for_platform(Edition.PRO, detect_current_platform())
    cert = issue_certificate(priv, sku, DEVICE, order_id="GIFT", creator=True)
    data_dir = tmp_path / "data"
    (data_dir / "licence").mkdir(parents=True)
    (data_dir / "licence" / "entitlement.lic").write_text(cert.to_json(), encoding="utf-8")
    daemon = AutoCorrectDaemon(
        data_dir=data_dir, dry_run_hooks=True, device_id_hash=DEVICE, public_key=priv.public_key()
    )
    try:
        assert daemon.start(start_ipc=False).mode == "CREATOR_LIFETIME"
    finally:
        daemon.stop()


def test_linux_skus_exist_and_round_trip() -> None:
    assert ProductSKU.PRO_LINUX.platform is PlatformOS.LINUX
    assert ProductSKU.STANDARD_LINUX.edition is Edition.STANDARD
    assert ProductSKU.for_platform(Edition.STANDARD, PlatformOS.LINUX) is ProductSKU.STANDARD_LINUX
    for sku in ProductSKU:
        assert ProductSKU.for_platform(sku.edition, sku.platform) is sku
