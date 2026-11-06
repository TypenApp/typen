"""
Independent Update Distribution and Cryptographic Verification Package.
Manages independent updates for:
1. Desktop application executable (`application_updater.py`)
2. Global language intelligence resources (`language_resource_updater.py`)
3. Optional local AI models (`model_updater.py`)
Governed by `update_policy.py` to enforce Ed25519 signatures, schema compatibility,
and an optional update window (unused in Typen, which has no expiry) without ever breaking offline usage.
"""

from autocorrect.updates.application_updater import (
    APP_RELEASES_REPO,
    DEFAULT_APP_RELEASES_URL,
    ApplicationReleaseDescriptor,
    ApplicationUpdater,
)
from autocorrect.updates.language_resource_updater import (
    DEFAULT_LANGUAGE_DATA_RELEASES_URL,
    LANGUAGE_DATA_REPO,
    LanguageResourceUpdater,
    ResourceUpdateDescriptor,
)
from autocorrect.updates.model_updater import (
    DEFAULT_MODEL_RESOURCES_RELEASES_URL,
    MODEL_RESOURCES_REPO,
    LocalModelDescriptor,
    ModelUpdater,
)
from autocorrect.updates.update_policy import UpdateEligibilityResult, UpdatePolicyEngine

__all__ = [
    "APP_RELEASES_REPO",
    "ApplicationReleaseDescriptor",
    "ApplicationUpdater",
    "DEFAULT_APP_RELEASES_URL",
    "DEFAULT_LANGUAGE_DATA_RELEASES_URL",
    "DEFAULT_MODEL_RESOURCES_RELEASES_URL",
    "LANGUAGE_DATA_REPO",
    "LanguageResourceUpdater",
    "LocalModelDescriptor",
    "MODEL_RESOURCES_REPO",
    "ModelUpdater",
    "ResourceUpdateDescriptor",
    "UpdateEligibilityResult",
    "UpdatePolicyEngine",
]
