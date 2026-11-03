"""Trial anchor integrity: per-device v2 HMAC, legacy v1 records still accepted, cross-device replay rejected."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from autocorrect.licensing.trial_manager import TrialManager, TrialState

DEVICE_A = "aa" * 32
DEVICE_B = "bb" * 32
_V1_KEY = b"AutoCorrect-Offline-Trial-Integrity-v1-Key"


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_legacy_v1_record_is_honoured_and_rewritten_with_v2_mac(tmp_path: Path) -> None:
    started = datetime.now(UTC) - timedelta(days=10)
    s_iso = m_iso = _iso(started)
    legacy_mac = hmac.new(_V1_KEY, f"{DEVICE_A}|{s_iso}|{m_iso}".encode(), hashlib.sha256).hexdigest()
    path = tmp_path / "trial.dat"
    path.write_text(json.dumps({"started_at": s_iso, "max_observed_utc": m_iso, "mac": legacy_mac}))

    mgr = TrialManager(path, DEVICE_A, use_os_keyring=False)
    status = mgr.evaluate_trial()
    assert status.state == TrialState.ACTIVE
    assert 3.5 < status.days_remaining < 4.5  # the old 10-day-old trial was kept, not restarted

    rewritten = json.loads(path.read_text())
    assert rewritten["mac"] != legacy_mac  # upgraded to the per-device key on save


def test_v2_record_is_bound_to_device(tmp_path: Path) -> None:
    path_a = tmp_path / "a" / "trial.dat"
    TrialManager(path_a, DEVICE_A, use_os_keyring=False).evaluate_trial(
        datetime.now(UTC) - timedelta(days=13)
    )
    # Copy device A's nearly-expired anchor onto device B and try to use it as-is.
    path_b = tmp_path / "b" / "trial.dat"
    path_b.parent.mkdir()
    path_b.write_text(path_a.read_text())
    status_b = TrialManager(path_b, DEVICE_B, use_os_keyring=False).evaluate_trial()
    # Foreign record fails the MAC: treated as tampering, so no free fresh trial.
    assert status_b.state == TrialState.CLOCK_TAMPER_DETECTED


def test_edited_record_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "trial.dat"
    mgr = TrialManager(path, DEVICE_A, use_os_keyring=False)
    mgr.evaluate_trial()
    rec = json.loads(path.read_text())
    rec["started_at"] = _iso(datetime.now(UTC) + timedelta(days=300))
    path.write_text(json.dumps(rec))
    assert (
        TrialManager(path, DEVICE_A, use_os_keyring=False).evaluate_trial().state
        == TrialState.CLOCK_TAMPER_DETECTED
    )
