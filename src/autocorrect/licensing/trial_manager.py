"""
14-Day Full-Featured Trial Manager.
Features:
- 14 calendar days of full Standard + Pro access.
- Survives application restarts and reinstalls by anchoring the signed inception
  record in both local disk storage and the OS Credential Vault (`keyring`).
- Resists local system clock rollback tampering via monotonic high-water timestamp tracking
  (`max_observed_utc`).
- Never deletes user preferences, custom dictionary entries, or downloaded resources on expiry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Final

import keyring

TRIAL_DURATION_DAYS: Final[int] = 14
TRIAL_CLOCK_ROLLBACK_TOLERANCE_SECONDS: Final[float] = 3600.0  # 1 hour DST/NTP tolerance
TRIAL_KEYRING_SERVICE: Final[str] = "AutoCorrect.Desktop.TrialAnchor"
TRIAL_HMAC_KEY: Final[bytes] = b"AutoCorrect-Offline-Trial-Integrity-v1-Key"


class TrialState(str, Enum):
    """Current state of the 14-day evaluation trial."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLOCK_TAMPER_DETECTED = "CLOCK_TAMPER_DETECTED"


@dataclass(frozen=True, slots=True)
class TrialStatus:
    """Evaluated trial status returned to `EntitlementManager`."""

    state: TrialState
    started_at: datetime
    expires_at: datetime
    days_remaining: float

    @property
    def is_usable(self) -> bool:
        return self.state == TrialState.ACTIVE


class TrialManager:
    """
    Manages the 14-day full-featured trial with reinstall persistence and clock-tamper detection.
    """

    def __init__(
        self,
        trial_file_path: Path,
        device_id_hash: str,
        use_os_keyring: bool = True,
    ) -> None:
        self._file_path = trial_file_path
        self._device_id_hash = device_id_hash
        self._use_keyring = use_os_keyring
        self._memory_vault_anchor: str | None = None

    def _compute_mac(self, started_iso: str, max_seen_iso: str) -> str:
        msg = f"{self._device_id_hash}|{started_iso}|{max_seen_iso}".encode("utf-8")
        return hmac.new(TRIAL_HMAC_KEY, msg, hashlib.sha256).hexdigest()

    def _load_raw_record(self) -> dict[str, str] | None:
        # Check OS keyring / vault first (survives deleting the app folder / reinstalling)
        vault_raw: str | None = self._memory_vault_anchor
        if self._use_keyring and vault_raw is None:
            try:
                vault_raw = keyring.get_password(TRIAL_KEYRING_SERVICE, self._device_id_hash)
            except Exception:
                vault_raw = None

        file_raw: str | None = None
        if self._file_path.exists():
            try:
                file_raw = self._file_path.read_text(encoding="utf-8")
            except Exception:
                file_raw = None

        candidates: list[dict[str, str]] = []
        for raw_str in (vault_raw, file_raw):
            if not raw_str:
                continue
            try:
                parsed = json.loads(raw_str)
                s_iso = str(parsed["started_at"])
                m_iso = str(parsed["max_observed_utc"])
                mac = str(parsed["mac"])
                if hmac.compare_digest(self._compute_mac(s_iso, m_iso), mac):
                    candidates.append(parsed)
            except Exception:
                continue

        if not candidates:
            # If the trial file existed on disk but failed HMAC verification, the user
            # tampered with the file; return a tamper marker
            if file_raw is not None:
                return {"tampered": "true"}
            return None

        # Choose the earliest started_at and latest max_observed_utc across all anchors
        earliest_start = min(
            candidates,
            key=lambda c: datetime.fromisoformat(c["started_at"].replace("Z", "+00:00")),
        )["started_at"]
        latest_max = max(
            candidates,
            key=lambda c: datetime.fromisoformat(c["max_observed_utc"].replace("Z", "+00:00")),
        )["max_observed_utc"]
        return {
            "started_at": earliest_start,
            "max_observed_utc": latest_max,
            "mac": self._compute_mac(earliest_start, latest_max),
        }

    def _save_raw_record(self, started_iso: str, max_seen_iso: str) -> None:
        record = {
            "started_at": started_iso,
            "max_observed_utc": max_seen_iso,
            "mac": self._compute_mac(started_iso, max_seen_iso),
        }
        serialized = json.dumps(record)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(serialized, encoding="utf-8")
        self._memory_vault_anchor = serialized
        if self._use_keyring:
            try:
                keyring.set_password(TRIAL_KEYRING_SERVICE, self._device_id_hash, serialized)
            except Exception:
                pass

    def evaluate_trial(self, now_utc: datetime | None = None) -> TrialStatus:
        """
        Start or evaluate the 14-day trial.
        Detects system clock rollback and file tampering.
        """
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")

        record = self._load_raw_record()
        if record is None:
            # First launch ever on this machine
            self._save_raw_record(now_iso, now_iso)
            expires = now + timedelta(days=TRIAL_DURATION_DAYS)
            return TrialStatus(
                state=TrialState.ACTIVE,
                started_at=now,
                expires_at=expires,
                days_remaining= float(TRIAL_DURATION_DAYS),
            )

        if record.get("tampered") == "true":
            past = now - timedelta(days=TRIAL_DURATION_DAYS + 1)
            return TrialStatus(
                state=TrialState.CLOCK_TAMPER_DETECTED,
                started_at=past,
                expires_at=now,
                days_remaining=0.0,
            )

        started_dt = datetime.fromisoformat(
            record["started_at"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        max_seen_dt = datetime.fromisoformat(
            record["max_observed_utc"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        expires_dt = started_dt + timedelta(days=TRIAL_DURATION_DAYS)

        # Check if system clock was rolled backward beyond tolerance
        if (max_seen_dt - now).total_seconds() > TRIAL_CLOCK_ROLLBACK_TOLERANCE_SECONDS:
            return TrialStatus(
                state=TrialState.CLOCK_TAMPER_DETECTED,
                started_at=started_dt,
                expires_at=expires_dt,
                days_remaining=0.0,
            )

        # Update high-water timestamp if clock moved forward
        if now > max_seen_dt:
            self._save_raw_record(record["started_at"], now_iso)

        remaining_sec = (expires_dt - now).total_seconds()
        if remaining_sec <= 0:
            return TrialStatus(
                state=TrialState.EXPIRED,
                started_at=started_dt,
                expires_at=expires_dt,
                days_remaining=0.0,
            )

        return TrialStatus(
            state=TrialState.ACTIVE,
            started_at=started_dt,
            expires_at=expires_dt,
            days_remaining=round(remaining_sec / 86400.0, 2),
        )
