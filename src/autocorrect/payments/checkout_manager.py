"""
End-to-End 9-Step Checkout and Fulfilment Coordinator (`checkout_manager.py`).
Implements the approved BACHS payment lifecycle:
1. Desktop application requests a checkout session from the licensing backend.
2. Backend validates product, platform, price, and upgrade eligibility.
3. Backend creates the BACHS checkout session.
4. Customer completes hosted checkout.
5. BACHS sends a signed payment webhook.
6. Backend verifies signature and independently validates amount, currency, reference, and product.
7. Backend records the successful transaction.
8. Backend issues the appropriate signed licence entitlement.
9. Desktop application retrieves and activates its entitlement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from autocorrect.licensing.entitlement_manager import EntitlementSnapshot
from autocorrect.licensing.licence_service import LicenceService
from autocorrect.licensing.signed_licence import ProductSKU, SignedLicenceCertificate
from autocorrect.payments.provider_port import PaymentProviderPort, ProviderCheckoutRequest
from autocorrect.payments.purchase_verification import PurchaseVerificationService
from autocorrect.payments.upgrade_pricing import PriceQuote, UpgradePricingCalculator


@dataclass(frozen=True, slots=True)
class CheckoutSessionResult:
    """Returned to the desktop client when initiating a purchase or upgrade."""

    order_id: str
    provider_checkout_id: str
    checkout_url: str
    quote: PriceQuote


class CheckoutManager:
    """
    Coordinates server-validated checkout creation and post-webhook client activation.
    """

    def __init__(
        self,
        provider: PaymentProviderPort,
        verification_service: PurchaseVerificationService,
        pricing_calculator: UpgradePricingCalculator | None = None,
    ) -> None:
        self._provider = provider
        self._verification = verification_service
        self._pricing = pricing_calculator or UpgradePricingCalculator()

    def initiate_checkout(
        self,
        target_sku: ProductSKU,
        device_id_hash: str,
        existing_cert: SignedLicenceCertificate | None = None,
        customer_email: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
        now_utc: datetime | None = None,
    ) -> CheckoutSessionResult:
        """
        Steps 1-3: Validate SKU/upgrade eligibility, persist a PENDING order with
        an idempotency key, and create the BACHS hosted checkout session.
        """
        quote = self._pricing.calculate_quote(
            target_sku=target_sku,
            existing_cert=existing_cert,
            now_utc=now_utc,
        )
        order = self._verification.create_pending_order(
            sku=target_sku,
            upgrade_type=quote.upgrade_type,
            expected_amount=quote.final_amount,
            expected_currency=quote.currency,
            device_id_hash=device_id_hash,
            parent_licence_id=quote.parent_licence_id,
            customer_email=customer_email,
            now_utc=now_utc,
        )
        provider_product_id = self._pricing.config.get_provider_product_id(target_sku)

        req = ProviderCheckoutRequest(
            order_reference=order.order_id,
            idempotency_key=order.idempotency_key,
            provider_product_id=provider_product_id,
            expected_amount_str=quote.final_amount_str,
            currency=quote.currency,
            override_catalog_price=quote.requires_adhoc_override,
            customer_email=customer_email,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "order_id": order.order_id,
                "sku": target_sku.value,
                "upgrade_type": quote.upgrade_type.value,
                "parent_licence_id": quote.parent_licence_id or "",
            },
        )
        session = self._provider.create_checkout_session(req)
        self._verification.attach_provider_checkout_id(order.order_id, session.provider_checkout_id)

        return CheckoutSessionResult(
            order_id=order.order_id,
            provider_checkout_id=session.provider_checkout_id,
            checkout_url=session.checkout_url,
            quote=quote,
        )

    def retrieve_and_activate_on_client(
        self,
        order_id: str,
        licence_service: LicenceService,
        device_id_hash: str,
        now_utc: datetime | None = None,
    ) -> EntitlementSnapshot:
        """
        Step 9: After the webhook has verified payment and fulfilled the order,
        retrieve the Ed25519-signed certificate and activate it on the desktop client.
        """
        cert = self._verification.activate_fulfilled_order(
            order_id=order_id,
            device_id_hash=device_id_hash,
            now_utc=now_utc,
        )
        return licence_service.save_and_activate_certificate(cert, now_utc=now_utc)
