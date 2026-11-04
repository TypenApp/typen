"""
Entitlements in a free product.

Typen is free and open source and funded by donations. There is one edition,
nothing expires, nothing is locked. This module is kept because the daemon,
the Settings controller and `InputSessionManager` all ask one object whether a
feature is allowed; keeping that single seam means the answer ("yes") lives in
exactly one place and a fork that *does* want gating has one class to replace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

GITHUB_ORG = "TypenApp"
GITHUB_REPO = "TypenApp/typen"
GITHUB_REPO_URL = "https://github.com/TypenApp/typen"
SPONSORS_HANDLE = "TypenApp"
GITHUB_SPONSORS_URL = f"https://github.com/sponsors/{SPONSORS_HANDLE}"
DONATE_URL = GITHUB_SPONSORS_URL
STATUS_MESSAGE = "Typen is free and open source — every feature, on every machine, for as long as you like."


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    """What the app may do right now. In Typen this is constant."""

    mode: str = "OPEN_SOURCE"
    typing_assistance_enabled: bool = True
    pro_features_enabled: bool = True
    can_download_new_updates: bool = True
    updates_expire_at: datetime | None = None
    status_message: str = STATUS_MESSAGE


FULL_ENTITLEMENT = EntitlementSnapshot()


class EntitlementManager:
    """
    Implements `EntitlementCheckPort` (see `autocorrect.input.session_state`) and the
    `evaluate()` surface the IPC server and Settings read. Every answer is "allowed".
    """

    def evaluate(self, now_utc: datetime | None = None) -> EntitlementSnapshot:
        return FULL_ENTITLEMENT

    def is_typing_assistance_enabled(self) -> bool:
        return True

    def is_pro_enabled(self) -> bool:
        return True
