# Embeddings — Phase 8

## Overview

Phase 8 adds pgvector support, chunk embedding generation, and an admin vector search endpoint.  
No external embedding API is called in this phase. All embeddings use the **fake-local** deterministic provider.

## pgvector Requirement

The PostgreSQL container must be pgvector-enabled:

```yaml
# docker-compose.yml
postgres:
  image: pgvector/pgvector:pg16
```

The `0005_embeddings` Alembic migration enables the extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Embedding Provider

### Fake-local (MVP only)

`EMBEDDING_PROVIDER=fake-local`

Produces unit vectors derived from SHA-256 of the input text.

- Deterministic: same text → same vector every time.
- No external service calls.
- Not semantically meaningful — structural testing only.
- Dimension configurable via `EMBEDDING_DIMENSION` (default: 16).

### Future providers

Real providers (OpenRouter, dedicated embedding gateway) are future work.  
They must:

1. Route through the internal **LLM Gateway**.
2. Pass the **privacy guard** before any text is sent externally.
3. Never store raw prompts or document text in logs.

## Database Table: `chunk_embeddings`

| Column               | Type       | Description                                        |
|----------------------|------------|----------------------------------------------------|
| id                   | UUID PK    |                                                    |
| document_chunk_id    | UUID FK    | References `document_chunks.id`                    |
| source_document_id   | UUID FK    | References `source_documents.id`                   |
| parsed_document_id   | UUID FK    | References `parsed_documents.id`                   |
| index_version_id     | UUID FK?   | References `index_versions.id` (nullable)          |
| embedding_model      | text       | e.g. `fake-local-v1`                              |
| embedding_dimension  | integer    | Dimension of the stored vector                     |
| embedding            | vector     | pgvector column (unconstrained dimension)           |
| content_hash         | text       | SHA-256 of the embedded chunk text                 |
| status               | text       | `embedded` or `failed`                             |
| error_message        | text?      | Safe error, no chunk text included                 |
| metadata_json        | jsonb?     | Provider-specific metadata                         |
| created_at / updated_at | timestamptz |                                               |

**UniqueConstraint:** `(document_chunk_id, embedding_model, content_hash, index_version_id)`  
**Note:** PostgreSQL treats NULL values as distinct in unique indexes; if `index_version_id` is NULL, uniqueness is enforced per-row.

**Vector index:** IVFFlat/HNSW index is not created at MVP stage — add after data volume warrants it.

## Embedding Generation

### Rules

- Only `building` index versions accept embeddings. Ready/active/archived/quality_check_failed versions are immutable.
- Duplicate detection: if a `ChunkEmbedding` already exists for the same `(document_chunk_id, embedding_model, content_hash, index_version_id)`, the chunk is skipped.
- `DocumentChunk` rows are never mutated.
- Failed embeddings store a `status=failed` row with a safe error message (no chunk text).
- Embeddings do **not** activate the index version.
- Audit metadata contains counts only — no chunk text or raw content.

### Audit Action

| Action                | Description                          |
|-----------------------|--------------------------------------|
| `embeddings_generated` | Embedding run completed; counts only |

## Admin API

Base path: `/admin/embeddings`  
Authorization: `knowledge_admin` or `system_admin` only. All checks server-side.

### POST `/admin/embeddings/generate`

Generates embeddings synchronously for a `building` index version.

**Input:**

| Field                | Type    | Required |
|----------------------|---------|----------|
| index_version_id     | UUID    | ✅        |
| parsed_document_id   | UUID    | optional |
| source_document_id   | UUID    | optional |

**Returns:** generation summary (counts, model, dimension). No raw vectors.

**Errors:**
- 404 if index version not found.
- 409 if index version is not `building`.

### GET `/admin/embeddings`

Lists `ChunkEmbedding` records. Filters: `index_version_id`, `source_document_id`, `parsed_document_id`, `embedding_model`, `embedding_status` (`embedded`|`failed`).

Returns metadata only — **no raw embedding vectors**.

### POST `/admin/embeddings/search`

Admin/debug vector similarity search using cosine distance.

**Input:**

| Field            | Type    | Required | Constraints   |
|------------------|---------|----------|---------------|
| index_version_id | UUID    | ✅        |               |
| query_text       | string  | ✅        | min_length=1  |
| limit            | integer | optional | 1–20          |

**Returns:** top chunks by cosine distance (chunk_id, chunk_text, source_document_id, parsed_document_id, distance).

No external service calls are made. Raw embedding vectors are not returned.

## Configuration

| Variable             | Default         | Description                          |
|----------------------|-----------------|--------------------------------------|
| `EMBEDDING_PROVIDER` | `fake-local`    | Provider name                        |
| `EMBEDDING_DIMENSION`| `16`            | Vector dimension                     |
| `EMBEDDING_MODEL`    | `fake-local-v1` | Model name stored in DB              |

## Current Limitations

- Fake embeddings have no semantic meaning (hash-based).
- Generation is synchronous (no background task queue).
- No production ranking — plain cosine similarity only.
- No chat integration yet.
- No real external embedding provider yet.
- IVFFlat/HNSW vector index not yet created.

## Next Steps

Phase 9: Real embedding provider integration via LLM Gateway, with privacy guard.  
Phase 10: RAG retrieval pipeline — similarity search, authority ranking, citation generation, chat endpoint.

## Docker / Manual Checks

```bash
# Start the stack
docker compose up --build

# Apply migrations
docker compose run --rm api alembic upgrade head

# Verify pgvector extension
docker compose exec postgres psql -U chathr_user -d chathr -c "SELECT extname FROM pg_extension WHERE extname='vector';"
```
