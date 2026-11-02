"""
Ed25519-Signed Offline Licence Certificate.
Represents the four independent entitlements (Product, Platform, Perpetual Usage,
and 12-Month Update Entitlement) verifiable 100% offline in < 1ms.
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class Edition(str, Enum):
    """Product edition."""

    STANDARD = "STANDARD"
    PRO = "PRO"


class PlatformOS(str, Enum):
    """Licensed operating system family."""

    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"


class ProductSKU(str, Enum):
    """Approved distinct product SKUs."""

    STANDARD_WIN = "STANDARD-WIN"
    PRO_WIN = "PRO-WIN"
    STANDARD_MAC = "STANDARD-MAC"
    PRO_MAC = "PRO-MAC"

    @property
    def edition(self) -> Edition:
        if self in (ProductSKU.PRO_WIN, ProductSKU.PRO_MAC):
            return Edition.PRO
        return Edition.STANDARD

    @property
    def platform(self) -> PlatformOS:
        if self in (ProductSKU.STANDARD_WIN, ProductSKU.PRO_WIN):
            return PlatformOS.WINDOWS
        return PlatformOS.MACOS


def detect_current_platform() -> PlatformOS:
    if sys.platform == "win32":
        return PlatformOS.WINDOWS
    if sys.platform == "darwin":
        return PlatformOS.MACOS
    return PlatformOS.LINUX


@dataclass(frozen=True, slots=True)
class SignedLicenceCertificate:
    """
    Immutable offline licence certificate containing the 4 commercial entitlements
    and Ed25519 cryptographic signature.
    """

    licence_id: str
    order_id: str
    sku: ProductSKU
    edition: Edition
    platform: PlatformOS
    device_id_hash: str
    perpetual_usage: bool
    issued_at: str
    updates_expire_at: str
    entitled_app_max_release_date: str
    signature_b64: str = ""

    def to_unsigned_dict(self) -> dict[str, object]:
        return {
            "licence_id": self.licence_id,
            "order_id": self.order_id,
            "sku": self.sku.value,
            "edition": self.edition.value,
            "platform": self.platform.value,
            "device_id_hash": self.device_id_hash,
            "perpetual_usage": self.perpetual_usage,
            "issued_at": self.issued_at,
            "updates_expire_at": self.updates_expire_at,
            "entitled_app_max_release_date": self.entitled_app_max_release_date,
        }

    def to_json(self) -> str:
        payload = self.to_unsigned_dict()
        payload["signature_b64"] = self.signature_b64
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> SignedLicenceCertificate:
        raw = json.loads(json_str)
        return cls(
            licence_id=str(raw["licence_id"]),
            order_id=str(raw["order_id"]),
            sku=ProductSKU(str(raw["sku"])),
            edition=Edition(str(raw["edition"])),
            platform=PlatformOS(str(raw["platform"])),
            device_id_hash=str(raw["device_id_hash"]),
            perpetual_usage=bool(raw["perpetual_usage"]),
            issued_at=str(raw["issued_at"]),
            updates_expire_at=str(raw["updates_expire_at"]),
            entitled_app_max_release_date=str(raw["entitled_app_max_release_date"]),
            signature_b64=str(raw.get("signature_b64", "")),
        )

    def get_updates_expire_datetime(self) -> datetime:
        return datetime.fromisoformat(
            self.updates_expire_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

    def get_entitled_max_release_datetime(self) -> datetime:
        return datetime.fromisoformat(
            self.entitled_app_max_release_date.replace("Z", "+00:00")
        ).astimezone(timezone.utc)


def _canonical_bytes(cert: SignedLicenceCertificate) -> bytes:
    return json.dumps(
        cert.to_unsigned_dict(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sign_licence_certificate(
    cert: SignedLicenceCertificate,
    private_key: Ed25519PrivateKey,
) -> SignedLicenceCertificate:
    """Sign `cert` with the licensing backend's Ed25519 private key."""
    sig = private_key.sign(_canonical_bytes(cert))
    sig_b64 = base64.b64encode(sig).decode("ascii")
    return SignedLicenceCertificate(
        licence_id=cert.licence_id,
        order_id=cert.order_id,
        sku=cert.sku,
        edition=cert.edition,
        platform=cert.platform,
        device_id_hash=cert.device_id_hash,
        perpetual_usage=cert.perpetual_usage,
        issued_at=cert.issued_at,
        updates_expire_at=cert.updates_expire_at,
        entitled_app_max_release_date=cert.entitled_app_max_release_date,
        signature_b64=sig_b64,
    )


def verify_licence_certificate(
    cert: SignedLicenceCertificate,
    public_key: Ed25519PublicKey,
    expected_device_id_hash: str | None = None,
    expected_platform: PlatformOS | None = None,
) -> tuple[bool, str]:
    """
    Verify a licence certificate offline:
    1. Ed25519 signature validity.
    2. SKU <-> Edition and SKU <-> Platform internal consistency.
    3. Platform match (e.g. a Windows licence is rejected on macOS).
    4. Device seat hash match (`device_id_hash`).
    """
    if not cert.signature_b64:
        return False, "Missing cryptographic signature"

    try:
        sig = base64.b64decode(cert.signature_b64)
        public_key.verify(sig, _canonical_bytes(cert))
    except Exception:
        return False, "Invalid Ed25519 licence signature"

    if cert.sku.edition != cert.edition or cert.sku.platform != cert.platform:
        return False, "SKU and edition/platform fields are inconsistent"

    if expected_platform is not None and cert.platform != expected_platform:
        return (
            False,
            f"Platform mismatch: licence {cert.sku.value} is for {cert.platform.value}, not {expected_platform.value}",
        )

    if expected_device_id_hash is not None and cert.device_id_hash != expected_device_id_hash:
        return False, "Licence is activated for a different device"

    return True, "VALID"
