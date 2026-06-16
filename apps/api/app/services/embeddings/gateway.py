"""Embeddings Gateway — the single entry point for all embedding generation.

All embedding calls (indexing, FAQ sync, retrieval query) must go through
embed_with_gateway(). Direct provider calls from outside this module are
not allowed.

Provider dispatch:
  fake-local  → FakeLocalProvider.embed_texts() (sync, no IO, safe for tests/dev)
  openrouter  → OpenRouterEmbeddingProvider.embed() (async HTTP)

Indexing callers: pass approved official document text (privacy guard not required).
Retrieval callers: query text has already passed the LLM Gateway privacy guard.
"""
from __future__ import annotations

from app.core.config import settings


async def embed_with_gateway(
    texts: list[str],
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
) -> list[list[float]]:
    """Return one embedding vector per input text.

    Args:
        texts: Non-empty list of strings to embed.
        embedding_provider: Override the configured provider. If None, uses
            settings.embedding_provider.
        embedding_model: Override the configured model. If None, uses the
            provider's default from settings.

    Returns:
        List of float vectors, one per input text.

    Raises:
        ValueError: Unknown provider or missing configuration.
        EmbeddingProviderError: Provider call failed.
    """
    provider_name = embedding_provider or settings.embedding_provider

    if provider_name == "fake-local":
        from app.services.embeddings.fake_provider import FakeLocalProvider
        model = embedding_model or settings.embedding_model
        dimension = settings.embedding_dimension
        provider = FakeLocalProvider(dimension=dimension, model_name=model)
        return provider.embed_texts(texts)

    if provider_name == "openrouter":
        from app.services.embeddings.openrouter_provider import OpenRouterEmbeddingProvider
        _PLACEHOLDER_KEYS = {"CHANGE_ME", "REPLACE_WITH_REAL_KEY_FOR_OPENROUTER"}
        api_key = settings.openrouter_api_key
        if not api_key or api_key in _PLACEHOLDER_KEYS:
            raise ValueError(
                "EMBEDDING_PROVIDER=openrouter requires OPENROUTER_API_KEY to be set"
            )
        model = embedding_model or settings.openrouter_embedding_model
        provider = OpenRouterEmbeddingProvider(
            api_key=api_key,
            model=model,
            timeout=settings.llm_request_timeout_seconds,
        )
        return await provider.embed(texts)

    raise ValueError(
        f"Unknown embedding provider: {provider_name!r}. "
        "Valid options: fake-local, openrouter."
    )


def get_embedding_dimension(provider_name: str | None = None) -> int:
    """Return the configured dimension for the given provider."""
    p = provider_name or settings.embedding_provider
    if p == "fake-local":
        return settings.embedding_dimension
    # For openrouter, return the known dimension for the configured model
    # text-embedding-3-small → 1536, text-embedding-ada-002 → 1536
    # Update if a different model with different dimensions is used
    return 1536
