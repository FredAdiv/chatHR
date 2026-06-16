"""Embedding provider factory.

Production code must use embed_with_gateway() from gateway.py — not this factory directly.
This factory is retained for use in tests and direct provider access where needed.
"""
from app.core.config import settings
from app.services.embeddings.base import EmbeddingProvider

_PLACEHOLDER_KEYS = {"CHANGE_ME", "REPLACE_WITH_REAL_KEY_FOR_OPENROUTER"}


def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider
    if provider == "fake-local":
        from app.services.embeddings.fake_provider import FakeLocalProvider
        return FakeLocalProvider(
            dimension=settings.embedding_dimension,
            model_name=settings.embedding_model,
        )
    if provider == "openrouter":
        from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider
        api_key = settings.openrouter_api_key
        if not api_key or api_key in _PLACEHOLDER_KEYS:
            raise ValueError(
                "EMBEDDING_PROVIDER=openrouter requires OPENROUTER_API_KEY to be set"
            )
        return OpenRouterEmbeddingProvider(
            api_key=api_key,
            model=settings.openrouter_embedding_model,
            timeout=settings.llm_request_timeout_seconds,
        )
    raise ValueError(
        f"Unknown embedding provider: {provider!r}. "
        "Valid options: fake-local, openrouter."
    )
