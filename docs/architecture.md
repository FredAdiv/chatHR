# ChatHR – Architecture

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js |
| Backend API | FastAPI |
| Database | PostgreSQL |
| Vector search | pgvector (PostgreSQL extension) |
| Queue / cache | Redis |
| Object storage | MinIO (local) |
| Runtime | Docker Compose |
| AI Gateway | OpenRouter (via internal LLM Gateway) |

## Project Structure

```
gov-hr-chatbot/
├── apps/
│   ├── web/          # Next.js frontend
│   └── api/          # FastAPI backend
├── packages/
│   └── shared/       # Shared types and utilities
├── ingestion/
│   ├── crawlers/     # Source crawling scripts
│   ├── parsers/      # Document text extraction
│   └── chunking/     # Splitting into knowledge units
├── rag/
│   ├── retrieval/    # Vector search and ranking
│   ├── ranking/      # Re-ranking and authority scoring
│   ├── citation/     # Citation generation and linking
│   └── authority/    # Authority hierarchy enforcement
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evals/        # RAG quality evaluations
└── docs/
```

## Component Descriptions

### apps/api (FastAPI)

- Authentication and session management
- RBAC enforcement (server-side only)
- Chat endpoint with streaming support
- FAQ management endpoints
- User and role management endpoints
- Audit log recording
- Proxy to LLM Gateway

### apps/web (Next.js)

- Login and session UI
- Chat interface with streaming response display
- Civil service context selector
- Source citation display
- Thumbs up/down feedback
- Admin panels (FAQ management, user management, indexing, feedback review)

### LLM Gateway

Internal layer wrapping OpenRouter. No module may call OpenRouter directly.

Responsibilities:
- Route requests to default or fallback model
- Support different models by purpose (chat, embeddings)
- Stream responses to end users
- Log model, tokens, latency, errors, fallback usage
- Run privacy guard before every model call
- Never store full prompts by default

### RAG Pipeline

**Initial build:**
1. Crawl knowledge sources
2. Download documents
3. Extract text
4. Identify document structure
5. Split into sections, paragraphs, and knowledge units
6. Add metadata (source, date, authority level, context)
7. Create embeddings
8. Store as index version
9. Run quality checks
10. Publish active index version

**Differential update:**
- Detect new, updated, and disappeared documents
- Detect FAQ changes
- Update only changed content
- Build new index version aside
- Run quality checks before activation
- Support rollback

**Rule:** Never update the active index directly.

### RBAC Roles

| Role | Permissions |
|---|---|
| `chat_user` | Ask questions, view own history, give feedback |
| `faq_manager` | Create, edit, approve, manage FAQ items |
| `user_admin` | Manage users and roles |
| `feedback_reviewer` | View ratings and feedback |
| `knowledge_admin` | Manage sources, run indexing, approve/rollback index versions |
| `system_admin` | Manage system settings and advanced permissions |

A user may hold multiple roles. All authorization checks happen server-side.

### Audit Log

All administrative actions are recorded: user creation, role changes, user deactivation, FAQ lifecycle, feedback viewing, indexing runs, index activation/rollback, system setting changes.

## Data Flow (Chat Request)

```
User → Next.js → FastAPI (auth + RBAC check)
     → Privacy Guard → RAG retrieval (pgvector)
     → Authority ranking + citation generation
     → LLM Gateway → OpenRouter → streaming response
     → Feedback collection
```

## Security Constraints

- No anonymous access
- No client-side-only authorization
- No secrets in code — all from env files
- No full prompt storage by default
- Privacy guard runs before every model call
- No personal data sent to external models

## Implementation Status

### Phase 1 — Runnable Skeleton ✅

| Component | Status |
|---|---|
| `docker-compose.yml` (api, web, postgres, redis, minio) | ✅ Done |
| FastAPI app with `/health` and `/ready` endpoints | ✅ Done |
| Next.js app with home page and API health display | ✅ Done |
| Unit test for `/health` | ✅ Done |

### Phase 2 — Database Foundation ✅

| Component | Status |
|---|---|
| Alembic migration setup | ✅ Done |
| Initial migration (all 10 core tables) | ✅ Done |
| SQLAlchemy 2.0 async models | ✅ Done |
| RBAC role constants and server-side helpers | ✅ Done |
| Audit log helper (`record_audit_event`) | ✅ Done |
| Role seed script (idempotent) | ✅ Done |
| Dev endpoint `GET /dev/db-info` | ✅ Done |
| Unit tests for RBAC and audit helpers | ✅ Done |
| `docs/database.md` | ✅ Done |

### Phase 3 — Authentication & Authorization ✅

| Component | Status |
|---|---|
| `POST /auth/login` — bcrypt verify, JWT issue, audit | ✅ Done |
| `GET /auth/me` — token validation, user profile | ✅ Done |
| `GET/POST /admin/users` — CRUD with RBAC | ✅ Done |
| `PATCH /admin/users/{id}/roles` — role replacement + audit | ✅ Done |
| `PATCH /admin/users/{id}/deactivate` — deactivation + audit | ✅ Done |
| `GET /dev/db-info` protected with `system_admin` role | ✅ Done |
| Alembic migration 0002 (password_hash, last_login_at) | ✅ Done |
| `scripts/create_initial_admin.py` — idempotent bootstrap | ✅ Done |
| Unit tests: security (8 tests), auth API (4 tests) | ✅ Done |
| `docs/auth.md` | ✅ Done |

### Phase 4 — Route Authorization Tests & FAQ Management Backend ✅

| Component | Status |
|---|---|
| Route-level auth tests: /admin/users (chat_user/user_admin/system_admin) | ✅ Done |
| Route-level auth tests: /dev/db-info (user_admin/system_admin) | ✅ Done |
| GET /admin/faq with role guard + filters (status, context_type, topic) | ✅ Done |
| POST /admin/faq — create draft, validate fields, audit | ✅ Done |
| PATCH /admin/faq/{id} — update, auto-draft on approved edit, version++ | ✅ Done |
| PATCH /admin/faq/{id}/approve — set approved + approver + timestamp | ✅ Done |
| PATCH /admin/faq/{id}/archive — set archived, block edits | ✅ Done |
| 21 new unit tests (admin route auth + FAQ API behavior) | ✅ Done |
| docs/faq.md | ✅ Done |

### Phase 5 — Knowledge Sources & Index Versions ✅

| Component | Status |
|---|---|
| GET/POST/PATCH /admin/knowledge-sources — CRUD with authority_level 1-5 validation | ✅ Done |
| PATCH /admin/knowledge-sources/{id}/deactivate + activate | ✅ Done |
| GET/POST /admin/index-versions — create in building status | ✅ Done |
| PATCH /admin/index-versions/{id}/mark-ready — building → ready | ✅ Done |
| PATCH /admin/index-versions/{id}/mark-quality-failed | ✅ Done |
| PATCH /admin/index-versions/{id}/activate — ready → active, auto-archives previous | ✅ Done |
| PATCH /admin/index-versions/{id}/archive — ready/quality_check_failed → archived | ✅ Done |
| FAQ status filter validated as Literal (draft/approved/archived) | ✅ Done |
| Unit tests: 20 new tests (knowledge sources + index versions + FAQ status filter) | ✅ Done |
| docs/knowledge-sources.md | ✅ Done |
| docs/indexing.md | ✅ Done |

**Constraints enforced:**
- At most one active index version at any time (enforced in application code during activation; DB-level partial unique index is future work)
- Active index version cannot be archived directly — only replaced by activating a newer `ready` version
- Only `ready` versions can be activated; `building`, `quality_check_failed`, and `archived` cannot
- `mark-quality-failed` allowed only from `building` or `ready`; blocked on `active`, `archived`, and `quality_check_failed`
- authority_level query filter on GET /admin/knowledge-sources validated 1-5 at API level
- `knowledge_admin` and `system_admin` only — all checks server-side

### Phase 6 — Ingestion Foundation ✅

| Component | Status |
|---|---|
| `SourceDocument` model + migration | ✅ Done |
| `IngestionRun` model + migration | ✅ Done |
| `IngestionRunDocument` model + migration | ✅ Done |
| URL validation helper (rejects private IPs, non-http/https) | ✅ Done |
| SHA-256 content hash helper (change detection) | ✅ Done |
| Document type detection (html/pdf/docx/xlsx/unknown) | ✅ Done |
| MinIO storage helper (`ensure_bucket_exists`, `put_bytes`) | ✅ Done |
| Safe HTTP fetch skeleton (20 MB limit, 5 redirects, 30s timeout) | ✅ Done |
| Ingestion orchestration: `run_ingestion_for_source` | ✅ Done |
| Modes: `dry_run`, `metadata_only`, `download` | ✅ Done |
| POST /admin/ingestion/runs — start run synchronously | ✅ Done |
| GET /admin/ingestion/runs — list with filters | ✅ Done |
| GET /admin/ingestion/runs/{id} — run with document details | ✅ Done |
| GET /admin/ingestion/source-documents — list with filters | ✅ Done |
| Unit tests: 52 new tests (helpers + orchestrator + API) | ✅ Done |
| docs/ingestion.md | ✅ Done |

**Constraints:**
- MVP processes only the knowledge source's root URL — no recursive crawling
- Raw document bytes stored only in MinIO, never in DB or audit logs
- No document text parsing, chunking, or embeddings
- Private/internal IP addresses blocked at URL validation layer
- All authorization server-side (knowledge_admin and system_admin only)

### Phase 7 — Document Parsing and Chunking ✅

| Component | Status |
|---|---|
| DB models: ParsedDocument, DocumentChunk | ✅ Done |
| Alembic migration 0004_parsing_tables | ✅ Done |
| HTML parser (BeautifulSoup, removes script/style) | ✅ Done |
| PDF parser (pypdf, text layer only, no OCR) | ✅ Done |
| DOCX parser (python-docx, paragraphs) | ✅ Done |
| XLSX parser (openpyxl, cell text) | ✅ Done |
| Unknown/fallback parser (UTF-8, binary detection) | ✅ Done |
| Chunker: paragraph-boundary-aware, overlapping | ✅ Done |
| parse_and_chunk_source_document orchestrator | ✅ Done |
| POST /admin/parsing/source-documents/{id}/parse | ✅ Done |
| GET /admin/parsing/parsed-documents | ✅ Done |
| GET /admin/parsing/parsed-documents/{id} | ✅ Done |
| GET /admin/parsing/parsed-documents/{id}/chunks | ✅ Done |
| 49 new unit tests | ✅ Done |
| docs/parsing-and-chunking.md | ✅ Done |

Phase 7 constraints:
- No embeddings or pgvector columns yet
- No OCR; no external resource fetching from documents
- Raw bytes remain in MinIO only; full text not in audit logs
- Parser safety: documents never executed, no macros run

### Phase 8 — Embeddings + pgvector Foundation ✅

| Component | Status |
|---|---|
| pgvector extension enabled via Alembic migration 0005 | ✅ Done |
| `ChunkEmbedding` model + migration | ✅ Done |
| `EmbeddingProvider` protocol | ✅ Done |
| Fake deterministic local provider (no external calls) | ✅ Done |
| Provider factory (fake-local only; real providers are future work) | ✅ Done |
| `embed_chunks_for_index_version` orchestrator | ✅ Done |
| POST /admin/embeddings/generate | ✅ Done |
| GET /admin/embeddings | ✅ Done |
| POST /admin/embeddings/search (cosine distance, pgvector) | ✅ Done |
| 39 new unit tests | ✅ Done |
| docs/embeddings.md | ✅ Done |

**Constraints enforced:**
- Only `building` index versions accept embeddings
- Duplicate embeddings skipped (chunk + model + hash + version)
- `DocumentChunk` rows are never mutated
- Audit metadata contains counts only — no chunk text
- No external embedding API calls — fake-local only in MVP
- Raw embedding vectors not returned in list API
- All authorization server-side (knowledge_admin, system_admin)

### Phase 9 — Retrieval Foundation ✅

| Component | Status |
|---|---|
| `context_type` added to `KnowledgeSource` (migration 0006) | ✅ Done |
| `retrieve_chunks` service (pgvector cosine distance, 5-table join) | ✅ Done |
| `build_citation_metadata` helper | ✅ Done |
| `RetrievedChunk` dataclass with citation metadata | ✅ Done |
| Context filtering (matching + null/general sources) | ✅ Done |
| Authority tie-breaker ordering (lower = stronger) | ✅ Done |
| POST /admin/retrieval/search (admin/debug only) | ✅ Done |
| GET /admin/retrieval/health | ✅ Done |
| Knowledge Sources API updated with context_type | ✅ Done |
| 30 new unit tests | ✅ Done |
| docs/retrieval.md | ✅ Done |

**Constraints enforced:**
- Retrieval admin/debug only — not exposed to chat users
- query_text never stored in audit metadata or logs
- No LLM calls, no OpenRouter, no external service calls
- Uses fake-local embeddings (not semantically meaningful in MVP)
- All authorization server-side (knowledge_admin, system_admin)
- Context filter includes matching type + null/general sources

### Phase 10 — Pending

Real embedding provider via LLM Gateway with privacy guard, RAG answer generation with citations, chat endpoint with streaming, OpenRouter integration, frontend UI, SSO.
