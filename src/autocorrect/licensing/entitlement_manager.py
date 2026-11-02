"""
Unified Runtime Entitlement Manager.
Evaluates offline licence certificates and the 14-day trial state to determine:
- Whether typing assistance hooks should be active (`is_typing_assistance_enabled`).
- Whether Pro features (Local AI, BYOK Cloud AI, Snippets, Domain Packs, App Profiles) are unlocked.
- Whether new resource/app updates may be downloaded (`updates_expire_at`).
Automatically triggers registered hook-release callbacks when a trial expires so
the application safely stops intercepting keyboard input without deleting any user data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from autocorrect.env_config import creator_device_hashes, creator_name
from autocorrect.licensing.signed_licence import (
    Edition,
    PlatformOS,
    SignedLicenceCertificate,
    detect_current_platform,
    verify_licence_certificate,
)
from autocorrect.licensing.trial_manager import TrialManager, TrialStatus
from autocorrect.licensing.update_entitlement import (
    UpdateEntitlementEvaluator,
    UpdateEntitlementState,
)


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    """Complete snapshot of current commercial entitlements."""

    mode: str  # 'CREATOR_LIFETIME' | 'LICENSED_STANDARD' | 'LICENSED_PRO' | 'TRIAL_PRO' | 'TRIAL_EXPIRED' | 'UNLICENSED'
    typing_assistance_enabled: bool
    pro_features_enabled: bool
    can_download_new_updates: bool
    updates_expire_at: datetime | None
    status_message: str


class EntitlementManager:
    """
    Coordinates offline licence verification, trial fallback, and safe hook suspension.
    Implements `EntitlementCheckPort` used by `InputSessionManager`.
    """

    def __init__(
        self,
        public_key: Ed25519PublicKey,
        device_id_hash: str,
        trial_manager: TrialManager,
        current_platform: PlatformOS | None = None,
        on_typing_disabled_callback: Callable[[], None] | None = None,
    ) -> None:
        self._public_key = public_key
        self._device_id_hash = device_id_hash
        self._trial_manager = trial_manager
        self._platform = current_platform or detect_current_platform()
        self._on_typing_disabled = on_typing_disabled_callback
        self._active_cert: SignedLicenceCertificate | None = None
        self._last_snapshot: EntitlementSnapshot | None = None

    @property
    def active_certificate(self) -> SignedLicenceCertificate | None:
        return self._active_cert

    def is_creator_device(self) -> bool:
        """True when this device's SHA-256 id hash is listed as a creator device."""
        return self._device_id_hash.lower() in creator_device_hashes()

    def install_certificate(
        self,
        cert: SignedLicenceCertificate,
        now_utc: datetime | None = None,
    ) -> EntitlementSnapshot:
        """Verify and activate an offline licence certificate."""
        valid, reason = verify_licence_certificate(
            cert=cert,
            public_key=self._public_key,
            expected_device_id_hash=self._device_id_hash,
            expected_platform=self._platform,
        )
        if not valid:
            raise PermissionError(f"Licence rejected: {reason}")

        self._active_cert = cert
        return self.evaluate(now_utc=now_utc)

    def clear_certificate(self, now_utc: datetime | None = None) -> EntitlementSnapshot:
        """Remove local certificate (e.g. upon device deactivation)."""
        self._active_cert = None
        return self.evaluate(now_utc=now_utc)

    def evaluate(
        self,
        now_utc: datetime | None = None,
        app_release_dt: datetime | None = None,
        is_security_patch_build: bool = False,
    ) -> EntitlementSnapshot:
        """
        Evaluate current entitlements 100% offline.
        Creator devices (listed in `.env` as AUTOCORRECT_CREATOR_DEVICE_HASHES)
        hold a perpetual Pro entitlement with no update window.
        If a valid licence certificate is present, evaluates its perpetual and update rights.
        Otherwise falls back to the 14-day full-featured trial.
        """
        if self.is_creator_device():
            snap = EntitlementSnapshot(
                mode="CREATOR_LIFETIME",
                typing_assistance_enabled=True,
                pro_features_enabled=True,
                can_download_new_updates=True,
                updates_expire_at=None,
                status_message=f"{creator_name()} Lifetime Pro Licence (this device)",
            )
            self._apply_snapshot(snap)
            return snap

        if self._active_cert is not None:
            valid, reason = verify_licence_certificate(
                cert=self._active_cert,
                public_key=self._public_key,
                expected_device_id_hash=self._device_id_hash,
                expected_platform=self._platform,
            )
            if valid:
                upd_state: UpdateEntitlementState = UpdateEntitlementEvaluator.evaluate(
                    cert=self._active_cert,
                    now_utc=now_utc,
                    app_release_dt=app_release_dt,
                    is_security_patch_build=is_security_patch_build,
                )
                if not upd_state.can_use_current_app_perpetually:
                    snap = EntitlementSnapshot(
                        mode="UNLICENSED",
                        typing_assistance_enabled=False,
                        pro_features_enabled=False,
                        can_download_new_updates=False,
                        updates_expire_at=upd_state.updates_expire_at,
                        status_message="This application build was released after your update entitlement expired.",
                    )
                    self._apply_snapshot(snap)
                    return snap

                is_pro = self._active_cert.edition == Edition.PRO
                mode = "LICENSED_PRO" if is_pro else "LICENSED_STANDARD"
                msg = (
                    f"{self._active_cert.sku.value} Active (Updates until {upd_state.updates_expire_at.date().isoformat()})"
                    if upd_state.is_within_update_window
                    else f"{self._active_cert.sku.value} Perpetual Licence Active (Update window ended {upd_state.updates_expire_at.date().isoformat()})"
                )
                snap = EntitlementSnapshot(
                    mode=mode,
                    typing_assistance_enabled=True,
                    pro_features_enabled=is_pro,
                    can_download_new_updates=upd_state.is_within_update_window,
                    updates_expire_at=upd_state.updates_expire_at,
                    status_message=msg,
                )
                self._apply_snapshot(snap)
                return snap

        # No valid paid licence: evaluate 14-day full-featured trial
        trial: TrialStatus = self._trial_manager.evaluate_trial(now_utc=now_utc)
        if trial.is_usable:
            snap = EntitlementSnapshot(
                mode="TRIAL_PRO",
                typing_assistance_enabled=True,
                pro_features_enabled=True,
                can_download_new_updates=True,
                updates_expire_at=trial.expires_at,
                status_message=f"14-Day Full Pro Trial Active ({trial.days_remaining:.1f} days remaining)",
            )
            self._apply_snapshot(snap)
            return snap

        snap = EntitlementSnapshot(
            mode="TRIAL_EXPIRED",
            typing_assistance_enabled=False,
            pro_features_enabled=False,
            can_download_new_updates=False,
            updates_expire_at=None,
            status_message="14-Day Trial Expired — Activate a Standard or Pro licence to resume typing assistance.",
        )
        self._apply_snapshot(snap)
        return snap

    def _apply_snapshot(self, snapshot: EntitlementSnapshot) -> None:
        self._last_snapshot = snapshot
        if not snapshot.typing_assistance_enabled and self._on_typing_disabled is not None:
            self._on_typing_disabled()

    def is_typing_assistance_enabled(self) -> bool:
        if self._last_snapshot is None:
            self.evaluate()
        assert self._last_snapshot is not None
        return self._last_snapshot.typing_assistance_enabled

    def is_pro_enabled(self) -> bool:
        if self._last_snapshot is None:
            self.evaluate()
        assert self._last_snapshot is not None
        return self._last_snapshot.pro_features_enabled
