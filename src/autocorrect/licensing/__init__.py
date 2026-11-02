"""
Commercial Licensing & Offline Entitlement Package.
Enforces the four independent entitlements:
1. Product entitlement ('STANDARD' | 'PRO')
2. Platform entitlement ('STANDARD-WIN', 'PRO-WIN', 'STANDARD-MAC', 'PRO-MAC')
3. Perpetual usage entitlement (never disables purchased app when updates expire)
4. 12-month time-limited update entitlement
Plus the 14-day full-featured tamper-resistant trial and 1-device activation.
"""

from autocorrect.licensing.activation_manager import ActivationManager, DeviceSeatRecord
from autocorrect.licensing.entitlement_manager import EntitlementManager, EntitlementSnapshot
from autocorrect.licensing.licence_service import LicenceService
from autocorrect.licensing.signed_licence import (
    Edition,
    PlatformOS,
    ProductSKU,
    SignedLicenceCertificate,
    sign_licence_certificate,
    verify_licence_certificate,
)
from autocorrect.licensing.trial_manager import TrialManager, TrialStatus
from autocorrect.licensing.update_entitlement import UpdateEntitlementEvaluator
from autocorrect.licensing.upgrade_manager import UpgradeEligibility, UpgradeManager, UpgradeType

__all__ = [
    "ActivationManager",
    "DeviceSeatRecord",
    "Edition",
    "EntitlementManager",
    "EntitlementSnapshot",
    "LicenceService",
    "PlatformOS",
    "ProductSKU",
    "SignedLicenceCertificate",
    "TrialManager",
    "TrialStatus",
    "UpdateEntitlementEvaluator",
    "UpgradeEligibility",
    "UpgradeManager",
    "UpgradeType",
    "sign_licence_certificate",
    "verify_licence_certificate",
]
