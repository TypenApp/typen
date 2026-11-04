"""
Independent Update Distribution and Cryptographic Verification Package.
Manages independent updates for:
1. Desktop application executable (`application_updater.py`)
2. Global language intelligence resources (`language_resource_updater.py`)
3. Optional local AI models (`model_updater.py`)
Governed by `update_policy.py` to enforce Ed25519 signatures, schema compatibility,
and an optional update window (unused in Tact, which has no expiry) without ever breaking offline usage.
"""

from autocorrect.updates.application_updater import ApplicationReleaseDescriptor, ApplicationUpdater
from autocorrect.updates.language_resource_updater import (
    LanguageResourceUpdater,
    ResourceUpdateDescriptor,
)
from autocorrect.updates.model_updater import LocalModelDescriptor, ModelUpdater
from autocorrect.updates.update_policy import UpdateEligibilityResult, UpdatePolicyEngine

__all__ = [
    "ApplicationReleaseDescriptor",
    "ApplicationUpdater",
    "LanguageResourceUpdater",
    "LocalModelDescriptor",
    "ModelUpdater",
    "ResourceUpdateDescriptor",
    "UpdateEligibilityResult",
    "UpdatePolicyEngine",
]
