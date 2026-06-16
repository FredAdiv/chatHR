"""LLM Gateway — shared types, errors, and provider protocol.

All external model calls must go through generate_with_gateway().
No module may call a provider directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    input_token_count: int | None
    output_token_count: int | None
    latency_ms: int = 0
    used_fallback: bool = False


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails (network, auth, rate-limit, etc.)."""


class PrivacyGuardBlockedError(Exception):
    """Raised when the privacy guard detects high-severity PII and blocks the call."""


@runtime_checkable
class LLMProvider(Protocol):
    provider_name: str

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str,
        purpose: str,
        stream: bool = False,
        metadata: dict | None = None,
    ) -> LLMResponse: ...
