"""
Layer 3 Cloud AI (BYOK) Provider Manager.
Supports OpenAI, Anthropic, Google Gemini, and OpenAI-Compatible Custom endpoints.
Strictly enforces:
1. Pro Edition entitlement check.
2. Explicit user consent (`user_consented=True`) before any network transmission.
3. Local-Only Mode lockdown and daily/monthly spending caps.
4. Direct HTTPS transmission to the user's chosen provider (never proxying keys through our servers).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable

import httpx

from autocorrect.ai.api_key_manager import ApiKeyManager, redact_secrets
from autocorrect.ai.spending_controls import SpendingController
from autocorrect.ai.usage_tracker import UsageTracker


class AIProviderId(str, Enum):
    """Supported BYOK Cloud AI providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    CUSTOM_OPENAI = "custom_openai"


@dataclass(frozen=True, slots=True)
class AIRewriteRequest:
    """Deliberate user-initiated writing refinement or grammar request."""

    text: str
    instruction: str = "Fix grammar and spelling while preserving tone and meaning."
    provider: AIProviderId = AIProviderId.OPENAI
    model: str = "gpt-4o-mini"
    user_consented: bool = False
    custom_base_url: str | None = None


@dataclass(frozen=True, slots=True)
class AIRewriteResponse:
    """Result of an explicit BYOK Cloud AI invocation."""

    original_text: str
    rewritten_text: str
    provider: AIProviderId
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Decimal


class BYOKProviderManager:
    """
    Manages BYOK provider configuration, consent enforcement, and direct REST calls.
    Never called during ordinary background autocorrection.
    """

    def __init__(
        self,
        key_manager: ApiKeyManager,
        usage_tracker: UsageTracker,
        spending_controller: SpendingController,
        http_transport: httpx.BaseTransport | None = None,
        is_pro_entitled_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._keys = key_manager
        self._usage = usage_tracker
        self._spending = spending_controller
        self._transport = http_transport
        self._is_pro_fn = is_pro_entitled_fn or (lambda: True)
        self._global_cloud_consent: bool = False

    @property
    def global_cloud_consent(self) -> bool:
        return self._global_cloud_consent

    def set_global_cloud_consent(self, consented: bool) -> None:
        self._global_cloud_consent = consented

    def get_transmission_disclosure(self, request: AIRewriteRequest) -> str:
        """Return clear user-facing disclosure before transmitting selected text."""
        return (
            f"The selected passage ({len(request.text)} characters) will be sent directly "
            f"to {request.provider.value.upper()} ({request.model}) using your personal API key."
        )

    def refine_sentence(self, request: AIRewriteRequest) -> AIRewriteResponse:
        """
        Execute an explicit sentence/passage refinement request via the user's BYOK provider.
        """
        if not self._is_pro_fn():
            raise PermissionError("Cloud AI requires an active Pro Edition licence.")

        if not (request.user_consented or self._global_cloud_consent):
            raise PermissionError(
                "Explicit user consent is required before transmitting text to a cloud AI provider."
            )

        # Check Local-Only Mode and spending circuit breaker
        self._spending.assert_request_permitted()

        api_key = self._keys.get_api_key(request.provider.value)
        if not api_key or not self._keys.validate_key_format(request.provider.value, api_key):
            raise PermissionError(
                f"Missing or invalid API key for provider '{request.provider.value}'."
            )

        try:
            with httpx.Client(transport=self._transport, timeout=15.0) as client:
                if request.provider in (AIProviderId.OPENAI, AIProviderId.CUSTOM_OPENAI):
                    rewritten, p_tok, c_tok = self._call_openai(client, api_key, request)
                elif request.provider == AIProviderId.ANTHROPIC:
                    rewritten, p_tok, c_tok = self._call_anthropic(client, api_key, request)
                elif request.provider == AIProviderId.GEMINI:
                    rewritten, p_tok, c_tok = self._call_gemini(client, api_key, request)
                else:
                    raise ValueError(f"Unsupported provider: {request.provider}")
        except Exception as exc:
            # Scrub any accidental key appearance before re-raising
            safe_msg = redact_secrets(str(exc))
            raise RuntimeError(f"AI provider request failed: {safe_msg}") from None

        cost = self._usage.record_usage(
            provider=request.provider.value,
            model=request.model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
        )
        return AIRewriteResponse(
            original_text=request.text,
            rewritten_text=rewritten,
            provider=request.provider,
            model=request.model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            estimated_cost_usd=cost,
        )

    @staticmethod
    def _call_openai(
        client: httpx.Client,
        api_key: str,
        req: AIRewriteRequest,
    ) -> tuple[str, int, int]:
        base = (req.custom_base_url or "https://api.openai.com/v1").rstrip("/")
        resp = client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": req.model,
                "messages": [
                    {"role": "system", "content": req.instruction},
                    {"role": "user", "content": req.text},
                ],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = str(data["choices"][0]["message"]["content"]).strip()
        usage = data.get("usage", {})
        return (
            content,
            int(usage.get("prompt_tokens", max(1, len(req.text) // 4))),
            int(usage.get("completion_tokens", max(1, len(content) // 4))),
        )

    @staticmethod
    def _call_anthropic(
        client: httpx.Client,
        api_key: str,
        req: AIRewriteRequest,
    ) -> tuple[str, int, int]:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": req.model,
                "max_tokens": 512,
                "system": req.instruction,
                "messages": [{"role": "user", "content": req.text}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = str(data["content"][0]["text"]).strip()
        usage = data.get("usage", {})
        return (
            content,
            int(usage.get("input_tokens", max(1, len(req.text) // 4))),
            int(usage.get("output_tokens", max(1, len(content) // 4))),
        )

    @staticmethod
    def _call_gemini(
        client: httpx.Client,
        api_key: str,
        req: AIRewriteRequest,
    ) -> tuple[str, int, int]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{req.model}:generateContent"
        resp = client.post(
            url,
            headers={"x-goog-api-key": api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": f"{req.instruction}\n\nText:\n{req.text}"}
                        ]
                    }
                ]
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = str(
            data["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
        meta = data.get("usageMetadata", {})
        return (
            content,
            int(meta.get("promptTokenCount", max(1, len(req.text) // 4))),
            int(meta.get("candidatesTokenCount", max(1, len(content) // 4))),
        )
