# Retrieval — Phase 9

## Overview

Phase 9 adds a server-side retrieval service over existing `ChunkEmbedding`, `DocumentChunk`, `SourceDocument`, and `KnowledgeSource` records.

**Admin/debug only.** No LLM answer generation. No OpenRouter calls.  
Results are not semantically meaningful until real embeddings replace the fake-local provider.

## Retrieval Service

Function: `retrieve_chunks(db, query_text, index_version_id, context_type, limit, min_score)`

### Behavior

1. Embeds `query_text` using the configured embedding provider (fake-local in MVP).
2. Searches `chunk_embeddings` joined to `document_chunks`, `parsed_documents`, `source_documents`, `knowledge_sources`.
3. Filters: `index_version_id`, `embedding_model` (from provider), `status='embedded'`.
4. Optional context_type filter: includes sources with matching `context_type` **OR** `context_type IS NULL` (null = general source, applicable to all contexts).
5. Sorted: cosine distance ASC → authority_level ASC (lower = stronger authority) → chunk_index ASC.
6. Applies optional `min_score` filter (score = 1 - distance).

### Constraints

- `query_text` is **never** stored in audit metadata or logs.
- No text is sent to external services.
- No LLM call, no answer generation.
- Returns at most `limit` results (max 20 via API).

## Authority Hierarchy

Lower `authority_level` = stronger authority (used as tie-breaker after vector score):

| Level | Source type |
|-------|-------------|
| 1 | Salary agreements / תקשי"ר (highest) |
| 2 | Commissioner guidelines / official circulars |
| 3 | Policy documents / implementation guidelines |
| 4 | Approved FAQ |
| 5 | General explanatory documents (lowest) |

No contradiction resolution between sources of different authority levels yet.

## Citation Metadata

Each retrieved chunk includes:

| Field | Description |
|-------|-------------|
| `source_url` | URL of the source document |
| `source_title` | Title of the source document |
| `knowledge_source_id` | UUID of the KnowledgeSource |
| `knowledge_source_name` | Name of the KnowledgeSource |
| `authority_level` | Authority level 1–5 |
| `section_title` | Section heading (if available) |
| `page_number` | Page number (if available) |
| `chunk_index` | Sequential chunk index within parsed document |
| `document_type` | html, pdf, docx, xlsx, unknown |

Citation metadata is built by `build_citation_metadata(...)` and used directly in retrieval results. Future RAG answers will attach citations to generated text.

## Context Filtering

`KnowledgeSource.context_type` (nullable) groups sources by civil service sector:

| Value | Sector |
|-------|--------|
| `government_ministries` | Government ministries |
| `defense_system` | Defense system |
| `health_system` | Health system |
| `null` | General — applies to all contexts |

When `context_type` is passed to retrieval, sources matching the type **plus** all general (null) sources are included. This is coarse MVP filtering — finer-grained document-level filtering is future work.

## Admin API

Base path: `/admin/retrieval`  
Authorization: `knowledge_admin` or `system_admin` only. All checks server-side.

### POST `/admin/retrieval/search`

Debug vector search.

**Input:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| query_text | string | ✅ | min_length=1 |
| index_version_id | UUID | ✅ | |
| context_type | string | optional | `government_ministries` / `defense_system` / `health_system` |
| limit | integer | optional | 1–20, default 5 |
| min_score | float | optional | 0.0–1.0 |

**Returns:** list of `SearchResultItem` with `chunk_text` and `citation` metadata.

Audit action `retrieval_debug_search` — counts only, no `query_text`.

### GET `/admin/retrieval/health`

Returns embedding provider config and `vector_search_available` flag.  
No DB query performed.

## Admin API — Knowledge Sources context_type

`POST /admin/knowledge-sources` and `PATCH /admin/knowledge-sources/{id}` now accept:

```json
{"context_type": "government_ministries"}
```

Valid values: `government_ministries`, `defense_system`, `health_system`, `null`.  
`GET /admin/knowledge-sources` supports `?context_type=` filter.

## Current Limitations

- Retrieval is admin/debug only — not exposed to regular chat users yet.
- Fake embeddings are not semantically meaningful; results are deterministic but not relevant.
- No real embedding provider — all results use hash-based fake vectors.
- No LLM answer generation, no OpenRouter calls.
- No contradiction resolution between authority levels.
- No answer synthesis — chunk_text is returned raw.
- No frontend UI.
- Context filtering is source-level only (not document or chunk level).
- Synchronous retrieval (no background indexing).

## Next Steps

Phase 10: Real embedding provider via LLM Gateway with privacy guard, RAG answer generation with citations, chat endpoint with streaming, OpenRouter integration.
