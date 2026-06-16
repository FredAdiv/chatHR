# FAQ Management — Backend API

## Purpose

The FAQ management API allows authorized HR staff to create, approve, archive, and manage frequently asked questions. Approved FAQs are intended for future use as a high-quality seed layer in the RAG retrieval pipeline, supplementing official document sources.

## Roles Allowed

| Role | Access |
|---|---|
| `faq_manager` | Create, update, approve, archive FAQ items |
| `system_admin` | All of the above |
| `chat_user` | No access to FAQ admin endpoints |
| `user_admin` | No access unless also `faq_manager` or `system_admin` |

All authorization checks are enforced server-side. Client-side display of role information must not be used to gate access.

## FAQ Lifecycle

```
draft → approved → archived
  ↑___________|
  (edit approved → back to draft)
```

| Status | Description |
|---|---|
| `draft` | Newly created or returned from approved after edit |
| `approved` | Reviewed and approved by an authorized user |
| `archived` | No longer active; cannot be edited |

### Rules

- New FAQ items are always created as `draft`. Clients cannot set `status` on create.
- Editing a `draft` FAQ increments `content_version` if content fields change.
- Editing an `approved` FAQ sets status back to `draft`, clears `approved_by_user_id` and `approved_at`, and increments `content_version`.
- `archived` FAQ items cannot be edited.

## Authority Limitation

**Approved FAQ does not override official sources.** FAQ approval means the answer has been reviewed internally — it does not grant the FAQ higher legal authority than:
- תקשי״ר (Civil Service Regulations)
- Salary agreements and collective bargaining agreements
- Official binding circulars and regulations

The RAG pipeline (when implemented) must enforce the authority hierarchy and never present FAQ answers as superseding official binding sources.

## API Endpoints

All endpoints require `faq_manager` or `system_admin` role.

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/faq` | List FAQ items. Optional filters: `status`, `context_type`, `topic` |
| `POST` | `/admin/faq` | Create FAQ in draft status |
| `PATCH` | `/admin/faq/{id}` | Update draft or approved FAQ (approved → draft) |
| `PATCH` | `/admin/faq/{id}/approve` | Approve FAQ item |
| `PATCH` | `/admin/faq/{id}/archive` | Archive FAQ item |

### Create Request Body

```json
{
  "question": "Can I transfer to another ministry?",
  "answer": "Yes, subject to approval from both ministries.",
  "topic": "mobility",
  "context_type": "government_ministries",
  "applicable_population": null,
  "official_source_links": ["https://example.gov.il/source"]
}
```

`context_type` must be one of: `government_ministries`, `defense_system`, `health_system`, or `null`.

### Response Fields

```json
{
  "id": "uuid",
  "question": "...",
  "answer": "...",
  "topic": null,
  "context_type": null,
  "applicable_population": null,
  "official_source_links": [],
  "status": "draft",
  "approved_by_user_id": null,
  "approved_at": null,
  "content_version": 1,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

## Audit Actions

| Action | Trigger |
|---|---|
| `faq_created` | POST /admin/faq |
| `faq_updated` | PATCH /admin/faq/{id} |
| `faq_approved` | PATCH /admin/faq/{id}/approve |
| `faq_archived` | PATCH /admin/faq/{id}/archive |

All audit events record `actor_user_id` and `target_id`.

## Current Limitations

- FAQ items are **not yet connected to the RAG retrieval pipeline** — they exist in the database but are not indexed for embedding or search.
- No frontend FAQ management UI yet.
- No bulk import/export.
- `context_type` is validated by a DB check constraint but not validated in the API layer (will cause a DB error if invalid).
