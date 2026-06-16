"""Fake deterministic LLM provider for tests and local development.

No network calls. Deterministic response based on message count and purpose.
Supports simulating failures to test gateway fallback behavior.
"""
from __future__ import annotations

from app.services.llm_gateway.protocol import LLMMessage, LLMProviderError, LLMResponse


class FakeLocalLLMProvider:
    """Deterministic local LLM provider. No external calls. Safe for tests."""

    provider_name = "fake-local"

    def __init__(self, *, fail_count: int = 0) -> None:
        """
        Args:
            fail_count: Number of consecutive generate() calls to fail before succeeding.
                        Useful for testing gateway fallback logic.
        """
        self._fail_remaining = fail_count

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str,
        purpose: str,
        stream: bool = False,
        metadata: dict | None = None,
    ) -> LLMResponse:
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise LLMProviderError("Simulated provider failure (FakeLocalLLMProvider)")

        content = (
            f"[fake-local] Acknowledged {len(messages)} message(s) "
            f"for purpose='{purpose}' using model='{model}'."
        )
        return LLMResponse(
            content=content,
            model=model or "fake-local-v1",
            provider="fake-local",
            input_token_count=sum(len(m.content) for m in messages),
            output_token_count=len(content),
            latency_ms=0,
        )
