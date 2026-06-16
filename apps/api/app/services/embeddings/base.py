"""Embedding provider protocol and result types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
import uuid


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers.

    MVP: only fake-local is implemented.
    Future real providers must route through the LLM Gateway and pass the
    privacy guard before any text is sent to an external service.
    """

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


@dataclass
class EmbeddingGenerationResult:
    index_version_id: uuid.UUID
    embedding_model: str
    embedding_dimension: int
    chunks_found: int
    embedded_count: int
    skipped_count: int
    failed_count: int
