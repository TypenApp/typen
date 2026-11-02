"""
Provider-Independent Commercial Payments & BACHS Integration Package.
Provides:
- `pricing_config.py`: Configurable retail pricing, SKUs, and regional currency options.
- `upgrade_pricing.py`: 30% renewal and Standard-to-Pro cross-grade calculator.
- `provider_port.py`: Hexagonal `PaymentProviderPort` abstraction (decoupling BACHS vs future MoR).
- `bachs_adapter.py`: Official BACHS SDK (`bachs>=2.0.0`) + REST adapter for refunds/disputes.
- `purchase_verification.py`: Webhook signature verification, deduplication, amount/currency matching,
  idempotent licence issuance, refund/dispute handling, and reconciliation.
- `checkout_manager.py`: End-to-end 9-step checkout and activation coordinator.
"""

from autocorrect.payments.bachs_adapter import BachsPaymentAdapter
from autocorrect.payments.checkout_manager import CheckoutManager, CheckoutSessionResult
from autocorrect.payments.pricing_config import PricingConfig
from autocorrect.payments.provider_port import (
    PaymentProviderPort,
    ProviderCheckoutRequest,
    ProviderCheckoutSession,
    ProviderDisputeState,
    ProviderRefundState,
    ProviderWebhookEvent,
)
from autocorrect.payments.purchase_verification import (
    OrderRecord,
    OrderStatus,
    PurchaseVerificationService,
)
from autocorrect.payments.upgrade_pricing import PriceQuote, UpgradePricingCalculator

__all__ = [
    "BachsPaymentAdapter",
    "CheckoutManager",
    "CheckoutSessionResult",
    "OrderRecord",
    "OrderStatus",
    "PaymentProviderPort",
    "PriceQuote",
    "PricingConfig",
    "ProviderCheckoutRequest",
    "ProviderCheckoutSession",
    "ProviderDisputeState",
    "ProviderRefundState",
    "ProviderWebhookEvent",
    "PurchaseVerificationService",
    "UpgradePricingCalculator",
]
