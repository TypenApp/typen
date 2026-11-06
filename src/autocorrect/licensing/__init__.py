"""
Entitlements and update signing.

Typen has no paid editions, trials or licence certificates: `EntitlementManager`
always answers "allowed". `root_key` holds the Ed25519 *public* key used to verify
signed language-resource, model and application updates.
"""

from autocorrect.licensing.entitlement_manager import (
    DONATE_URL,
    FULL_ENTITLEMENT,
    GITHUB_ORG,
    GITHUB_REPO,
    GITHUB_REPO_URL,
    GITHUB_SPONSORS_URL,
    SPONSORS_HANDLE,
    EntitlementManager,
    EntitlementSnapshot,
)

__all__ = [
    "DONATE_URL",
    "FULL_ENTITLEMENT",
    "GITHUB_ORG",
    "GITHUB_REPO",
    "GITHUB_REPO_URL",
    "GITHUB_SPONSORS_URL",
    "SPONSORS_HANDLE",
    "EntitlementManager",
    "EntitlementSnapshot",
]
