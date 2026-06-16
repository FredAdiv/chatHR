"""LLM provider factory.

Resolves the configured provider from settings.
Default: fake-local (no external calls, safe for tests/dev).
Real providers require explicit opt-in via LLM_PROVIDER env var.
"""
from __future__ import annotations

from app.core.config import settings
from app.services.llm_gateway.protocol import LLMProvider


def get_llm_provider() -> LLMProvider:
    """Return the LLM provider configured in settings.

    fake-local: deterministic, no network calls.
    openrouter: requires OPENROUTER_API_KEY; not used unless explicitly selected.
    """
    provider_name = settings.llm_provider

    if provider_name == "fake-local":
        from app.services.llm_gateway.fake_provider import FakeLocalLLMProvider
        return FakeLocalLLMProvider()

    if provider_name == "openrouter":
        from app.services.llm_gateway.openrouter_provider import OpenRouterProvider
        api_key = settings.openrouter_api_key
        _PLACEHOLDER_KEYS = {"CHANGE_ME", "REPLACE_WITH_REAL_KEY_FOR_OPENROUTER"}
        if not api_key or api_key in _PLACEHOLDER_KEYS:
            raise ValueError(
                "LLM_PROVIDER=openrouter requires OPENROUTER_API_KEY to be set in the environment"
            )
        return OpenRouterProvider(
            api_key=api_key,
            timeout=settings.llm_request_timeout_seconds,
        )

    raise ValueError(
        f"Unknown LLM provider: {provider_name!r}. Valid options: fake-local, openrouter."
    )
