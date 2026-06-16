# Chat Flow — Phase 11

## Overview

The Chat API provides a secure, RAG-backed conversation interface for `chat_user` and `system_admin` roles. All answers are grounded in official knowledge sources retrieved via vector search.

**Module:** `apps/api/app/api/chat.py`  
**Prompt service:** `apps/api/app/services/chat/prompt_builder.py`

## Architecture

```
User → POST /chat/conversations/{id}/messages
         ↓
      Ownership check (conversation belongs to user)
         ↓
      Privacy Guard (check_text on user content)
         ↓ blocked → 422, nothing stored
         ↓ allowed
      Store user message
         ↓
      retrieve_chunks (pgvector, active index, conversation.context_type)
         ↓ no results → store refusal assistant message, return 200 (no LLM call)
         ↓ results found
      build_chat_prompt (transient — never stored)
         ↓
      generate_with_gateway (purpose="chat_answer", fake-local by default)
         ↓
      Store assistant message + MessageSource rows
         ↓
      Return: message, sources list, retrieval_count
```

## Authorization

| Role | Can access /chat |
|---|---|
| `chat_user` | ✅ Yes |
| `system_admin` | ✅ Yes (own conversations only) |
| `user_admin` | ❌ No |
| `faq_manager` | ❌ No |
| `knowledge_admin` | ❌ No |

All checks are server-side. No client-side authorization.

## Endpoints

Base path: `/chat`  
Authorization: `chat_user` OR `system_admin`

### POST `/chat/conversations`

Create a new conversation.

**Input:**
```json
{"context_type": "government_ministries | defense_system | health_system", "title": "optional string"}
```

**Success (201):**
```json
{"id": "uuid", "context_type": "...", "title": null, "created_at": "iso8601"}
```

### GET `/chat/conversations`

List current user's conversations only. No admin override for viewing other users' conversations.

### GET `/chat/conversations/{conversation_id}`

Get conversation with all messages.

- Owner only — non-owner gets 404 (not 403, to avoid leaking existence).

### POST `/chat/conversations/{conversation_id}/messages`

Send a user message and receive an AI answer.

**Input:**
```json
{
  "content": "string (required, min 1)",
  "index_version_id": "optional UUID — if omitted, active index is used",
  "limit": "optional int 1-10, default 5"
}
```

**Flow:**
1. Check conversation belongs to current user.
2. Run privacy guard on `content` — if high-severity PII found, return 422 (nothing stored, no retrieval, no LLM).
3. Resolve index version (must be `active`; otherwise 503).
4. Store user message.
5. Retrieve chunks using `context_type` + active index.
6. If no chunks: store assistant message with safe refusal text, return 200 (no LLM call).
7. If chunks found: build transient prompt, call LLM Gateway, store assistant message + MessageSource rows.

**Success (200):**
```json
{
  "message": {"id": "...", "role": "assistant", "content": "...", "created_at": "..."},
  "sources": [{"chunk_id": "...", "knowledge_source_name": "...", "authority_level": 1, ...}],
  "retrieval_count": 3
}
```

**Privacy blocked (422):**
```json
{"detail": {"error": "privacy_guard_blocked", "reason": "...", "findings": [{"type": "email", "severity": "high"}]}}
```
Note: `matched_text` is never included in findings.

**No active index (503):**
```json
{"detail": "No active knowledge index available."}
```

### POST `/chat/messages/{message_id}/feedback`

Submit thumbs up/down feedback for an assistant message.

**Authorization:** Owner of the conversation only. Feedback only allowed on `assistant` messages.

**Input:**
```json
{"rating": "positive | negative", "comment": "optional string"}
```

Comment is privacy-guarded — high-severity PII in comment returns 422.

## Safety Rules

| Rule | Enforced |
|---|---|
| No professional answer without sources | ✅ No LLM call if retrieval returns nothing |
| No LLM call when no sources | ✅ Enforced in endpoint |
| Privacy guard before storing user text | ✅ Guard runs before INSERT |
| No full prompt stored | ✅ Prompt is transient — never persisted |
| No user text in metadata | ✅ metadata_json has counts/IDs only |
| No sources → safe refusal | ✅ Fixed Hebrew refusal string |
| Only active index used | ✅ Non-active index returns 422/503 |
| Feedback PII guard | ✅ Comment checked before storing |

## Prompt Assembly

`build_chat_prompt(user_question, retrieval_results, context_type)` in `services/chat/prompt_builder.py`:

- Returns `list[LLMMessage]` (system + user).
- **Never persisted** — caller must not store the return value.
- System message: strict instruction — answer only from provided sources, cite sources, if insufficient say no official source.
- User message: includes question + labeled source blocks with `chunk_text` and citation labels.
- No raw UUIDs as visible source labels — human-readable labels from title + knowledge_source_name.

## Message Metadata

`messages.metadata_json` stores safe metadata only:

| Field | Description |
|---|---|
| `answer_mode` | `"retrieval_augmented"` or `"no_sources"` |
| `retrieval_count` | Number of chunks retrieved |
| `source_chunk_ids` | List of chunk UUIDs |
| `index_version_id` | UUID of the index version used |

**Never stored in metadata_json:** prompt text, user question, chunk_text, model output.

## MessageSource Table

Stores one row per retrieved source used in each assistant answer.

| Column | Description |
|---|---|
| `message_id` | FK to messages.id |
| `document_chunk_id` | FK to document_chunks.id (nullable) |
| `source_document_id` | FK to source_documents.id (nullable) |
| `knowledge_source_id` | FK to knowledge_sources.id (nullable) |
| `citation_json` | Citation metadata (JSONB) |

`citation_json` contains: chunk_id, knowledge_source_id/name, authority_level, source_title, source_url, section_title, page_number, document_type.

**Not stored:** full chunk_text, prompt content, user text, API keys.

## Limitations (MVP)

- Fake-local LLM only — responses are deterministic placeholders, not semantically grounded.
- No real OpenRouter calls.
- No streaming.
- No frontend UI.
- No real semantic embeddings (fake-local embedding provider).
- No conversation search or pagination.
- No FAQ answer integration.
- No authority conflict resolution in prompt (authority_level included in sources but not resolved).

## Migration

Apply migration 0008:

```bash
docker compose run --rm api alembic upgrade head
```

This migration:
- Adds `metadata_json` (JSONB nullable) to `messages`
- Creates `message_sources` table
