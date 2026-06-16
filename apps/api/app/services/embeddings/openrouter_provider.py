"""OpenRouter embedding provider.

Calls POST /api/v1/embeddings (OpenAI-compatible) on the OpenRouter API.
- Injectable http_client for testing (no real network in unit tests).
- Never logs API key, raw text, or response content.
- Raises EmbeddingProviderError on HTTP/timeout/network errors.
- model_name and dimension are discovered from the first response.
"""
from __future__ import annotations

import httpx


class EmbeddingProviderError(Exception):
    """Raised when the embedding provider cannot fulfill the request."""


class OpenRouterEmbeddingProvider:
    """Real semantic embeddings via OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1/embeddings"
    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 30,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouterEmbeddingProvider requires a non-empty API key")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._http_client = http_client
        # Dimension is set after the first successful call
        self._dimension: int | None = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int | None:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return one vector per text."""
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": "ChatHR",
        }
        payload = {"model": self._model, "input": texts}

        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=self._timeout)

        try:
            try:
                resp = await client.post(self.BASE_URL, headers=headers, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise EmbeddingProviderError(
                    f"OpenRouter embeddings HTTP {exc.response.status_code}"
                ) from exc
            except httpx.TimeoutException as exc:
                raise EmbeddingProviderError("OpenRouter embeddings request timed out") from exc
            except httpx.RequestError as exc:
                raise EmbeddingProviderError("OpenRouter embeddings network error") from exc

            data = resp.json()
            items = sorted(data["data"], key=lambda x: x["index"])
            vectors = [item["embedding"] for item in items]

            # Discover and cache dimension from first response
            if vectors and self._dimension is None:
                self._dimension = len(vectors[0])

            return vectors
        finally:
            if owns_client:
                await client.aclose()
