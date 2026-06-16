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

### Phase 1 — Runnable Skeleton (current)

| Component | Status |
|---|---|
| `docker-compose.yml` (api, web, postgres, redis, minio) | ✅ Done |
| FastAPI app with `/health` and `/ready` endpoints | ✅ Done |
| Next.js app with home page and API health display | ✅ Done |
| Unit test for `/health` | ✅ Done |

### Phase 2 — Pending

Authentication, RBAC, chat endpoint, FAQ management, RAG pipeline, LLM Gateway, audit log, privacy guard.
