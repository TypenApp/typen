"""
Local Licence Persistence Service (`licence_service.py`).
Loads and persists signed `entitlement.lic` files on disk so activated
installations remain 100% verifiable offline across restarts, internet
disconnections, and server outages.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from autocorrect.licensing.activation_manager import ActivationManager
from autocorrect.licensing.entitlement_manager import EntitlementManager, EntitlementSnapshot
from autocorrect.licensing.signed_licence import (
    PlatformOS,
    SignedLicenceCertificate,
    detect_current_platform,
)


class LicenceService:
    """
    Coordinates local persistence of `entitlement.lic` and interactions with `EntitlementManager`
    and `ActivationManager`.
    """

    def __init__(
        self,
        licence_file_path: Path,
        entitlement_manager: EntitlementManager,
        device_id_hash: str,
        activation_manager: ActivationManager | None = None,
        current_platform: PlatformOS | None = None,
    ) -> None:
        self._lic_path = licence_file_path
        self._entitlement_mgr = entitlement_manager
        self._device_id_hash = device_id_hash
        self._activation_mgr = activation_manager
        self._platform = current_platform or detect_current_platform()

    @property
    def licence_file_path(self) -> Path:
        return self._lic_path

    def load_cached_licence_offline(
        self, now_utc: datetime | None = None
    ) -> EntitlementSnapshot:
        """
        Load `entitlement.lic` from local disk if present and evaluate offline.
        Never requires a network connection.
        """
        if self._lic_path.exists():
            try:
                cert = SignedLicenceCertificate.from_json(
                    self._lic_path.read_text(encoding="utf-8")
                )
                return self._entitlement_mgr.install_certificate(cert, now_utc=now_utc)
            except Exception:
                pass
        return self._entitlement_mgr.evaluate(now_utc=now_utc)

    def save_and_activate_certificate(
        self,
        cert: SignedLicenceCertificate,
        now_utc: datetime | None = None,
    ) -> EntitlementSnapshot:
        """Verify `cert` and atomically persist `entitlement.lic` to disk."""
        snap = self._entitlement_mgr.install_certificate(cert, now_utc=now_utc)
        self._lic_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._lic_path.with_suffix(".lic.tmp")
        tmp_path.write_text(cert.to_json(), encoding="utf-8")
        os.replace(tmp_path, self._lic_path)
        return snap

    def activate_with_licence_key(
        self,
        licence_id: str,
        now_utc: datetime | None = None,
    ) -> EntitlementSnapshot:
        """Activate a licence key against the activation service and persist offline."""
        if self._activation_mgr is None:
            raise RuntimeError("ActivationManager is not configured")
        cert = self._activation_mgr.activate_device(
            licence_id=licence_id,
            device_id_hash=self._device_id_hash,
            client_platform=self._platform,
            now_utc=now_utc,
        )
        return self.save_and_activate_certificate(cert, now_utc=now_utc)

    def deactivate_current_device(
        self,
        now_utc: datetime | None = None,
    ) -> EntitlementSnapshot:
        """Deactivate the current device seat and remove local `entitlement.lic`."""
        cert = self._entitlement_mgr.active_certificate
        if cert is not None and self._activation_mgr is not None:
            self._activation_mgr.deactivate_device(cert.licence_id, self._device_id_hash)
        self._lic_path.unlink(missing_ok=True)
        return self._entitlement_mgr.clear_certificate(now_utc=now_utc)
