"""
Version and build metadata constants used for independent resource compatibility
and perpetual usage vs. 12-month update entitlement verification.
"""

from datetime import UTC, datetime

APP_VERSION: str = "1.3.0"
BINARY_SCHEMA_VERSION: int = 1

# Baked in at build time; used offline by update_entitlement.py to verify that
# this binary was released within the customer's entitled update window.
APP_RELEASE_TIMESTAMP: str = "2026-11-06T00:00:00Z"


def get_app_release_datetime() -> datetime:
    """Return the parsed UTC release timestamp of this application binary."""
    return datetime.fromisoformat(APP_RELEASE_TIMESTAMP.replace("Z", "+00:00")).astimezone(UTC)
