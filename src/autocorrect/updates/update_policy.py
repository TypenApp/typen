"""
Update Policy Engine.
Enforces:
1. Binary schema compatibility (`schema_version == BINARY_SCHEMA_VERSION`).
2. Optional update window (`release.published_at <= updates_expire_at`); Typen ships with no window (None).
3. Critical security-patch override (`is_security_patch == True` for the user's entitled branch).
4. Protection of perpetual installations (blocks downloading non-entitled updates so an
   expired update window never disables an existing perpetual installation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from autocorrect.version import APP_VERSION, BINARY_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class UpdateEligibilityResult:
    """Decision on whether a remote release may be downloaded and installed."""

    eligible: bool
    reason: str
    requires_upgrade_purchase: bool = False


class UpdatePolicyEngine:
    """Evaluates whether an application, language resource, or model update is eligible."""

    @staticmethod
    def check_resource_update_eligibility(
        current_version: str,
        remote_version: str,
        remote_schema_version: int,
        remote_released_at_iso: str,
        updates_expire_at: datetime | None,
    ) -> UpdateEligibilityResult:
        if remote_schema_version != BINARY_SCHEMA_VERSION:
            return UpdateEligibilityResult(
                eligible=False,
                reason=f"Incompatible schema_version {remote_schema_version} != {BINARY_SCHEMA_VERSION}",
                requires_upgrade_purchase=False,
            )

        if not UpdatePolicyEngine._is_newer_semver(current_version, remote_version):
            return UpdateEligibilityResult(
                eligible=False,
                reason="Already on equal or newer resource version",
                requires_upgrade_purchase=False,
            )

        released_dt = datetime.fromisoformat(remote_released_at_iso.replace("Z", "+00:00")).astimezone(UTC)

        if updates_expire_at is not None and released_dt > updates_expire_at:
            return UpdateEligibilityResult(
                eligible=False,
                reason=(
                    f"Resource v{remote_version} released on {released_dt.date().isoformat()} "
                    f"is outside the 12-month update entitlement window "
                    f"(expired {updates_expire_at.date().isoformat()})."
                ),
                requires_upgrade_purchase=True,
            )

        return UpdateEligibilityResult(eligible=True, reason="ELIGIBLE")

    @staticmethod
    def check_app_update_eligibility(
        remote_version: str,
        remote_released_at_iso: str,
        is_security_patch: bool,
        target_branch_prefix: str,
        updates_expire_at: datetime | None,
        current_app_version: str = APP_VERSION,
    ) -> UpdateEligibilityResult:
        if not UpdatePolicyEngine._is_newer_semver(current_app_version, remote_version):
            return UpdateEligibilityResult(
                eligible=False,
                reason="Already on equal or newer application version",
            )

        # Critical security fixes for the customer's entitled release branch are always allowed
        if is_security_patch and current_app_version.startswith(target_branch_prefix):
            return UpdateEligibilityResult(
                eligible=True,
                reason="ELIGIBLE_SECURITY_PATCH",
            )

        released_dt = datetime.fromisoformat(remote_released_at_iso.replace("Z", "+00:00")).astimezone(UTC)

        if updates_expire_at is not None and released_dt > updates_expire_at:
            return UpdateEligibilityResult(
                eligible=False,
                reason=(
                    f"Application v{remote_version} requires an active update entitlement "
                    f"(entitlement expired on {updates_expire_at.date().isoformat()})."
                ),
                requires_upgrade_purchase=True,
            )

        return UpdateEligibilityResult(eligible=True, reason="ELIGIBLE")

    @staticmethod
    def _is_newer_semver(current: str, candidate: str) -> bool:
        """
        Semver-ish compare: 1.3.0 > 1.3.0-beta.3 > 1.3.0-beta.2.
        A release without a pre-release tag is newer than the same numbers with one.
        """
        return UpdatePolicyEngine._semver_key(candidate) > UpdatePolicyEngine._semver_key(current)

    @staticmethod
    def _semver_key(v: str) -> tuple[object, ...]:
        raw = v.strip().lstrip("v")
        core, _, pre = raw.partition("-")
        nums = tuple(int(p) for p in core.split(".") if p.isdigit())
        if not pre:
            # Final releases sort after any pre-release of the same core.
            return (*nums, 1, ())
        pre_parts: list[object] = []
        for part in pre.replace(".", "-").split("-"):
            if part.isdigit():
                pre_parts.append(int(part))
            elif part:
                pre_parts.append(part)
        return (*nums, 0, tuple(pre_parts))
