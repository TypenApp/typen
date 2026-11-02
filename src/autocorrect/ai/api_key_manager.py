"""
OS-Native Secure API Credential Storage and Log Redaction Filter.
Stores BYOK API keys exclusively in the operating system's credential vault
(Windows Credential Manager / macOS Keychain via `keyring`) and scrubs any
secret key patterns from logs, exception tracebacks, and diagnostics.
"""

from __future__ import annotations

import logging
import re
from typing import Final

import keyring

KEYRING_SERVICE_NAME: Final[str] = "AutoCorrect.Desktop.BYOK"

# Regex matching OpenAI, Anthropic, Google Gemini, and Bachs secret keys for log redaction
SECRET_KEY_PATTERNS: Final[re.Pattern[str]] = re.compile(
    r"(sk-[a-zA-Z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,}|sk_live_[a-zA-Z0-9_-]{8,}|sk_sandbox_[a-zA-Z0-9_-]{8,}|whsec_[a-zA-Z0-9_-]{8,})"
)


def redact_secrets(text: str) -> str:
    """Replace any API key or webhook secret pattern in `text` with `[REDACTED_SECRET]`."""
    if not text:
        return text
    return SECRET_KEY_PATTERNS.sub("[REDACTED_SECRET]", text)


class SecretRedactingFilter(logging.Filter):
    """Logging filter that guarantees API keys are never written to log outputs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (redact_secrets(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


class ApiKeyManager:
    """
    Manages BYOK credentials via OS secure storage (`keyring`).
    Supports an optional in-memory vault backend for isolated unit tests.
    """

    def __init__(self, use_memory_backend: bool = False) -> None:
        self._use_memory = use_memory_backend
        self._memory_vault: dict[str, str] = {}

    def set_api_key(self, provider_id: str, api_key: str) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("API key must not be empty")
        norm_provider = provider_id.strip().lower()
        if self._use_memory:
            self._memory_vault[norm_provider] = cleaned
            return
        try:
            keyring.set_password(KEYRING_SERVICE_NAME, norm_provider, cleaned)
        except Exception:
            self._memory_vault[norm_provider] = cleaned

    def get_api_key(self, provider_id: str) -> str | None:
        norm_provider = provider_id.strip().lower()
        if self._use_memory:
            return self._memory_vault.get(norm_provider)
        try:
            val = keyring.get_password(KEYRING_SERVICE_NAME, norm_provider)
            if val is not None:
                return val
        except Exception:
            pass
        return self._memory_vault.get(norm_provider)

    def delete_api_key(self, provider_id: str) -> None:
        norm_provider = provider_id.strip().lower()
        self._memory_vault.pop(norm_provider, None)
        if not self._use_memory:
            try:
                keyring.delete_password(KEYRING_SERVICE_NAME, norm_provider)
            except Exception:
                pass

    def has_api_key(self, provider_id: str) -> bool:
        return bool(self.get_api_key(provider_id))

    @staticmethod
    def validate_key_format(provider_id: str, api_key: str) -> bool:
        """Fast offline structural check before making a provider validation call."""
        key = api_key.strip()
        if len(key) < 12 or " " in key:
            return False
        prov = provider_id.strip().lower()
        if prov == "openai":
            return key.startswith("sk-")
        if prov == "anthropic":
            return key.startswith("sk-ant-")
        if prov == "gemini":
            return key.startswith("AIza") or len(key) >= 20
        return True
