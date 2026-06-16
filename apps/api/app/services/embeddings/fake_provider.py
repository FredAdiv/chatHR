"""Fake deterministic local embedding provider for MVP dev/tests.

Produces unit vectors derived from SHA-256 of the input text.
- Same text always gives the same vector (deterministic).
- Different texts usually give different vectors.
- Does NOT call any external service.
- Not semantically meaningful — for structural testing only.
"""
import hashlib
import math


class FakeLocalProvider:
    """Deterministic fake embeddings. Not for production use."""

    def __init__(self, dimension: int = 16, model_name: str = "fake-local-v1") -> None:
        if dimension < 1:
            raise ValueError("dimension must be at least 1")
        self._dimension = dimension
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        if not text:
            # Return a zero vector for empty text so callers get a valid-length result
            return [0.0] * self._dimension

        raw_hash = hashlib.sha256(text.encode("utf-8")).digest()
        # Tile hash bytes to cover the required dimension
        tile_count = (self._dimension // len(raw_hash)) + 2
        raw_bytes = (raw_hash * tile_count)[: self._dimension]

        # Map bytes to [-1, 1]
        floats = [(b - 128) / 128.0 for b in raw_bytes]

        # Normalize to unit vector
        magnitude = math.sqrt(sum(f * f for f in floats)) or 1.0
        return [f / magnitude for f in floats]
