"""
Upgrade and Renewal Eligibility Manager.
Evaluates eligibility for:
1. Voluntary 12-month update renewal at 30% discount (`RENEWAL_30PCT`).
2. Standard-to-Pro cross-grade while within an active Standard update window (`CROSSGRADE_ACTIVE` - $20 difference).
3. Standard-to-Pro cross-grade after Standard update window has expired (`CROSSGRADE_EXPIRED` - 30% off Pro retail).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from autocorrect.licensing.signed_licence import Edition, ProductSKU, SignedLicenceCertificate


class UpgradeType(str, Enum):
    """Types of commercial purchase transactions."""

    NEW_PURCHASE = "NEW_PURCHASE"
    RENEWAL_30PCT = "RENEWAL_30PCT"
    CROSSGRADE_ACTIVE = "CROSSGRADE_ACTIVE"
    CROSSGRADE_EXPIRED = "CROSSGRADE_EXPIRED"


@dataclass(frozen=True, slots=True)
class UpgradeEligibility:
    """Result of checking a customer's upgrade or renewal eligibility."""

    eligible: bool
    upgrade_type: UpgradeType
    source_sku: ProductSKU
    target_sku: ProductSKU
    reason: str


class UpgradeManager:
    """Determines valid upgrade paths and target SKUs for an existing licence holder."""

    @staticmethod
    def evaluate_upgrade(
        existing_cert: SignedLicenceCertificate,
        target_sku: ProductSKU,
        now_utc: datetime | None = None,
    ) -> UpgradeEligibility:
        now = (now_utc or datetime.now(UTC)).astimezone(UTC)

        # Must be on the same OS platform (Windows licences upgrade to Windows SKUs; macOS to macOS)
        if existing_cert.platform != target_sku.platform:
            return UpgradeEligibility(
                eligible=False,
                upgrade_type=UpgradeType.NEW_PURCHASE,
                source_sku=existing_cert.sku,
                target_sku=target_sku,
                reason=(
                    f"Cross-platform upgrades are not supported ({existing_cert.sku.value} -> "
                    f"{target_sku.value}). Windows and macOS require separate licences."
                ),
            )

        # Cannot downgrade from Pro to Standard
        if existing_cert.edition == Edition.PRO and target_sku.edition == Edition.STANDARD:
            return UpgradeEligibility(
                eligible=False,
                upgrade_type=UpgradeType.NEW_PURCHASE,
                source_sku=existing_cert.sku,
                target_sku=target_sku,
                reason="Cannot downgrade a Pro licence to Standard.",
            )

        updates_active = now <= existing_cert.get_updates_expire_datetime()

        # Same edition (Standard -> Standard or Pro -> Pro): 30% Update Renewal
        if existing_cert.edition == target_sku.edition:
            return UpgradeEligibility(
                eligible=True,
                upgrade_type=UpgradeType.RENEWAL_30PCT,
                source_sku=existing_cert.sku,
                target_sku=target_sku,
                reason="Eligible for 30% discounted 12-month update entitlement renewal.",
            )

        # Standard -> Pro Cross-grade
        if updates_active:
            return UpgradeEligibility(
                eligible=True,
                upgrade_type=UpgradeType.CROSSGRADE_ACTIVE,
                source_sku=existing_cert.sku,
                target_sku=target_sku,
                reason="Eligible for active Standard-to-Pro cross-grade at retail price difference.",
            )

        return UpgradeEligibility(
            eligible=True,
            upgrade_type=UpgradeType.CROSSGRADE_EXPIRED,
            source_sku=existing_cert.sku,
            target_sku=target_sku,
            reason="Eligible for expired Standard-to-Pro upgrade at 30% loyalty discount.",
        )
