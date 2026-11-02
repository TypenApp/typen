"""
BYOK Spending Controls and Local-Only Lockdown Circuit Breaker.
Enforces user-defined daily and monthly USD spending limits before any
external AI provider call is permitted.
"""

from __future__ import annotations

import time
from decimal import Decimal

from autocorrect.ai.usage_tracker import UsageTracker


class SpendLimitExceededError(PermissionError):
    """Raised when a BYOK request would exceed the user's configured spending limit."""


class LocalOnlyLockdownError(PermissionError):
    """Raised when a cloud AI request is attempted while Local-Only Mode is active."""


class SpendingController:
    """
    Enforces hard daily/monthly cost limits and the Local-Only Mode switch.
    """

    def __init__(
        self,
        usage_tracker: UsageTracker,
        daily_limit_usd: Decimal | None = Decimal("2.00"),
        monthly_limit_usd: Decimal | None = Decimal("15.00"),
        local_only_mode: bool = False,
    ) -> None:
        self._tracker = usage_tracker
        self._daily_limit = daily_limit_usd
        self._monthly_limit = monthly_limit_usd
        self._local_only_mode = local_only_mode

    @property
    def local_only_mode(self) -> bool:
        return self._local_only_mode

    def set_local_only_mode(self, enabled: bool) -> None:
        self._local_only_mode = enabled

    def set_limits(
        self,
        daily_limit_usd: Decimal | None,
        monthly_limit_usd: Decimal | None,
    ) -> None:
        self._daily_limit = daily_limit_usd
        self._monthly_limit = monthly_limit_usd

    def assert_request_permitted(self, now_utc: float | None = None) -> None:
        """
        Check Local-Only Lockdown and daily/monthly spend caps before sending a request.
        Raises `LocalOnlyLockdownError` or `SpendLimitExceededError` if blocked.
        """
        if self._local_only_mode:
            raise LocalOnlyLockdownError(
                "Cloud AI is blocked because Local-Only Mode is enabled."
            )

        now = now_utc if now_utc is not None else time.time()

        if self._daily_limit is not None:
            day_summary = self._tracker.get_summary_since(now - 86400.0)
            if day_summary.estimated_cost_usd >= self._daily_limit:
                raise SpendLimitExceededError(
                    f"Daily BYOK spending limit (${self._daily_limit}) reached "
                    f"(spent ${day_summary.estimated_cost_usd})."
                )

        if self._monthly_limit is not None:
            month_summary = self._tracker.get_summary_since(now - 30 * 86400.0)
            if month_summary.estimated_cost_usd >= self._monthly_limit:
                raise SpendLimitExceededError(
                    f"Monthly BYOK spending limit (${self._monthly_limit}) reached "
                    f"(spent ${month_summary.estimated_cost_usd})."
                )
