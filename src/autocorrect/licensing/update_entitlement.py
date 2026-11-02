"""
Perpetual Usage & 12-Month Update Entitlement Evaluator.
Guarantees:
1. Customers retain indefinite perpetual rights to use their purchased and entitled
   application version even after their 12-month update entitlement expires.
2. Downloaded language resources and local user preferences remain 100% accessible
   after update entitlement expiry.
3. Application releases published after `updates_expire_at` require a voluntary
   upgrade renewal (unless marked as a critical security patch for the user's branch).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from autocorrect.licensing.signed_licence import SignedLicenceCertificate
from autocorrect.version import get_app_release_datetime


@dataclass(frozen=True, slots=True)
class UpdateEntitlementState:
    """Evaluated state of the licence's perpetual usage and 12-month update window."""

    can_use_current_app_perpetually: bool
    is_within_update_window: bool
    updates_expire_at: datetime
    days_of_updates_remaining: float
    status_label: str  # 'ACTIVE_UPDATES' | 'PERPETUAL_FROZEN' | 'UNENTITLED_APP_BINARY'


class UpdateEntitlementEvaluator:
    """Evaluates perpetual usage rights vs. time-limited update eligibility."""

    @staticmethod
    def evaluate(
        cert: SignedLicenceCertificate,
        now_utc: datetime | None = None,
        app_release_dt: datetime | None = None,
        is_security_patch_build: bool = False,
    ) -> UpdateEntitlementState:
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        binary_dt = (app_release_dt or get_app_release_datetime()).astimezone(timezone.utc)
        expire_dt = cert.get_updates_expire_datetime()
        max_app_dt = cert.get_entitled_max_release_datetime()

        # Perpetual usage check: was this application binary released on or before
        # the customer's entitled update window (or is it a security patch)?
        can_use_binary = bool(
            cert.perpetual_usage
            and (binary_dt <= max_app_dt or is_security_patch_build)
        )

        rem_seconds = (expire_dt - now).total_seconds()
        within_window = rem_seconds >= 0

        if not can_use_binary:
            label = "UNENTITLED_APP_BINARY"
        elif within_window:
            label = "ACTIVE_UPDATES"
        else:
            # Update window expired, but current app and cached resources work forever!
            label = "PERPETUAL_FROZEN"

        return UpdateEntitlementState(
            can_use_current_app_perpetually=can_use_binary,
            is_within_update_window=within_window,
            updates_expire_at=expire_dt,
            days_of_updates_remaining=max(0.0, round(rem_seconds / 86400.0, 2)),
            status_label=label,
        )
