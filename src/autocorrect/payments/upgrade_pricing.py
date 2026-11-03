"""
Upgrade and Renewal Price Calculator.
Computes exact decimal amounts for:
1. Full retail new purchases ($14.99 Standard / $34.99 Pro).
2. 30% discounted 12-month update renewals ($10.49 Standard / $24.49 Pro).
3. Active Standard-to-Pro cross-grades ($20.00 retail differential).
4. Expired Standard-to-Pro cross-grades ($24.49 - 30% off Pro retail).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from autocorrect.licensing.signed_licence import ProductSKU, SignedLicenceCertificate
from autocorrect.licensing.upgrade_manager import UpgradeManager, UpgradeType
from autocorrect.payments.pricing_config import PricingConfig


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """Calculated server-side price quote for a checkout session."""

    target_sku: ProductSKU
    upgrade_type: UpgradeType
    retail_amount: Decimal
    final_amount: Decimal
    currency: str
    requires_adhoc_override: bool
    parent_licence_id: str | None = None

    @property
    def final_amount_str(self) -> str:
        """Decimal string formatted to 2 decimal places (e.g. '10.49') as required by BACHS."""
        return f"{self.final_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


class UpgradePricingCalculator:
    """Calculates authoritative checkout prices from `PricingConfig`."""

    def __init__(self, config: PricingConfig | None = None) -> None:
        self._config = config or PricingConfig()

    @property
    def config(self) -> PricingConfig:
        return self._config

    def calculate_quote(
        self,
        target_sku: ProductSKU,
        existing_cert: SignedLicenceCertificate | None = None,
        now_utc: datetime | None = None,
    ) -> PriceQuote:
        retail = self._config.get_retail_price(target_sku)

        if existing_cert is None:
            return PriceQuote(
                target_sku=target_sku,
                upgrade_type=UpgradeType.NEW_PURCHASE,
                retail_amount=retail,
                final_amount=retail,
                currency=self._config.primary_currency,
                requires_adhoc_override=False,
                parent_licence_id=None,
            )

        eligibility = UpgradeManager.evaluate_upgrade(
            existing_cert=existing_cert,
            target_sku=target_sku,
            now_utc=now_utc,
        )
        if not eligibility.eligible:
            raise PermissionError(eligibility.reason)

        discount_mult = Decimal("1.00") - self._config.renewal_discount_fraction

        if eligibility.upgrade_type == UpgradeType.RENEWAL_30PCT:
            # e.g. $14.99 * 0.70 = $10.493 -> $10.49; $34.99 * 0.70 = $24.493 -> $24.49
            discounted = (retail * discount_mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return PriceQuote(
                target_sku=target_sku,
                upgrade_type=UpgradeType.RENEWAL_30PCT,
                retail_amount=retail,
                final_amount=discounted,
                currency=self._config.primary_currency,
                requires_adhoc_override=True,
                parent_licence_id=existing_cert.licence_id,
            )

        if eligibility.upgrade_type == UpgradeType.CROSSGRADE_ACTIVE:
            # Fair active Standard-to-Pro cross-grade: pay the retail difference ($34.99 - $14.99 = $20.00)
            std_retail = self._config.standard_retail_price
            diff = max(Decimal("0.01"), retail - std_retail).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return PriceQuote(
                target_sku=target_sku,
                upgrade_type=UpgradeType.CROSSGRADE_ACTIVE,
                retail_amount=retail,
                final_amount=diff,
                currency=self._config.primary_currency,
                requires_adhoc_override=True,
                parent_licence_id=existing_cert.licence_id,
            )

        # CROSSGRADE_EXPIRED: 30% off Pro retail ($24.49)
        expired_crossgrade = (retail * discount_mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return PriceQuote(
            target_sku=target_sku,
            upgrade_type=UpgradeType.CROSSGRADE_EXPIRED,
            retail_amount=retail,
            final_amount=expired_crossgrade,
            currency=self._config.primary_currency,
            requires_adhoc_override=True,
            parent_licence_id=existing_cert.licence_id,
        )
