"""
Provider-Independent Payment Infrastructure Port (`PaymentProviderPort`).
Decouples the licensing, checkout, and entitlement engine from any single payment
gateway so BACHS serves as the primary adapter while Paddle or Lemon Squeezy
can be swapped in without modifying core licensing logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderCheckoutRequest:
    """Normalized request to create a hosted one-time checkout session."""

    order_reference: str  # Unique per organization (max 128 chars)
    idempotency_key: str
    provider_product_id: str
    expected_amount_str: str  # Decimal string, e.g. '14.99' or '10.49'
    currency: str  # e.g. 'USD'
    override_catalog_price: bool = False  # True for discounted renewals & cross-grades
    customer_email: str | None = None
    customer_name: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderCheckoutSession:
    """Normalized checkout session state returned by the payment provider."""

    provider_checkout_id: str
    checkout_url: str
    status: str  # 'open' | 'completed' | 'expired'
    payment_status: str | None  # 'paid' | 'succeeded' | 'no_payment_required' | None
    amount_str: str
    currency: str
    reference: str | None
    customer_email: str | None = None
    charge_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderWebhookEvent:
    """Normalized verified webhook event from the payment provider."""

    event_id: str  # e.g. 'evt_...'
    event_type: str  # e.g. 'checkout.completed', 'collection.succeeded', 'refund.paid', 'dispute.created'
    created_at_iso: str
    checkout_id: str | None
    charge_id: str | None
    reference: str | None
    amount_str: str | None
    currency: str | None
    status: str | None
    customer_email: str | None = None
    raw_data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderRefundState:
    """Normalized refund state."""

    refund_id: str
    charge_id: str
    reference: str
    status: str  # 'processing' | 'paid' | 'success' | 'failed'
    requested_amount_str: str
    refunded_amount_str: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDisputeState:
    """Normalized dispute / chargeback state."""

    dispute_id: str
    charge_id: str
    amount_str: str
    currency: str
    status: str  # 'needs_response' | 'under_review' | 'won' | 'lost' | 'closed' | 'prevented'
    reason: str | None
    response_deadline_at: str | None
    is_response_editable: bool = True


class PaymentProviderPort(Protocol):
    """Hexagonal port for payment collection, webhook verification, refunds, and disputes."""

    @property
    def provider_name(self) -> str: ...

    def create_checkout_session(self, request: ProviderCheckoutRequest) -> ProviderCheckoutSession: ...

    def retrieve_checkout_session(self, provider_checkout_id: str) -> ProviderCheckoutSession: ...

    def verify_and_parse_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> ProviderWebhookEvent: ...

    def issue_refund(
        self,
        charge_id: str,
        reference: str,
        idempotency_key: str,
        amount: Decimal | None = None,
        reason: str = "Customer requested refund",
    ) -> ProviderRefundState: ...

    def retrieve_dispute(self, dispute_id: str) -> ProviderDisputeState: ...
