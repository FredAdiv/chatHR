# LLM Gateway — Phase 10

## Overview

The LLM Gateway is the single entry point for all AI model calls. No module may call an external LLM provider directly.

**Module:** `apps/api/app/services/llm_gateway/`  
**Entry point:** `generate_with_gateway(messages, purpose, model, user_id, db)`

## Architecture

```
Caller → generate_with_gateway()
           ↓
        Privacy Guard (blocks high-severity PII)
           ↓
        Provider (fake-local or openrouter)
           ↓
        Fallback (if primary fails and fallback_model is set)
           ↓
        LLMUsageLog (metadata only — no prompts)
           ↓
        LLMResponse
```

## Providers

| Provider | Description |
|---|---|
| `fake-local` | Default. Deterministic, no network calls. Safe for tests/dev. |
| `openrouter` | External API. Requires `OPENROUTER_API_KEY`. Not active by default. |

## Configuration

```env
LLM_PROVIDER=fake-local
OPENROUTER_API_KEY=CHANGE_ME
DEFAULT_CHAT_MODEL=anthropic/claude-haiku-4-5-20251001
FALLBACK_CHAT_MODEL=openai/gpt-4o-mini
LLM_REQUEST_TIMEOUT_SECONDS=30
```

## Privacy Guard

Privacy guard **always runs** before any provider call. It cannot be bypassed.

- High-severity findings (email, phone, Israeli ID) → call blocked, `PrivacyGuardBlockedError` raised.
- Medium-severity findings → logged but call proceeds.
- Full message content is never stored.

See [privacy.md](privacy.md) for detection details.

## Model Resolution

1. Use `model` parameter if provided.
2. Otherwise use `settings.default_chat_model`.
3. On primary failure: retry with `settings.fallback_chat_model` (if different from primary).

## LLM Usage Logging (`llm_usage_logs` table)

Each gateway call writes one row. **No prompts are stored.**

| Field | Description |
|---|---|
| `provider` | Provider name (fake-local, openrouter) |
| `model` | Model used |
| `purpose` | Intent label (chat, debug, etc.) |
| `status` | success / blocked_by_privacy_guard / failed / fallback_success |
| `input_token_count` | Tokens sent (if provider returns) |
| `output_token_count` | Tokens generated |
| `latency_ms` | End-to-end latency |
| `used_fallback` | Whether fallback model was used |
| `error_type` | Exception class name on failure |
| `user_id` | Requesting user UUID (nullable) |

**Intentionally absent:** prompt, message, user_text, content — no full prompt storage.

## Admin API

Base path: `/admin/llm-gateway`  
Authorization: `system_admin` only. All checks server-side.

### GET `/admin/llm-gateway/health`

Returns gateway configuration summary. No secrets returned.

```json
{
  "provider_configured": "fake-local",
  "default_model": "anthropic/claude-haiku-4-5-20251001",
  "fallback_model_configured": true,
  "privacy_guard_enabled": true,
  "openrouter_configured": false
}
```

### POST `/admin/llm-gateway/test-generate`

Admin/debug: send a single message through the full gateway pipeline.

**Input:**
```json
{"message": "string (min 1)", "purpose": "debug", "model": null}
```

**Success (200):**
```json
{"content": "...", "model": "...", "provider": "fake-local", "used_fallback": false}
```

**PII blocked (422):**
```json
{
  "detail": {
    "error": "privacy_guard_blocked",
    "reason": "High-severity PII detected ...",
    "findings": [{"type": "email", "severity": "high"}]
  }
}
```

Note: `matched_text` is never returned in findings. Raw sensitive text is never exposed.

## Fake Provider

`FakeLocalLLMProvider` — deterministic, no network calls.

- Returns `[fake-local] Acknowledged N message(s) for purpose='...' using model='...'`.
- Supports `fail_count` parameter to simulate failures for fallback testing.
- No token counting (deterministic counts only).

## OpenRouter Provider (Skeleton)

`OpenRouterProvider` — full HTTP implementation, injectable client for tests.

- Requires `OPENROUTER_API_KEY` from environment.
- HTTP client is injectable via `__init__` parameter — real network never called in tests.
- API key is never logged or included in error messages.
- On failure: error type only is logged, never request body or headers.
- Streaming is not implemented in MVP (`NotImplementedError`).

## Constraints

- No module may call an LLM provider directly — must use `generate_with_gateway()`.
- Privacy guard cannot be bypassed or disabled.
- Full prompts are not stored by default.
- No raw user text in audit metadata or usage logs.
- OpenRouter is configured but not active unless `LLM_PROVIDER=openrouter`.
- No real OpenRouter calls in tests (fake-local is default).
- `system_admin` only for all admin endpoints.

## Migration

Apply migration 0007 to create `llm_usage_logs`:

```bash
docker compose run --rm api alembic upgrade head
```

## Limitations (MVP)

- No real model calls — `fake-local` only; responses are not semantically meaningful.
- No streaming support.
- No chat/RAG answer generation yet.
- No frontend UI.
- No purpose-specific model routing beyond default/fallback.
- Usage logs are not exposed via any list/query API.
