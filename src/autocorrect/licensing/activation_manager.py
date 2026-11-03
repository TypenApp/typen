"""
1-Device Activation, Deactivation, Reinstall, and Recovery Manager.
Avoids invasive hardware fingerprinting by deriving a privacy-preserving
salted SHA-256 hash of the operating system's standard machine identifier.
Supports:
- Activating 1 device per licence.
- Idempotent re-activation on the same device after OS/app reinstall.
- Self-service deactivation to move to a replacement computer.
- Rate-limited dead-device recovery (up to 2 emergency resets per 12 months).
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autocorrect.licensing.signed_licence import (
    PlatformOS,
    ProductSKU,
    SignedLicenceCertificate,
    sign_licence_certificate,
)

MAX_EMERGENCY_RECOVERIES_PER_YEAR: Final[int] = 2
DEVICE_HASH_SALT: Final[bytes] = b"AutoCorrect-DeviceSeat-Salt-v1:"


def get_os_native_machine_uuid() -> str:
    """
    Read the operating system's canonical non-volatile machine UUID
    (the desktop equivalent of a device identity):
    - Windows: `HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid`
    - macOS: Hardware `IOPlatformUUID` from `IOPlatformExpertDevice`
    - Linux: `/etc/machine-id` or `/var/lib/dbus/machine-id`
    """
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                if val and str(val).strip():
                    return f"WIN-MACHINEGUID-{str(val).strip()}"
        except Exception:
            pass

    elif sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                text=True,
                timeout=2.0,
            )
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return f"MAC-IOPLATFORMUUID-{parts[-2].strip()}"
        except Exception:
            pass

    elif sys.platform.startswith("linux"):
        for path_str in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            p = Path(path_str)
            if p.exists():
                try:
                    mid = p.read_text(encoding="utf-8").strip()
                    if mid:
                        return f"LINUX-MACHINEID-{mid}"
                except Exception:
                    pass

    return f"{platform.system()}-{platform.node()}-{uuid.getnode()}"


def compute_local_device_id_hash(custom_raw_id: str | None = None) -> str:
    """
    Compute a non-reversible SHA-256 device identifier hash bound to the OS Machine UUID.
    """
    raw = custom_raw_id or get_os_native_machine_uuid()
    return hashlib.sha256(DEVICE_HASH_SALT + raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class DeviceSeatRecord:
    """Server-side or authoritative licence seat state."""

    licence_id: str
    order_id: str
    customer_email: str
    sku: ProductSKU
    issued_at_iso: str
    updates_expire_at_iso: str
    active_device_id_hash: str | None = None
    activated_at_iso: str | None = None
    emergency_recovery_timestamps: list[str] = field(default_factory=list)
    revoked: bool = False


class ActivationManager:
    """
    Manages the 1-active-device seat rule, self-service deactivation,
    same-device reinstallation, and dead-device recovery.
    """

    def __init__(self, signing_private_key: Ed25519PrivateKey) -> None:
        self._private_key = signing_private_key
        self._seats: dict[str, DeviceSeatRecord] = {}

    def register_licence_seat(self, record: DeviceSeatRecord) -> None:
        self._seats[record.licence_id] = record

    def get_seat(self, licence_id: str) -> DeviceSeatRecord | None:
        return self._seats.get(licence_id)

    def activate_device(
        self,
        licence_id: str,
        device_id_hash: str,
        client_platform: PlatformOS,
        now_utc: datetime | None = None,
    ) -> SignedLicenceCertificate:
        """
        Activate `device_id_hash` on `licence_id` and return an Ed25519-signed certificate.
        - Rejects revoked licences.
        - Rejects platform mismatches (e.g. STANDARD-WIN on MACOS).
        - Allows idempotent re-activation if `active_device_id_hash == device_id_hash`
          (supporting seamless app/OS reinstalls on the same machine).
        - Rejects activation if another device is currently active.
        """
        seat = self._seats.get(licence_id)
        if seat is None:
            raise KeyError(f"Unknown licence ID: {licence_id}")
        if seat.revoked:
            raise PermissionError("This licence has been revoked due to a refund or chargeback.")
        if seat.sku.platform != client_platform:
            raise PermissionError(
                f"Platform mismatch: {seat.sku.value} cannot be activated on {client_platform.value}."
            )

        if seat.active_device_id_hash is not None and seat.active_device_id_hash != device_id_hash:
            raise PermissionError(
                "This licence is already active on another device. "
                "Please deactivate the existing device first or use Device Recovery."
            )

        now_iso = (now_utc or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
        seat.active_device_id_hash = device_id_hash
        seat.activated_at_iso = now_iso

        unsigned = SignedLicenceCertificate(
            licence_id=seat.licence_id,
            order_id=seat.order_id,
            sku=seat.sku,
            edition=seat.sku.edition,
            platform=seat.sku.platform,
            device_id_hash=device_id_hash,
            perpetual_usage=True,
            issued_at=seat.issued_at_iso,
            updates_expire_at=seat.updates_expire_at_iso,
            entitled_app_max_release_date=seat.updates_expire_at_iso,
        )
        return sign_licence_certificate(unsigned, self._private_key)

    def deactivate_device(self, licence_id: str, device_id_hash: str) -> bool:
        """Release the active device seat so the customer can activate a replacement machine."""
        seat = self._seats.get(licence_id)
        if seat is None:
            raise KeyError(f"Unknown licence ID: {licence_id}")
        if seat.active_device_id_hash != device_id_hash:
            raise PermissionError("Device hash does not match the currently active device.")
        seat.active_device_id_hash = None
        seat.activated_at_iso = None
        return True

    def recover_after_device_failure(
        self,
        licence_id: str,
        customer_email: str,
        new_device_id_hash: str,
        client_platform: PlatformOS,
        now_utc: datetime | None = None,
    ) -> SignedLicenceCertificate:
        """
        Recover access when the previous device suffered hardware failure or OS wipe
        without prior deactivation. Verified via customer email and rate-limited
        to `MAX_EMERGENCY_RECOVERIES_PER_YEAR` to prevent seat sharing abuse.
        """
        seat = self._seats.get(licence_id)
        if seat is None:
            raise KeyError(f"Unknown licence ID: {licence_id}")
        if seat.customer_email.strip().lower() != customer_email.strip().lower():
            raise PermissionError("Customer email does not match licence owner.")

        now = (now_utc or datetime.now(UTC)).astimezone(UTC)
        cutoff = now.timestamp() - 365 * 86400
        recent_recoveries = [
            ts
            for ts in seat.emergency_recovery_timestamps
            if datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() >= cutoff
        ]
        if len(recent_recoveries) >= MAX_EMERGENCY_RECOVERIES_PER_YEAR:
            raise PermissionError(
                "Maximum annual emergency device recoveries reached. Please contact support."
            )

        now_iso = now.isoformat().replace("+00:00", "Z")
        seat.emergency_recovery_timestamps = [*recent_recoveries, now_iso]
        seat.active_device_id_hash = None
        return self.activate_device(
            licence_id=licence_id,
            device_id_hash=new_device_id_hash,
            client_platform=client_platform,
            now_utc=now,
        )
