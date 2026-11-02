"""
BACHS Payment Infrastructure Adapter (`https://docs.bachs.io/`).
Uses:
- Official `bachs` Python SDK (`>= 2.0.0`) for:
  - `bachs.checkout_sessions.create` (one-time `product_cart`, ad-hoc `pricing` overrides
    for 30% renewals and cross-grades, unique `reference`, and `idempotency_key`)
  - `bachs.checkout_sessions.get`
  - `bachs.products.create`
  - `bachs.webhooks.construct_event` (`X-Bachs-Signature-V2` verification over raw request bytes)
- Authenticated `httpx` REST client for endpoints not yet in the Python SDK:
  - `/v1/refunds` (`POST /v1/refunds`, `GET /v1/refunds/{id}`)
  - `/v1/disputes` (`GET /v1/disputes/{id}`, `PATCH /v1/disputes/{id}/evidence`, `POST /v1/disputes/{id}/submit`)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

import httpx
from bachs import (
    Bachs,
    BachsApiError,
    BachsNetworkError,
    BachsResponseError,
    BachsWebhookError,
    webhooks,
)

from autocorrect.payments.provider_port import (
    ProviderCheckoutRequest,
    ProviderCheckoutSession,
    ProviderDisputeState,
    ProviderRefundState,
    ProviderWebhookEvent,
)


class UncertainWriteError(RuntimeError):
    """
    Raised when a BACHS write operation fails in transit with `outcome_unknown=True`.
    Callers must reconcile the operation before retrying with the SAME `idempotency_key`.
    """

    def __init__(self, message: str, idempotency_key: str, reference: str) -> None:
        super().__init__(message)
        self.idempotency_key = idempotency_key
        self.reference = reference


class BachsPaymentAdapter:
    """
    Production-grade adapter for BACHS implementing `PaymentProviderPort`.
    """

    def __init__(
        self,
        api_key: str,
        webhook_secret: str,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._http_client = http_client

        sdk_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url is not None:
            sdk_kwargs["base_url"] = base_url
        if http_client is not None:
            sdk_kwargs["http_client"] = http_client

        self._client = Bachs(**sdk_kwargs)
        self._rest_base_url = (
            base_url
            or (
                "https://sandbox-api.bachs.io"
                if api_key.startswith("sk_sandbox_")
                else "https://api.bachs.io"
            )
        ).rstrip("/")

    @property
    def provider_name(self) -> str:
        return "BACHS"

    @property
    def sdk_client(self) -> Bachs:
        return self._client

    def create_catalog_product(
        self,
        name: str,
        amount_str: str,
        currency: str,
        idempotency_key: str,
        currency_options: list[dict[str, str]] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """
        Create a one-time product in BACHS (`billing_cycle` is intentionally omitted
        so the product is strictly a one-time purchase, never a recurring subscription).
        """
        price_obj: dict[str, Any] = {
            "currency": currency,
            "amount": amount_str,
        }
        if currency_options:
            price_obj["currency_options"] = currency_options

        kwargs: dict[str, Any] = {
            "name": name,
            "price": price_obj,
            "idempotency_key": idempotency_key,
        }
        if metadata:
            kwargs["metadata"] = metadata

        product = self._client.products.create(**kwargs)
        return str(product.id)

    def create_checkout_session(
        self, request: ProviderCheckoutRequest
    ) -> ProviderCheckoutSession:
        """
        Create a hosted checkout session via `bachs.checkout_sessions.create`.
        Uses `product_cart[].pricing` override when `request.override_catalog_price=True`
        (for 30% update renewals and Standard-to-Pro cross-grades).
        """
        cart_item: dict[str, Any] = {
            "product_id": request.provider_product_id,
            "quantity": 1,
        }
        if request.override_catalog_price:
            cart_item["pricing"] = {
                "price_type": "fixed",
                "amount": request.expected_amount_str,
            }

        kwargs: dict[str, Any] = {
            "product_cart": [cart_item],
            "reference": request.order_reference,
            "metadata": dict(request.metadata),
            "idempotency_key": request.idempotency_key,
        }

        if request.customer_email:
            cust: dict[str, str] = {"email": request.customer_email}
            if request.customer_name:
                cust["name"] = request.customer_name
            kwargs["customer"] = cust

        # Note: BACHS rejects localhost/private IPs for success_url and cancel_url;
        # only include them when public URLs are configured.
        if request.success_url and not self._is_private_or_local_url(request.success_url):
            kwargs["success_url"] = request.success_url
        if request.cancel_url and not self._is_private_or_local_url(request.cancel_url):
            kwargs["cancel_url"] = request.cancel_url

        try:
            session = self._client.checkout_sessions.create(**kwargs)
        except (BachsApiError, BachsNetworkError, BachsResponseError) as err:
            if getattr(err, "outcome_unknown", False):
                raise UncertainWriteError(
                    f"BACHS checkout creation outcome unknown: {err}",
                    idempotency_key=request.idempotency_key,
                    reference=request.order_reference,
                ) from err
            raise

        raw_dict = session.to_dict() if hasattr(session, "to_dict") else {}
        return ProviderCheckoutSession(
            provider_checkout_id=str(session.checkout_id),
            checkout_url=str(session.checkout_url),
            status=str(getattr(session, "status", "open")),
            payment_status=raw_dict.get("payment_status"),
            amount_str=str(raw_dict.get("amount") or request.expected_amount_str),
            currency=str(raw_dict.get("currency") or request.currency),
            reference=str(raw_dict.get("reference") or request.order_reference),
            metadata=dict(raw_dict.get("metadata") or request.metadata),
        )

    def retrieve_checkout_session(
        self, provider_checkout_id: str
    ) -> ProviderCheckoutSession:
        """Fetch authoritative checkout session state from BACHS via SDK."""
        session = self._client.checkout_sessions.get(provider_checkout_id)
        raw = session.to_dict() if hasattr(session, "to_dict") else {}

        cust_email: str | None = None
        cust_details = raw.get("customer_details")
        if isinstance(cust_details, dict) and cust_details.get("email"):
            cust_email = str(cust_details["email"])
        elif isinstance(raw.get("customer"), dict) and raw["customer"].get("email"):
            cust_email = str(raw["customer"]["email"])

        charge_obj = raw.get("charge")
        charge_id: str | None = None
        if isinstance(charge_obj, dict):
            raw_cid = charge_obj.get("payment_id") or charge_obj.get("id")
            if raw_cid:
                charge_id = str(raw_cid)

        return ProviderCheckoutSession(
            provider_checkout_id=str(session.checkout_id),
            checkout_url=str(getattr(session, "checkout_url", "")),
            status=str(getattr(session, "status", "")),
            payment_status=(
                str(raw["payment_status"]) if raw.get("payment_status") is not None else None
            ),
            amount_str=str(raw.get("amount") or "0.00"),
            currency=str(raw.get("currency") or "USD"),
            reference=str(raw["reference"]) if raw.get("reference") else None,
            customer_email=cust_email,
            charge_id=charge_id,
            metadata=dict(raw.get("metadata") or {}),
        )

    def verify_and_parse_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> ProviderWebhookEvent:
        """
        Verify `X-Bachs-Signature-V2` on the unparsed `raw_body` using the official
        `bachs.webhooks.construct_event` helper.
        Raises `ValueError` on invalid or expired signature (to return HTTP 400).
        """
        try:
            event = webhooks.construct_event(raw_body, headers, self._webhook_secret)
        except BachsWebhookError as exc:
            raise ValueError(f"Invalid BACHS webhook signature: {exc}") from exc

        ev_dict = event.to_dict() if hasattr(event, "to_dict") else {}
        data = ev_dict.get("data") if isinstance(ev_dict.get("data"), dict) else {}
        if not data and hasattr(event, "data"):
            d_obj = event.data
            data = d_obj.to_dict() if hasattr(d_obj, "to_dict") else dict(d_obj)  # type: ignore[arg-type]

        checkout_id = str(data["checkout_id"]) if data.get("checkout_id") else None
        charge_id: str | None = None
        if data.get("charge_id"):
            charge_id = str(data["charge_id"])
        elif isinstance(data.get("charge"), dict) and data["charge"].get("id"):
            charge_id = str(data["charge"]["id"])

        cust_email: str | None = None
        if isinstance(data.get("customer_details"), dict) and data["customer_details"].get("email"):
            cust_email = str(data["customer_details"]["email"])
        elif isinstance(data.get("customer"), dict) and data["customer"].get("email"):
            cust_email = str(data["customer"]["email"])

        return ProviderWebhookEvent(
            event_id=str(event.id),
            event_type=str(event.type),
            created_at_iso=str(getattr(event, "created_at", "")),
            checkout_id=checkout_id,
            charge_id=charge_id,
            reference=str(data["reference"]) if data.get("reference") else None,
            amount_str=str(data["amount"]) if data.get("amount") is not None else None,
            currency=str(data["currency"]) if data.get("currency") else None,
            status=str(data["status"]) if data.get("status") else None,
            customer_email=cust_email,
            raw_data=dict(data),
        )

    def issue_refund(
        self,
        charge_id: str,
        reference: str,
        idempotency_key: str,
        amount: Decimal | None = None,
        reason: str = "Customer requested refund",
    ) -> ProviderRefundState:
        """
        Issue a full or partial refund via direct REST call to `POST /v1/refunds`
        (as refunds are not yet in the Python SDK).
        """
        payload: dict[str, str] = {
            "charge_id": charge_id,
            "reference": reference,
            "reason": reason,
        }
        if amount is not None:
            payload["amount"] = f"{amount:.2f}"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }
        client = self._http_client or httpx.Client(timeout=20.0)
        close_after = self._http_client is None
        try:
            resp = client.post(
                f"{self._rest_base_url}/v1/refunds",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
            return ProviderRefundState(
                refund_id=str(body["refund_id"]),
                charge_id=str(body["charge_id"]),
                reference=str(body["reference"]),
                status=str(body["status"]),
                requested_amount_str=str(body["requested_amount"]),
                refunded_amount_str=(
                    str(body["refunded_amount"])
                    if body.get("refunded_amount") is not None
                    else None
                ),
            )
        finally:
            if close_after:
                client.close()

    def retrieve_dispute(self, dispute_id: str) -> ProviderDisputeState:
        """Retrieve a dispute record via direct REST call to `GET /v1/disputes/{dispute_id}`."""
        headers = {"Authorization": f"Bearer {self._api_key}"}
        client = self._http_client or httpx.Client(timeout=20.0)
        close_after = self._http_client is None
        try:
            resp = client.get(
                f"{self._rest_base_url}/v1/disputes/{dispute_id}",
                headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
            return ProviderDisputeState(
                dispute_id=str(body.get("dispute_id") or body.get("id")),
                charge_id=str(body["charge_id"]),
                amount_str=str(body["amount"]),
                currency=str(body["currency"]),
                status=str(body["status"]),
                reason=body.get("reason"),
                response_deadline_at=body.get("response_deadline_at"),
                is_response_editable=bool(body.get("is_response_editable", True)),
            )
        finally:
            if close_after:
                client.close()

    @staticmethod
    def _is_private_or_local_url(url: str) -> bool:
        low = url.lower()
        return "localhost" in low or "127.0.0.1" in low or "0.0.0.0" in low
