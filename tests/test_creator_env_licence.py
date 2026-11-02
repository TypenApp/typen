"""
Creator lifetime entitlement via `.env`.

`AUTOCORRECT_CREATOR_DEVICE_HASHES` lists SHA-256 device-id hashes that hold a
perpetual Pro entitlement, loaded from `.env` by `autocorrect.env_config`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.env_config import creator_device_hashes, load_env_file, parse_env_text
from autocorrect.licensing.entitlement_manager import EntitlementManager
from autocorrect.licensing.trial_manager import TrialManager

DEVICE = "bd3fb66fb7d7d8dd399e95837194ca78803d806ca358c6dfc4fb55a46dfc15b3"
OTHER = "0" * 64


def test_parse_env_text_handles_comments_quotes_and_export() -> None:
    parsed = parse_env_text(
        "\n".join(
            [
                "# comment",
                "",
                f"AUTOCORRECT_CREATOR_DEVICE_HASHES={DEVICE} # inline",
                'export AUTOCORRECT_CREATOR_NAME="Enwono Ntuk"',
                "BROKEN LINE WITHOUT EQUALS",
                "EMPTY=",
            ]
        )
    )
    assert parsed["AUTOCORRECT_CREATOR_DEVICE_HASHES"] == DEVICE
    assert parsed["AUTOCORRECT_CREATOR_NAME"] == "Enwono Ntuk"
    assert parsed["EMPTY"] == ""
    assert "BROKEN LINE WITHOUT EQUALS" not in parsed


def test_creator_hashes_are_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", f" {DEVICE.upper()}, not-a-hash ;{OTHER}")
    assert creator_device_hashes() == frozenset({DEVICE, OTHER})
    monkeypatch.setenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", "")
    assert creator_device_hashes() == frozenset()


def test_env_file_in_data_dir_is_loaded_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", raising=False)
    monkeypatch.setenv("AUTOCORRECT_CREATOR_NAME", "FromRealEnv")
    (tmp_path / ".env").write_text(
        f"AUTOCORRECT_CREATOR_DEVICE_HASHES={DEVICE}\nAUTOCORRECT_CREATOR_NAME=FromFile\n",
        encoding="utf-8",
    )
    loaded = load_env_file(tmp_path)
    assert loaded == tmp_path / ".env"
    assert creator_device_hashes() == frozenset({DEVICE})
    # a variable already present in the process environment wins
    import os

    assert os.environ["AUTOCORRECT_CREATOR_NAME"] == "FromRealEnv"


def _manager(tmp_path: Path, device_hash: str) -> EntitlementManager:
    key = Ed25519PrivateKey.from_private_bytes(b"AutoCorrect-Embedded-Root-Key-v1").public_key()
    trial = TrialManager(
        trial_file_path=tmp_path / "trial.dat", device_id_hash=device_hash, use_os_keyring=False
    )
    return EntitlementManager(public_key=key, device_id_hash=device_hash, trial_manager=trial)


def test_creator_device_gets_lifetime_pro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", DEVICE)
    monkeypatch.setenv("AUTOCORRECT_CREATOR_NAME", "Enwono")
    snap = _manager(tmp_path, DEVICE).evaluate()
    assert snap.mode == "CREATOR_LIFETIME"
    assert snap.typing_assistance_enabled and snap.pro_features_enabled
    assert snap.can_download_new_updates and snap.updates_expire_at is None
    assert snap.status_message == "Enwono Lifetime Pro Licence (this device)"


def test_other_devices_still_fall_back_to_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", DEVICE)
    snap = _manager(tmp_path, OTHER).evaluate()
    assert snap.mode == "TRIAL_PRO"


def test_daemon_loads_env_from_its_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", raising=False)
    monkeypatch.delenv("AUTOCORRECT_CREATOR_NAME", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text(f"AUTOCORRECT_CREATOR_DEVICE_HASHES={DEVICE}\n", encoding="utf-8")
    daemon = AutoCorrectDaemon(data_dir=data_dir, dry_run_hooks=True, device_id_hash=DEVICE)
    try:
        snap = daemon.start(start_ipc=False)
        assert snap.mode == "CREATOR_LIFETIME"
        assert daemon.entitlement_manager.is_creator_device()
    finally:
        daemon.stop()
