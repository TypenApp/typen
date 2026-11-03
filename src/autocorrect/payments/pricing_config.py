"""
Configurable Retail Pricing, Regional Currency Options, and SKU Catalog Mapping.
Ensures prices are never hardcoded throughout the application and can be updated
through configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from autocorrect.licensing.signed_licence import Edition, ProductSKU


@dataclass(slots=True)
class PricingConfig:
    """
    Central configurable pricing rules for Standard and Pro editions,
    renewal discounts, and regional currency options.
    """

    primary_currency: str = "USD"
    standard_retail_price: Decimal = Decimal("14.99")
    pro_retail_price: Decimal = Decimal("34.99")
    renewal_discount_fraction: Decimal = Decimal("0.30")  # 30% discount

    # Mapping of ProductSKU -> provider catalog product_id (configured per environment)
    sku_to_provider_product_id: dict[ProductSKU, str] = field(
        default_factory=lambda: {
            ProductSKU.STANDARD_WIN: "prod_standard_win",
            ProductSKU.PRO_WIN: "prod_pro_win",
            ProductSKU.STANDARD_MAC: "prod_standard_mac",
            ProductSKU.PRO_MAC: "prod_pro_mac",
            ProductSKU.STANDARD_LINUX: "prod_standard_linux",
            ProductSKU.PRO_LINUX: "prod_pro_linux",
        }
    )

    # Optional regional fixed prices (BACHS `currency_options` per edition)
    standard_regional_prices: dict[str, Decimal] = field(
        default_factory=lambda: {
            "NGN": Decimal("22500.00"),
            "GHS": Decimal("225.00"),
            "KES": Decimal("1950.00"),
        }
    )
    pro_regional_prices: dict[str, Decimal] = field(
        default_factory=lambda: {
            "NGN": Decimal("52500.00"),
            "GHS": Decimal("525.00"),
            "KES": Decimal("4550.00"),
        }
    )

    def get_retail_price(self, sku: ProductSKU) -> Decimal:
        if sku.edition == Edition.PRO:
            return self.pro_retail_price
        return self.standard_retail_price

    def get_provider_product_id(self, sku: ProductSKU) -> str:
        return self.sku_to_provider_product_id[sku]

    def get_currency_options_for_sku(self, sku: ProductSKU) -> list[dict[str, str]]:
        """Format regional currency options for BACHS product creation (`currency_options`)."""
        table = self.pro_regional_prices if sku.edition == Edition.PRO else self.standard_regional_prices
        return [
            {"currency": code, "amount": f"{amt:.2f}"}
            for code, amt in sorted(table.items())
            if code != self.primary_currency
        ]
