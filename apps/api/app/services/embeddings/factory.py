"""Embedding provider factory.

MVP: supports only fake-local.
Future providers (OpenRouter, dedicated embedding gateway) must:
- Route through the internal LLM Gateway.
- Pass the privacy guard before any text is sent externally.
- Never store raw prompts or document text in logs.
"""
from app.core.config import settings
from app.services.embeddings.base import EmbeddingProvider


def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider
    if provider == "fake-local":
        from app.services.embeddings.fake_provider import FakeLocalProvider
        return FakeLocalProvider(
            dimension=settings.embedding_dimension,
            model_name=settings.embedding_model,
        )
    raise ValueError(
        f"Unknown embedding provider: {provider!r}. "
        "Only 'fake-local' is supported in this MVP. "
        "Real providers are future work and must pass the privacy guard."
    )
