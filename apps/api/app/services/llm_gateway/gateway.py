"""LLM Gateway — main entry point for all model calls.

All LLM calls MUST go through generate_with_gateway().
No module may call a provider directly.

Behavior:
1. Runs privacy guard on every message before any provider call.
2. Blocks and logs if high-severity PII is detected.
3. Resolves model (provided > settings.default_chat_model).
4. Calls the configured provider.
5. On failure, retries with fallback model if configured.
6. Logs usage metadata without prompts.
7. Returns LLMResponse.

What is never stored:
- Full prompts or message content
- Raw user text
- API keys or authorization headers
"""
from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.llm_gateway.factory import get_llm_provider
from app.services.llm_gateway.protocol import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    PrivacyGuardBlockedError,
)
from app.services.privacy.guard import check_text


async def generate_with_gateway(
    messages: list[LLMMessage],
    purpose: str,
    model: str | None = None,
    user_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> LLMResponse:
    """
    Main LLM entry point. All external model calls must go through here.

    Args:
        messages: Conversation messages (content is privacy-checked but not stored).
        purpose: Intent label for logging ('chat', 'debug', etc.).
        model: Override model. Falls back to settings.default_chat_model.
        user_id: Requesting user UUID (for usage log). None for background tasks.
        db: Optional DB session for usage logging. If None, logging is skipped.

    Raises:
        PrivacyGuardBlockedError: High-severity PII detected; call blocked.
        LLMProviderError: Provider failed and no fallback is available.
    """
    provider = get_llm_provider()
    resolved_model = model or settings.default_chat_model

    # ── Privacy guard (MUST run before provider) ──────────────────────────────
    # Name-context detection (full_name_context) runs only on user messages.
    # System and assistant messages contain document chunks / regulation text
    # that legitimately match "employment-context + Hebrew-word-pair" patterns.
    for msg in messages:
        result = check_text(msg.content, check_name_context=(msg.role == "user"))
        if not result.allowed:
            await _write_usage_log(
                db,
                user_id=user_id,
                provider=provider.provider_name,
                model=resolved_model,
                purpose=purpose,
                status="blocked_by_privacy_guard",
            )
            raise PrivacyGuardBlockedError(
                result.reason or "Privacy guard blocked the request."
            )

    # ── Provider call (with optional fallback) ────────────────────────────────
    start = time.monotonic()
    used_fallback = False
    status = "success"

    try:
        response = await provider.generate(messages, resolved_model, purpose)
    except LLMProviderError:
        fallback_model = settings.fallback_chat_model
        if fallback_model and fallback_model != resolved_model:
            try:
                response = await provider.generate(messages, fallback_model, purpose)
                used_fallback = True
                resolved_model = fallback_model
                status = "fallback_success"
            except LLMProviderError as fb_exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                await _write_usage_log(
                    db,
                    user_id=user_id,
                    provider=provider.provider_name,
                    model=resolved_model,
                    purpose=purpose,
                    status="failed",
                    latency_ms=latency_ms,
                    error_type=type(fb_exc).__name__,
                )
                raise
        else:
            latency_ms = int((time.monotonic() - start) * 1000)
            await _write_usage_log(
                db,
                user_id=user_id,
                provider=provider.provider_name,
                model=resolved_model,
                purpose=purpose,
                status="failed",
                latency_ms=latency_ms,
            )
            raise

    latency_ms = int((time.monotonic() - start) * 1000)
    response.used_fallback = used_fallback
    response.latency_ms = latency_ms

    await _write_usage_log(
        db,
        user_id=user_id,
        provider=provider.provider_name,
        model=response.model,
        purpose=purpose,
        status=status,
        input_token_count=response.input_token_count,
        output_token_count=response.output_token_count,
        latency_ms=latency_ms,
        used_fallback=used_fallback,
    )

    return response


async def _write_usage_log(
    db: AsyncSession | None,
    *,
    user_id: uuid.UUID | None,
    provider: str,
    model: str,
    purpose: str,
    status: str,
    input_token_count: int | None = None,
    output_token_count: int | None = None,
    latency_ms: int | None = None,
    used_fallback: bool = False,
    error_type: str | None = None,
) -> None:
    """Add a usage log row to the DB session. No prompt content is stored.

    Caller is responsible for db.commit().
    """
    if db is None:
        return

    from app.db.models.llm_usage_log import LLMUsageLog

    log = LLMUsageLog(
        id=uuid.uuid4(),
        user_id=user_id,
        provider=provider,
        model=model,
        purpose=purpose,
        status=status,
        input_token_count=input_token_count,
        output_token_count=output_token_count,
        latency_ms=latency_ms,
        used_fallback=used_fallback,
        error_type=error_type,
        # metadata_json intentionally omitted — no prompts, no user text
    )
    db.add(log)
