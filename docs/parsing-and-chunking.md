# Document Parsing and Chunking

## Overview

Phase 7 adds document text extraction and chunking for already-ingested `SourceDocument` records. Raw bytes are fetched from MinIO, parsed to plain text, and split into overlapping chunks for future RAG retrieval.

No embeddings, vector columns, or retrieval logic is included in this phase.

## Supported Document Types

| Type    | Parser         | Notes                                      |
|---------|----------------|---------------------------------------------|
| html    | BeautifulSoup  | Removes script/style; extracts visible text |
| pdf     | pypdf          | Text-layer only; no OCR                     |
| docx    | python-docx    | Paragraphs only; no images or OLE objects   |
| xlsx    | openpyxl       | Cell text; no formulas evaluated            |
| unknown | UTF-8 fallback | Rejects content with null bytes             |

### Parser Safety Constraints

- Documents are never executed.
- No OCR; no image content extracted.
- No external resources referenced by documents are fetched.
- Extracted text is capped at **2 MB** per document; longer text is silently truncated.
- Raw binary bytes are never stored in the DB or audit logs.
- Full document text is never written to logs.

## Database Tables

### `parsed_documents`

| Column              | Type     | Description                              |
|---------------------|----------|------------------------------------------|
| id                  | UUID PK  |                                          |
| source_document_id  | UUID FK  | References `source_documents`            |
| parser_name         | text     | e.g. `html`, `pdf`                       |
| parser_version      | text     | e.g. `1.0`                              |
| text_content        | text     | Extracted plain text (may be large)      |
| text_hash           | text     | SHA-256 of `text_content`               |
| language            | text?    | Detected language (future)               |
| parse_status        | text     | `parsed` or `failed`                     |
| error_message       | text?    | Safe error, max 2000 chars               |
| metadata_json       | jsonb?   | Parser-specific metadata                 |

UniqueConstraint: `(source_document_id, parser_name, parser_version, text_hash)` — prevents duplicate parsing of identical content.

### `document_chunks`

| Column              | Type     | Description                              |
|---------------------|----------|------------------------------------------|
| id                  | UUID PK  |                                          |
| parsed_document_id  | UUID FK  | References `parsed_documents`            |
| source_document_id  | UUID FK  | References `source_documents`            |
| chunk_index         | integer  | Sequential, 0-based                      |
| chunk_text          | text     | Chunk content (for RAG)                  |
| chunk_hash          | text     | SHA-256 of `chunk_text`                  |
| section_title       | text?    | Section heading (future use)             |
| page_number         | integer? | Source page (future use)                 |
| token_estimate      | integer? | Rough estimate: `len(chunk_text) // 4`  |
| metadata_json       | jsonb?   | Chunk-level metadata                     |

UniqueConstraint: `(parsed_document_id, chunk_index)`.

## Chunking Strategy

Function: `chunk_text(text, max_chars=2000, overlap_chars=200)`

- Splits on paragraph boundaries (`\n\n`) by default.
- Oversized paragraphs are hard-split at `max_chars`.
- Consecutive chunks overlap by `overlap_chars` characters for context continuity.
- Empty/whitespace-only input returns no chunks.
- Chunk hashes are deterministic (same text → same hash every time).
- Token estimate: `len(chunk_text) // 4` (approximation).

## Admin API

Base path: `/admin/parsing`
Authorization: `knowledge_admin` or `system_admin` only. All checks server-side.

### POST `/admin/parsing/source-documents/{source_document_id}/parse`

Triggers synchronous parsing and chunking for a downloaded SourceDocument.

- Returns 404 if source document not found.
- Returns 409 if source document status is not `downloaded` or `unchanged`.
- Returns 409 if source document has no MinIO storage reference.
- Returns 201 with `ParsedDocumentDetail` on success.

### GET `/admin/parsing/parsed-documents`

Lists parsed documents. Filters: `source_document_id`, `parse_status` (`parsed`|`failed`), `parser_name`.

### GET `/admin/parsing/parsed-documents/{parsed_document_id}`

Returns parsed document metadata and chunk count. Full `text_content` is included (admin-only endpoint).

### GET `/admin/parsing/parsed-documents/{parsed_document_id}/chunks`

Returns all chunks for a parsed document, ordered by `chunk_index`. Intended for RAG retrieval (admin-only).

## Audit Actions

| Action                       | Description                               |
|------------------------------|-------------------------------------------|
| `document_parse_started`     | Parse was initiated                       |
| `document_parsed_and_chunked`| Parse succeeded; chunks created           |
| `document_parse_failed`      | Parse failed; error stored safely         |

Audit metadata never contains full document text, raw bytes, or PII.

## Current Limitations

- No embeddings or vector search (Phase 8).
- No recursive crawling (MVP: root URL only).
- PDF parsing requires text layer; scanned/image-only PDFs will have empty text.
- Language detection not yet implemented.
- No chunk-level section titles or page numbers for HTML/DOCX.

## Next Steps

Phase 8: Generate embeddings for each `DocumentChunk` using an embedding model via OpenRouter, store in pgvector, and implement similarity retrieval for RAG.
