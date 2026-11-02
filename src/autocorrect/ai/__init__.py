"""
Pro Edition Hybrid AI Package (Layer 2 Local AI & Layer 3 Cloud BYOK).
Provides:
- `api_key_manager.py`: OS Keyring credential storage & log redaction filter.
- `usage_tracker.py`: Local SQLite token and estimated cost accounting.
- `spending_controls.py`: Daily/monthly spend circuit breakers & Local-Only Lockdown.
- `provider_manager.py`: Explicit-consent BYOK adapters (OpenAI, Anthropic, Gemini, Custom).
- `local_model_manager.py`: Hardware-aware Layer 2 local grammar & rewrite assistant.
"""

from autocorrect.ai.api_key_manager import ApiKeyManager, SecretRedactingFilter
from autocorrect.ai.local_model_manager import (
    HardwareProfile,
    LocalModelManager,
    SentenceSuggestion,
)
from autocorrect.ai.provider_manager import (
    AIProviderId,
    AIRewriteRequest,
    AIRewriteResponse,
    BYOKProviderManager,
)
from autocorrect.ai.spending_controls import SpendingController, SpendLimitExceededError
from autocorrect.ai.usage_tracker import ProviderUsageSummary, UsageTracker

__all__ = [
    "AIProviderId",
    "AIRewriteRequest",
    "AIRewriteResponse",
    "ApiKeyManager",
    "BYOKProviderManager",
    "HardwareProfile",
    "LocalModelManager",
    "ProviderUsageSummary",
    "SecretRedactingFilter",
    "SentenceSuggestion",
    "SpendLimitExceededError",
    "SpendingController",
    "UsageTracker",
]
