# Ingestion Foundation — Backend

## Purpose

The ingestion foundation provides the database schema, service layer, and admin API for controlled document ingestion from knowledge sources. It enables discovery and download of source documents, content change detection, and MinIO storage — without recursive crawling, text parsing, chunking, or embeddings (those are future phases).

## Ingestion Modes

| Mode | Description |
|---|---|
| `dry_run` | Validates the source and records a run + one run-document without fetching any URL. Useful for testing plumbing. |
| `metadata_only` | Fetches HTTP headers (GET request). Discovers/updates `SourceDocument` records. Does not store content bytes in MinIO. |
| `download` | Fetches full content. Computes SHA-256 hash. Stores changed content in MinIO. Records action as `downloaded` or `unchanged`. |

## Change Detection

Content change is detected by comparing the SHA-256 hex digest of the fetched response body against the stored `content_hash` on the `SourceDocument`.

If the hash matches the existing record → action: `unchanged`, no MinIO write.
If the hash differs (or no record exists) → action: `downloaded`, content stored in MinIO.

## Raw Content Storage

**Raw document bytes are stored only in MinIO — never in the database or audit logs.**

| Storage type | What is stored |
|---|---|
| Database (`source_documents`) | Metadata: URL, type, hash, bucket/key, status, timestamps |
| MinIO (`chathr-documents` bucket) | Raw document bytes (HTML, PDF, DOCX, XLSX) |
| Audit log | Mode, source ID, run status — no content, no PII, no tokens |

## URL Safety Rules

The ingestion service enforces the following rules before fetching any URL:

- Only `http` and `https` schemes are allowed.
- `file://`, `ftp://`, `javascript:`, `data:` and other schemes are rejected.
- Private and localhost addresses are rejected: `localhost`, `127.x.x.x`, `10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`.
- Empty URLs are rejected.

## Max Response Size

The downloader limits each response to **20 MB**. Responses exceeding this limit return an error result and the ingestion run document is marked `failed`. This limit prevents memory exhaustion from unexpectedly large files.

## Relationship to IndexVersion

An `IngestionRun` may optionally reference an `IndexVersion` via `index_version_id`. In future phases, ingestion runs will feed into the index build pipeline:

1. Download/update source documents (this phase)
2. Parse and chunk document text (future)
3. Create embeddings (future)
4. Store in pgvector index version (future)
5. Activate index version for RAG retrieval (future)

## Current Limitations

- MVP processes only the knowledge source's root URL — no recursive link crawling.
- No document text parsing, chunking, or embeddings yet.
- Ingestion runs synchronously in the API call (no async task queue yet).
- Quality checks for ingested content are not implemented yet.
- No rollback or re-ingestion UI.

## Database Tables

### `source_documents`

Tracks each discovered document URL from a knowledge source.

| Field | Description |
|---|---|
| `id` | UUID primary key |
| `knowledge_source_id` | FK → `knowledge_sources.id` |
| `url` | Document URL (unique per source) |
| `title` | Optional document title |
| `document_type` | `html`, `pdf`, `docx`, `xlsx`, `unknown` |
| `source_etag` | HTTP ETag header for conditional fetching |
| `source_last_modified` | HTTP Last-Modified header |
| `content_hash` | SHA-256 hex digest of last downloaded content |
| `storage_bucket` | MinIO bucket name |
| `storage_object_key` | MinIO object key |
| `status` | `discovered`, `downloaded`, `unchanged`, `failed`, `deleted` |
| `first_seen_at` | Timestamp when first discovered |
| `last_seen_at` | Timestamp when last checked |
| `downloaded_at` | Timestamp when content was last downloaded |
| `metadata_json` | Safe administrative metadata only (no content, no PII) |

### `ingestion_runs`

One record per ingestion run attempt.

| Field | Description |
|---|---|
| `id` | UUID primary key |
| `index_version_id` | Optional FK → `index_versions.id` |
| `started_by_user_id` | FK → `users.id` |
| `status` | `pending`, `running`, `completed`, `failed` |
| `mode` | `dry_run`, `metadata_only`, `download` |
| `started_at` | Run start timestamp |
| `completed_at` | Run end timestamp |
| `summary_json` | Run summary: mode, doc count, action breakdown |
| `error_message` | Top-level error if run itself failed |

### `ingestion_run_documents`

Per-document detail for each run.

| Field | Description |
|---|---|
| `id` | UUID primary key |
| `ingestion_run_id` | FK → `ingestion_runs.id` |
| `source_document_id` | FK → `source_documents.id` (nullable if failed) |
| `url` | URL that was processed |
| `action` | `discovered`, `downloaded`, `unchanged`, `failed`, `skipped` |
| `error_message` | Error detail if action is `failed` |
| `metadata_json` | Safe metadata: document type, content type (no raw content) |

## API Endpoints

All endpoints require `knowledge_admin` or `system_admin` role. All checks server-side.

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/ingestion/runs` | Start an ingestion run |
| `GET` | `/admin/ingestion/runs` | List ingestion runs |
| `GET` | `/admin/ingestion/runs/{run_id}` | Get run with document details |
| `GET` | `/admin/ingestion/source-documents` | List source documents |

### Start Ingestion Run

```json
POST /admin/ingestion/runs
{
  "knowledge_source_id": "uuid",
  "mode": "dry_run",
  "index_version_id": null
}
```

Response includes the completed run summary (synchronous in MVP).

### List Ingestion Runs (filters)

```
GET /admin/ingestion/runs?status=completed&mode=download
```

### List Source Documents (filters)

```
GET /admin/ingestion/source-documents?knowledge_source_id=uuid&status=downloaded&document_type=pdf
```

## Audit Actions

| Action | Trigger |
|---|---|
| `ingestion_run_started` | When a run begins |
| `ingestion_run_completed` | When a run ends (completed or failed) |

Audit metadata includes: `mode`, `knowledge_source_id`, `status`. Never includes raw content, tokens, prompts, PII, or secrets.

## Required Environment Variables

```
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=CHANGE_ME
MINIO_SECRET_KEY=CHANGE_ME
MINIO_BUCKET_DOCUMENTS=chathr-documents
MINIO_SECURE=false
```

See `.env.example` for the full list.

## Security Constraints

- No anonymous access — all endpoints require authentication and correct role.
- All authorization checks are server-side.
- No raw document content in DB, audit logs, or API responses.
- No personal employee data in examples or metadata.
- Private/internal IP addresses are blocked at the URL validation layer.
- MinIO credentials are loaded from environment variables, never from code.
