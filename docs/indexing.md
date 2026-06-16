# Index Versions — Backend API

## Purpose

Index versions represent snapshots of the knowledge base that have been built, quality-checked, and optionally activated for use in RAG retrieval. The index version lifecycle enforces the rule that the active index is never updated directly.

## Index Version Lifecycle

```
building → ready → active
    |          |        |
    ↓          ↓        | (only via activation of newer version)
quality_check_failed  archived ←──────────────────────────────┘
    |
    ↓
 archived
```

| Status | Description |
|---|---|
| `building` | Index is being constructed. No RAG queries use this version. |
| `quality_check_failed` | Indexing run failed quality checks. Cannot be activated. |
| `ready` | Quality checks passed. Can be activated. |
| `active` | Currently serving RAG queries. At most one version is active at any time. |
| `archived` | No longer used. Cannot be activated or edited. |

## Critical Rules

1. **Never update the active index directly.** Every indexing run creates a new version.
2. **Only `ready` versions can be activated.** `building`, `quality_check_failed`, and `archived` versions cannot be activated.
3. **At most one version is `active` at any time.** Activating a `ready` version automatically archives the currently active version.
4. **The active version cannot be archived directly.** To replace the active version, activate a newer `ready` version — this archives the old one automatically.
5. **Quality check failure is represented only by `mark-quality-failed` in MVP.** Real automated quality checks are future work.
6. **Active index uniqueness is enforced in application code only (MVP).** The `activate` endpoint archives any existing active version before setting the new one. Before concurrent indexing or production-scale use, add a DB-level partial unique index (`CREATE UNIQUE INDEX ... WHERE status = 'active'`) or an equivalent locking strategy to prevent race conditions.

## Roles Allowed

| Role | Access |
|---|---|
| `knowledge_admin` | Full access to manage index versions |
| `system_admin` | Full access |
| All other roles | No access |

All authorization checks are enforced server-side.

## API Endpoints

All endpoints require `knowledge_admin` or `system_admin` role.

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/index-versions` | List all versions. Optional filter: `status` |
| `POST` | `/admin/index-versions` | Create new version in `building` status |
| `PATCH` | `/admin/index-versions/{id}/mark-ready` | Transition from `building` → `ready` |
| `PATCH` | `/admin/index-versions/{id}/mark-quality-failed` | Transition to `quality_check_failed` |
| `PATCH` | `/admin/index-versions/{id}/activate` | Transition from `ready` → `active` (archives current active) |
| `PATCH` | `/admin/index-versions/{id}/archive` | Archive a `ready` or `quality_check_failed` version |

### Create Request Body

```json
{
  "version_label": "v1.0-20260616",
  "embedding_model": "text-embedding-ada-002",
  "metadata_json": {"notes": "Initial full index build"}
}
```

- `status` is always set to `building` on create. Clients cannot set a different status.
- `created_by_user_id` is set to the requesting user automatically.
- **`metadata_json` safety:** This field must not contain prompts, secrets, tokens, PII, raw source content, or model outputs. It is intended only for administrative metadata such as build notes, tool versions, or run identifiers.

### Response Fields

```json
{
  "id": "uuid",
  "version_label": "v1.0-20260616",
  "status": "building",
  "embedding_model": "text-embedding-ada-002",
  "created_by_user_id": "uuid",
  "activated_by_user_id": null,
  "created_at": "ISO8601",
  "activated_at": null,
  "metadata_json": null
}
```

## State Transition Rules

| Endpoint | Allowed from | Result | Returns if not allowed |
|---|---|---|---|
| `mark-ready` | `building` | `ready` | 409 |
| `mark-quality-failed` | `building`, `ready` | `quality_check_failed` | 409 if `active` |
| `activate` | `ready` | `active` (previous active → `archived`) | 409 |
| `archive` | `ready`, `quality_check_failed` | `archived` | 409 |

## Audit Actions

| Action | Trigger |
|---|---|
| `index_version_created` | POST /admin/index-versions |
| `index_version_marked_ready` | PATCH …/mark-ready |
| `index_version_quality_failed` | PATCH …/mark-quality-failed |
| `index_version_activated` | PATCH …/activate (records on new active version) |
| `index_version_archived` | PATCH …/archive or auto-archive on activation |

## Relationship to Embeddings

Embeddings are generated for `building` index versions via `POST /admin/embeddings/generate`.  
Chunks can be embedded incrementally; the index version is promoted to `ready` manually.  
See [docs/embeddings.md](embeddings.md) for details.

## Current Limitations

- Quality checks are represented only by `mark-ready` (manual) in MVP. Real automated quality checks are future work.
- No rollback endpoint yet. To roll back: activate a previous `ready` version if one exists.
- IVFFlat/HNSW vector index not yet created (deferred until data volume warrants it).
- RAG retrieval not connected yet — vector search is admin/debug only in MVP.
