"""
Desktop Application Binary Updater.
Verifies Ed25519-signed release manifests, enforces the 12-month update
entitlement window (and security-patch overrides), and guarantees that an
unentitled update is never downloaded or staged over a working perpetual installation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from autocorrect.updates.update_policy import UpdateEligibilityResult, UpdatePolicyEngine
from pipeline.sign_release import verify_manifest_signature


@dataclass(frozen=True, slots=True)
class ApplicationReleaseDescriptor:
    """Signed metadata for a desktop application release."""

    version: str
    platform_sku_suffix: str  # 'WIN' | 'MAC' | 'LINUX'
    released_at: str
    installer_sha256: str
    installer_size: int
    download_url: str
    is_security_patch: bool = False
    target_branch_prefix: str = "1.2."

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "platform_sku_suffix": self.platform_sku_suffix,
            "released_at": self.released_at,
            "installer_sha256": self.installer_sha256,
            "installer_size": self.installer_size,
            "download_url": self.download_url,
            "is_security_patch": self.is_security_patch,
            "target_branch_prefix": self.target_branch_prefix,
        }


class ApplicationUpdater:
    """Verifies and stages desktop application updates within entitlement bounds."""

    def __init__(self, staging_dir: Path, public_key: Ed25519PublicKey) -> None:
        self._staging_dir = staging_dir
        self._public_key = public_key

    def evaluate_release(
        self,
        descriptor: ApplicationReleaseDescriptor,
        signature_b64: str,
        updates_expire_at: datetime | None,
        current_app_version: str,
    ) -> UpdateEligibilityResult:
        if not verify_manifest_signature(
            descriptor.to_canonical_dict(), signature_b64, self._public_key
        ):
            return UpdateEligibilityResult(
                eligible=False,
                reason="Invalid Ed25519 application release signature",
            )

        return UpdatePolicyEngine.check_app_update_eligibility(
            remote_version=descriptor.version,
            remote_released_at_iso=descriptor.released_at,
            is_security_patch=descriptor.is_security_patch,
            target_branch_prefix=descriptor.target_branch_prefix,
            updates_expire_at=updates_expire_at,
            current_app_version=current_app_version,
        )

    def stage_verified_installer(
        self,
        descriptor: ApplicationReleaseDescriptor,
        signature_b64: str,
        installer_bytes: bytes,
        updates_expire_at: datetime | None,
        current_app_version: str,
    ) -> Path:
        eligibility = self.evaluate_release(
            descriptor, signature_b64, updates_expire_at, current_app_version
        )
        if not eligibility.eligible:
            raise PermissionError(f"Application update not eligible: {eligibility.reason}")

        actual_sha = hashlib.sha256(installer_bytes).hexdigest()
        if actual_sha != descriptor.installer_sha256:
            raise ValueError("Installer SHA-256 verification failed")

        self._staging_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._staging_dir / f"autocorrect-setup-{descriptor.version}.bin"
        out_path.write_bytes(installer_bytes)
        return out_path
