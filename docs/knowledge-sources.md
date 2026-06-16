# Knowledge Sources — Backend API

## Purpose

Knowledge sources represent the authoritative content repositories that the RAG pipeline will crawl, index, and retrieve from. Managing sources is a prerequisite for building index versions.

## Authority Hierarchy

All knowledge sources carry an `authority_level` integer that determines how answers from this source rank against others. Lower numbers mean higher authority.

| Level | Description |
|---|---|
| 1 | Salary agreements / תקשי״ר (Civil Service Regulations) |
| 2 | Commissioner guidelines / official circulars / binding procedures |
| 3 | Policy documents / implementation guidelines / helper documents |
| 4 | Approved FAQ items |
| 5 | General explanatory documents |

**Rule:** The RAG pipeline must never present a lower-authority answer as overriding a higher-authority source. This hierarchy is enforced at the authority ranking stage of retrieval (not yet implemented).

## Roles Allowed

| Role | Access |
|---|---|
| `knowledge_admin` | Full access to create, update, deactivate, activate knowledge sources |
| `system_admin` | Full access |
| `chat_user` | No access |
| `user_admin` | No access unless also `knowledge_admin` or `system_admin` |
| `faq_manager` | No access unless also `knowledge_admin` or `system_admin` |

All authorization checks are enforced server-side.

## API Endpoints

All endpoints require `knowledge_admin` or `system_admin` role.

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/knowledge-sources` | List all sources. Optional filters: `is_active`, `authority_level`, `source_type` |
| `POST` | `/admin/knowledge-sources` | Create a new knowledge source |
| `PATCH` | `/admin/knowledge-sources/{id}` | Update source fields |
| `PATCH` | `/admin/knowledge-sources/{id}/deactivate` | Set `is_active=false` |
| `PATCH` | `/admin/knowledge-sources/{id}/activate` | Set `is_active=true` |

### Create Request Body

```json
{
  "name": "תקשי\"ר — Civil Service Regulations",
  "source_type": "civil_service_regulations",
  "url": "https://example.gov.il/takshir",
  "authority_level": 1,
  "is_active": true
}
```

### Validation

- `name` must not be empty or whitespace-only.
- `source_type` must not be empty or whitespace-only.
- `authority_level` must be an integer between 1 and 5 (inclusive). Values outside this range return 422.
- `url` is optional. No URL format validation is currently applied beyond basic string type.
- `is_active` defaults to `true` on create.

### Response Fields

```json
{
  "id": "uuid",
  "name": "...",
  "source_type": "...",
  "url": null,
  "authority_level": 1,
  "is_active": true,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

## Audit Actions

| Action | Trigger |
|---|---|
| `knowledge_source_created` | POST /admin/knowledge-sources |
| `knowledge_source_updated` | PATCH /admin/knowledge-sources/{id} |
| `knowledge_source_deactivated` | PATCH /admin/knowledge-sources/{id}/deactivate |
| `knowledge_source_activated` | PATCH /admin/knowledge-sources/{id}/activate |

## Current Limitations

- No crawler implementation yet — sources are registered but not crawled.
- No document downloading yet.
- No embeddings or vector indexing yet.
- `url` format is not currently validated beyond string type.
- No bulk import/export.
