"""OpenRouter LLM provider.

Calls the OpenRouter API. HTTP client is injectable for testing.
API key is loaded from config only — never logged or exposed in errors.
Full prompts are never logged.

This provider is NOT activated unless LLM_PROVIDER=openrouter is configured.
MVP default is fake-local.
"""
from __future__ import annotations

import time

import httpx

from app.services.llm_gateway.protocol import LLMMessage, LLMProviderError, LLMResponse


class OpenRouterProvider:
    """OpenRouter LLM provider. Requires OPENROUTER_API_KEY from environment."""

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        timeout: int = 30,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "OpenRouter API key is required; set OPENROUTER_API_KEY in environment"
            )
        self._api_key = api_key
        self._timeout = timeout
        self._http_client = http_client  # injectable for unit tests — avoids real HTTP

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str,
        purpose: str,
        stream: bool = False,
        metadata: dict | None = None,
    ) -> LLMResponse:
        if stream:
            raise NotImplementedError(
                "Streaming is not implemented in the MVP OpenRouter provider"
            )

        # Authorization header is NOT logged anywhere — do not add to error messages
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": "ChatHR",
        }
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }

        own_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout)
        start = time.monotonic()

        try:
            resp = await client.post(self.BASE_URL, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Status code only — never log request headers or prompt content
            raise LLMProviderError(
                f"OpenRouter HTTP {exc.response.status_code}"
            ) from exc
        except httpx.TimeoutException:
            raise LLMProviderError("OpenRouter request timed out")
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"OpenRouter HTTP error: {type(exc).__name__}") from exc
        finally:
            if own_client:
                await client.aclose()

        latency_ms = int((time.monotonic() - start) * 1000)

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMProviderError("Unexpected OpenRouter response format") from exc

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", model),
            provider="openrouter",
            input_token_count=usage.get("prompt_tokens"),
            output_token_count=usage.get("completion_tokens"),
            latency_ms=latency_ms,
        )
