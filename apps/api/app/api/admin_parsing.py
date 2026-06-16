import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.document_chunk import DocumentChunk
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
from app.db.models.user import User
from app.db.session import get_db
from app.services.parsing.base import CURRENT_PARSER_VERSION
from app.services.parsing.orchestrator import parse_and_chunk_source_document

router = APIRouter(prefix="/admin/parsing", tags=["parsing"])

_PARSING_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

ParseStatus = Literal["parsed", "failed"]


# ── Request / Response models ─────────────────────────────────────────────────

class ParseRequest(BaseModel):
    parser_version: str = CURRENT_PARSER_VERSION


class ParsedDocumentSummary(BaseModel):
    id: str
    source_document_id: str
    parser_name: str
    parser_version: str
    text_hash: str
    language: str | None
    parse_status: str
    error_message: str | None
    chunk_count: int | None = None
    created_at: str | None
    updated_at: str | None


class ParsedDocumentDetail(ParsedDocumentSummary):
    metadata_json: dict | None = None


class ChunkResponse(BaseModel):
    id: str
    parsed_document_id: str
    source_document_id: str
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    section_title: str | None
    page_number: int | None
    token_estimate: int | None
    created_at: str | None


def _to_summary(pd: ParsedDocument, chunk_count: int | None = None) -> ParsedDocumentSummary:
    return ParsedDocumentSummary(
        id=str(pd.id),
        source_document_id=str(pd.source_document_id),
        parser_name=pd.parser_name,
        parser_version=pd.parser_version,
        text_hash=pd.text_hash,
        language=pd.language,
        parse_status=pd.parse_status,
        error_message=pd.error_message,
        chunk_count=chunk_count,
        created_at=pd.created_at.isoformat() if pd.created_at else None,
        updated_at=pd.updated_at.isoformat() if pd.updated_at else None,
    )


def _to_detail(pd: ParsedDocument, chunk_count: int | None = None) -> ParsedDocumentDetail:
    return ParsedDocumentDetail(
        id=str(pd.id),
        source_document_id=str(pd.source_document_id),
        parser_name=pd.parser_name,
        parser_version=pd.parser_version,
        text_hash=pd.text_hash,
        language=pd.language,
        parse_status=pd.parse_status,
        error_message=pd.error_message,
        chunk_count=chunk_count,
        metadata_json=pd.metadata_json,
        created_at=pd.created_at.isoformat() if pd.created_at else None,
        updated_at=pd.updated_at.isoformat() if pd.updated_at else None,
    )


# ── POST /admin/parsing/source-documents/{source_document_id}/parse ───────────

@router.post(
    "/source-documents/{source_document_id}/parse",
    status_code=status.HTTP_201_CREATED,
    response_model=ParsedDocumentDetail,
)
async def parse_source_document(
    source_document_id: uuid.UUID,
    body: ParseRequest = ParseRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_PARSING_ROLES)),
):
    source_doc = await db.get(SourceDocument, source_document_id)
    if not source_doc:
        raise HTTPException(status_code=404, detail="Source document not found")

    if source_doc.status not in ("downloaded", "unchanged"):
        raise HTTPException(
            status_code=409,
            detail=f"Source document status is '{source_doc.status}' — must be 'downloaded' or 'unchanged'",
        )
    if not source_doc.storage_bucket or not source_doc.storage_object_key:
        raise HTTPException(
            status_code=409,
            detail="Source document has no MinIO storage reference",
        )

    try:
        parsed_doc = await parse_and_chunk_source_document(
            db=db,
            source_document_id=source_document_id,
            parser_version=body.parser_version,
            started_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    chunk_result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.parsed_document_id == parsed_doc.id)
    )
    chunk_count = len(chunk_result.scalars().all())

    return _to_detail(parsed_doc, chunk_count=chunk_count)


# ── GET /admin/parsing/parsed-documents ──────────────────────────────────────

@router.get("/parsed-documents", response_model=list[ParsedDocumentSummary])
async def list_parsed_documents(
    source_document_id: uuid.UUID | None = Query(default=None),
    parse_status: ParseStatus | None = Query(default=None),
    parser_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_PARSING_ROLES)),
):
    q = select(ParsedDocument)
    if source_document_id is not None:
        q = q.where(ParsedDocument.source_document_id == source_document_id)
    if parse_status is not None:
        q = q.where(ParsedDocument.parse_status == parse_status)
    if parser_name is not None:
        q = q.where(ParsedDocument.parser_name == parser_name)
    result = await db.execute(q)
    return [_to_summary(pd) for pd in result.scalars().all()]


# ── GET /admin/parsing/parsed-documents/{parsed_document_id} ─────────────────

@router.get("/parsed-documents/{parsed_document_id}", response_model=ParsedDocumentDetail)
async def get_parsed_document(
    parsed_document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_PARSING_ROLES)),
):
    pd = await db.get(ParsedDocument, parsed_document_id)
    if not pd:
        raise HTTPException(status_code=404, detail="Parsed document not found")

    chunk_result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.parsed_document_id == parsed_document_id)
    )
    chunk_count = len(chunk_result.scalars().all())
    return _to_detail(pd, chunk_count=chunk_count)


# ── GET /admin/parsing/parsed-documents/{parsed_document_id}/chunks ───────────

@router.get(
    "/parsed-documents/{parsed_document_id}/chunks",
    response_model=list[ChunkResponse],
)
async def list_document_chunks(
    parsed_document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_PARSING_ROLES)),
):
    pd = await db.get(ParsedDocument, parsed_document_id)
    if not pd:
        raise HTTPException(status_code=404, detail="Parsed document not found")

    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.parsed_document_id == parsed_document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = result.scalars().all()
    return [
        ChunkResponse(
            id=str(c.id),
            parsed_document_id=str(c.parsed_document_id),
            source_document_id=str(c.source_document_id),
            chunk_index=c.chunk_index,
            chunk_text=c.chunk_text,
            chunk_hash=c.chunk_hash,
            section_title=c.section_title,
            page_number=c.page_number,
            token_estimate=c.token_estimate,
            created_at=c.created_at.isoformat() if c.created_at else None,
        )
        for c in chunks
    ]
