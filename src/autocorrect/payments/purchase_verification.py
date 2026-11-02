"""
Purchase Verification, Webhook Deduplication, Reconciliation, and Entitlement Issuance Service.
Implements the strict security rules from the Master Plan:
1. Never issue a licence solely because a user visits `success_url`.
2. Verify `X-Bachs-Signature-V2` on the raw request body before parsing JSON.
3. Deduplicate webhook deliveries by `event.id` (`evt_...`).
4. Independently retrieve the checkout session from the payment provider and match
   `status == 'completed'`, `payment_status == 'paid'`, `reference == order.id`,
   `currency`, and `amount` in integer minor units (cents/kobo, never floats).
5. Handle `checkout.completed` and `collection.succeeded` idempotently (whichever arrives first).
6. Reject unreferenced virtual-account deposits (`checkout_id is None`) from auto-fulfilling orders.
7. Handle `refund.paid`, `dispute.created`, and `dispute.updated` to revoke or suspend seats.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from pathlib import Path
from typing import Mapping

from autocorrect.licensing.activation_manager import ActivationManager, DeviceSeatRecord
from autocorrect.licensing.signed_licence import ProductSKU, SignedLicenceCertificate
from autocorrect.licensing.upgrade_manager import UpgradeType
from autocorrect.payments.provider_port import PaymentProviderPort, ProviderWebhookEvent


class OrderStatus(str, Enum):
    """Lifecycle states of a purchase or upgrade order."""

    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"


@dataclass(slots=True)
class OrderRecord:
    """Authoritative server-side order record."""

    order_id: str  # Passed as BACHS `reference`
    idempotency_key: str
    sku: ProductSKU
    upgrade_type: UpgradeType
    parent_licence_id: str | None
    device_id_hash: str
    expected_amount: Decimal
    expected_currency: str
    status: OrderStatus
    provider_checkout_id: str | None = None
    provider_charge_id: str | None = None
    issued_licence_id: str | None = None
    customer_email: str | None = None
    created_at_iso: str = ""


def to_minor_units(amount: Decimal | str) -> int:
    """Convert a decimal string or Decimal into exact integer minor units (e.g. cents)."""
    dec = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(dec * 100)


class PurchaseVerificationService:
    """
    Transactional order store, webhook processor, and idempotent licence issuer.
    """

    def __init__(
        self,
        db_path: Path,
        provider: PaymentProviderPort,
        activation_manager: ActivationManager,
    ) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._provider = provider
        self._activation_mgr = activation_manager
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    sku TEXT NOT NULL,
                    upgrade_type TEXT NOT NULL,
                    parent_licence_id TEXT,
                    device_id_hash TEXT NOT NULL,
                    expected_amount TEXT NOT NULL,
                    expected_currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_checkout_id TEXT,
                    provider_charge_id TEXT,
                    issued_licence_id TEXT,
                    customer_email TEXT,
                    created_at_iso TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    processed_at_iso TEXT NOT NULL
                );
                """
            )

    def create_pending_order(
        self,
        sku: ProductSKU,
        upgrade_type: UpgradeType,
        expected_amount: Decimal,
        expected_currency: str,
        device_id_hash: str,
        parent_licence_id: str | None = None,
        customer_email: str | None = None,
        now_utc: datetime | None = None,
    ) -> OrderRecord:
        now_iso = (
            (now_utc or datetime.now(timezone.utc))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        order_id = f"ord_{uuid.uuid4().hex[:20]}"
        idem_key = f"checkout-{order_id}"
        order = OrderRecord(
            order_id=order_id,
            idempotency_key=idem_key,
            sku=sku,
            upgrade_type=upgrade_type,
            parent_licence_id=parent_licence_id,
            device_id_hash=device_id_hash,
            expected_amount=expected_amount.quantize(Decimal("0.01")),
            expected_currency=expected_currency.upper(),
            status=OrderStatus.PENDING,
            customer_email=customer_email,
            created_at_iso=now_iso,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, idempotency_key, sku, upgrade_type, parent_licence_id,
                    device_id_hash, expected_amount, expected_currency, status,
                    provider_checkout_id, provider_charge_id, issued_licence_id,
                    customer_email, created_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.idempotency_key,
                    order.sku.value,
                    order.upgrade_type.value,
                    order.parent_licence_id,
                    order.device_id_hash,
                    f"{order.expected_amount:.2f}",
                    order.expected_currency,
                    order.status.value,
                    None,
                    None,
                    None,
                    order.customer_email,
                    order.created_at_iso,
                ),
            )
        return order

    def attach_provider_checkout_id(self, order_id: str, provider_checkout_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET provider_checkout_id = ? WHERE order_id = ?",
                (provider_checkout_id, order_id),
            )

    def get_order(self, order_id: str) -> OrderRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        return self._row_to_order(row) if row else None

    def find_order_by_reference_or_checkout(
        self, reference: str | None, checkout_id: str | None
    ) -> OrderRecord | None:
        with self._connect() as conn:
            if reference:
                row = conn.execute(
                    "SELECT * FROM orders WHERE order_id = ?", (reference,)
                ).fetchone()
                if row:
                    return self._row_to_order(row)
            if checkout_id:
                row = conn.execute(
                    "SELECT * FROM orders WHERE provider_checkout_id = ?",
                    (checkout_id,),
                ).fetchone()
                if row:
                    return self._row_to_order(row)
        return None

    def find_order_by_charge_id(self, charge_id: str) -> OrderRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE provider_charge_id = ?", (charge_id,)
            ).fetchone()
        return self._row_to_order(row) if row else None

    @staticmethod
    def _row_to_order(row: tuple[object, ...]) -> OrderRecord:
        return OrderRecord(
            order_id=str(row[0]),
            idempotency_key=str(row[1]),
            sku=ProductSKU(str(row[2])),
            upgrade_type=UpgradeType(str(row[3])),
            parent_licence_id=str(row[4]) if row[4] is not None else None,
            device_id_hash=str(row[5]),
            expected_amount=Decimal(str(row[6])),
            expected_currency=str(row[7]),
            status=OrderStatus(str(row[8])),
            provider_checkout_id=str(row[9]) if row[9] is not None else None,
            provider_charge_id=str(row[10]) if row[10] is not None else None,
            issued_licence_id=str(row[11]) if row[11] is not None else None,
            customer_email=str(row[12]) if row[12] is not None else None,
            created_at_iso=str(row[13]),
        )

    def is_webhook_already_processed(self, event_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return row is not None

    def handle_raw_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        now_utc: datetime | None = None,
    ) -> tuple[int, str]:
        """
        Process an incoming webhook delivery from BACHS.
        Returns `(http_status_code, message)`:
        - `400`: Invalid signature (never retried by BACHS).
        - `503`: Checkout not yet completed (BACHS will retry).
        - `200`: Processed or safely ignored/deduplicated.
        """
        try:
            event: ProviderWebhookEvent = self._provider.verify_and_parse_webhook(
                raw_body, headers
            )
        except ValueError as exc:
            return 400, str(exc)

        if self.is_webhook_already_processed(event.event_id):
            return 200, "DUPLICATE_EVENT_IGNORED"

        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")

        if event.event_type in ("checkout.completed", "collection.succeeded"):
            # Guard: unreferenced virtual-account deposits have checkout_id=None and reference=None;
            # they must never automatically fulfil a software checkout order.
            if not event.checkout_id and not event.reference:
                self._record_event_processed(event.event_id, event.event_type, now_iso)
                return 200, "UNREFERENCED_DEPOSIT_IGNORED"

            order = self.find_order_by_reference_or_checkout(
                event.reference, event.checkout_id
            )
            if order is None:
                self._record_event_processed(event.event_id, event.event_type, now_iso)
                return 200, "UNKNOWN_ORDER_IGNORED"

            if order.status == OrderStatus.FULFILLED:
                self._record_event_processed(event.event_id, event.event_type, now_iso)
                return 200, "ALREADY_FULFILLED"

            chk_id = event.checkout_id or order.provider_checkout_id
            if not chk_id:
                return 503, "Missing checkout_id"

            # Independently retrieve checkout state from BACHS API
            checkout = self._provider.retrieve_checkout_session(chk_id)
            if checkout.status != "completed":
                # Return 503 so BACHS retries once checkout transitions to completed
                return 503, "Checkout not completed yet"

            if checkout.payment_status not in ("paid", "succeeded"):
                self._update_order_status(
                    order.order_id, OrderStatus.HELD_FOR_REVIEW, event.event_id, event.event_type, now_iso
                )
                return 200, "HELD_UNPAID_STATUS"

            # Strict amount, currency, and reference verification in minor units
            if (
                checkout.currency.upper() != order.expected_currency.upper()
                or to_minor_units(checkout.amount_str) != to_minor_units(order.expected_amount)
                or (checkout.reference and checkout.reference != order.order_id)
            ):
                self._update_order_status(
                    order.order_id, OrderStatus.HELD_FOR_REVIEW, event.event_id, event.event_type, now_iso
                )
                return 200, "HELD_AMOUNT_OR_CURRENCY_MISMATCH"

            # Fulfil order and issue licence seat atomically
            charge_id = event.charge_id or checkout.charge_id
            buyer_email = checkout.customer_email or event.customer_email or order.customer_email or "customer@example.com"
            self._fulfil_verified_order(
                order=order,
                charge_id=charge_id,
                customer_email=buyer_email,
                event_id=event.event_id,
                event_type=event.event_type,
                now=now,
            )
            return 200, "FULFILLED"

        if event.event_type == "checkout.expired":
            order = self.find_order_by_reference_or_checkout(
                event.reference, event.checkout_id
            )
            if order and order.status == OrderStatus.PENDING:
                # Note: per BACHS docs, a late bank transfer can still complete after checkout.expired,
                # so marking EXPIRED does not delete the order.
                self._update_order_status(
                    order.order_id, OrderStatus.EXPIRED, event.event_id, event.event_type, now_iso
                )
                return 200, "MARKED_EXPIRED"

        if event.event_type == "refund.paid" and event.charge_id:
            order = self.find_order_by_charge_id(event.charge_id)
            if order and order.issued_licence_id:
                seat = self._activation_mgr.get_seat(order.issued_licence_id)
                if seat:
                    seat.revoked = True
                self._update_order_status(
                    order.order_id, OrderStatus.REFUNDED, event.event_id, event.event_type, now_iso
                )
                return 200, "LICENCE_REVOKED_ON_REFUND"

        if event.event_type in ("dispute.created", "dispute.updated") and event.charge_id:
            order = self.find_order_by_charge_id(event.charge_id)
            if order and order.issued_licence_id:
                seat = self._activation_mgr.get_seat(order.issued_licence_id)
                if seat:
                    if event.status in ("needs_response", "under_review", "lost"):
                        seat.revoked = True
                    elif event.status in ("won", "closed", "prevented"):
                        seat.revoked = False
                new_status = (
                    OrderStatus.FULFILLED
                    if event.status in ("won", "closed", "prevented")
                    else OrderStatus.DISPUTED
                )
                self._update_order_status(
                    order.order_id, new_status, event.event_id, event.event_type, now_iso
                )
                return 200, f"DISPUTE_HANDLED_{event.status}"

        self._record_event_processed(event.event_id, event.event_type, now_iso)
        return 200, "EVENT_ACKNOWLEDGED"

    def _fulfil_verified_order(
        self,
        order: OrderRecord,
        charge_id: str | None,
        customer_email: str,
        event_id: str,
        event_type: str,
        now: datetime,
    ) -> str:
        now_iso = now.isoformat().replace("+00:00", "Z")

        # If this is a 30% renewal or Standard-to-Pro cross-grade of an existing licence,
        # extend/upgrade the existing licence seat record; otherwise issue a fresh licence_id.
        if order.parent_licence_id:
            existing_seat = self._activation_mgr.get_seat(order.parent_licence_id)
        else:
            existing_seat = None

        if existing_seat is not None:
            lic_id = existing_seat.licence_id
            current_exp = datetime.fromisoformat(
                existing_seat.updates_expire_at_iso.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            base_dt = max(now, current_exp)
            new_exp_iso = (
                (base_dt + timedelta(days=365)).isoformat().replace("+00:00", "Z")
            )
            existing_seat.sku = order.sku
            existing_seat.order_id = order.order_id
            existing_seat.updates_expire_at_iso = new_exp_iso
        else:
            lic_id = f"lic_{uuid.uuid4().hex[:20]}"
            new_exp_iso = (
                (now + timedelta(days=365)).isoformat().replace("+00:00", "Z")
            )
            seat = DeviceSeatRecord(
                licence_id=lic_id,
                order_id=order.order_id,
                customer_email=customer_email,
                sku=order.sku,
                issued_at_iso=now_iso,
                updates_expire_at_iso=new_exp_iso,
                active_device_id_hash=None,
            )
            self._activation_mgr.register_licence_seat(seat)

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = ?, provider_charge_id = ?, issued_licence_id = ?, customer_email = ?
                WHERE order_id = ?
                """,
                (
                    OrderStatus.FULFILLED.value,
                    charge_id,
                    lic_id,
                    customer_email,
                    order.order_id,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_webhook_events (event_id, event_type, processed_at_iso)
                VALUES (?, ?, ?)
                """,
                (event_id, event_type, now_iso),
            )
        return lic_id

    def _update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
        event_id: str,
        event_type: str,
        now_iso: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET status = ? WHERE order_id = ?",
                (status.value, order_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_webhook_events (event_id, event_type, processed_at_iso)
                VALUES (?, ?, ?)
                """,
                (event_id, event_type, now_iso),
            )

    def _record_event_processed(
        self, event_id: str, event_type: str, now_iso: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_webhook_events (event_id, event_type, processed_at_iso)
                VALUES (?, ?, ?)
                """,
                (event_id, event_type, now_iso),
            )

    def reconcile_pending_order(
        self,
        order_id: str,
        now_utc: datetime | None = None,
    ) -> OrderRecord | None:
        """
        Reconcile a pending order by querying the payment provider directly
        (used when a webhook delivery was delayed or when recovering an uncertain write).
        """
        order = self.get_order(order_id)
        if order is None or order.status == OrderStatus.FULFILLED:
            return order
        if not order.provider_checkout_id:
            return order

        checkout = self._provider.retrieve_checkout_session(order.provider_checkout_id)
        if (
            checkout.status == "completed"
            and checkout.payment_status in ("paid", "succeeded")
            and checkout.currency.upper() == order.expected_currency.upper()
            and to_minor_units(checkout.amount_str) == to_minor_units(order.expected_amount)
        ):
            now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
            self._fulfil_verified_order(
                order=order,
                charge_id=checkout.charge_id,
                customer_email=checkout.customer_email or order.customer_email or "customer@example.com",
                event_id=f"reconcile_{order.order_id}",
                event_type="reconciliation.completed",
                now=now,
            )
        return self.get_order(order_id)

    def activate_fulfilled_order(
        self,
        order_id: str,
        device_id_hash: str,
        now_utc: datetime | None = None,
    ) -> SignedLicenceCertificate:
        """
        Retrieve and sign the device-bound `SignedLicenceCertificate` for a fulfilled order.
        Never issues a certificate unless `order.status == OrderStatus.FULFILLED`.
        """
        order = self.get_order(order_id)
        if order is None:
            raise KeyError(f"Order not found: {order_id}")
        if order.status != OrderStatus.FULFILLED or not order.issued_licence_id:
            raise PermissionError(
                f"Order {order_id} is not paid/fulfilled (current status: {order.status.value}). "
                "Visiting the checkout success URL without a verified payment never unlocks a licence."
            )
        return self._activation_mgr.activate_device(
            licence_id=order.issued_licence_id,
            device_id_hash=device_id_hash,
            client_platform=order.sku.platform,
            now_utc=now_utc,
        )
