import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.ingestion_run import IngestionRun
from app.db.models.ingestion_run_document import IngestionRunDocument
from app.db.models.source_document import SourceDocument
from app.db.models.user import User
from app.db.session import get_db
from app.services.ingestion.orchestrator import run_ingestion_for_source

router = APIRouter(prefix="/admin/ingestion", tags=["ingestion"])

_INGESTION_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

IngestionMode = Literal["dry_run", "metadata_only", "download"]
IngestionRunStatus = Literal["pending", "running", "completed", "failed"]
SourceDocumentStatus = Literal["discovered", "downloaded", "unchanged", "failed", "deleted"]


# ── Request / Response models ─────────────────────────────────────────────────

class StartIngestionRunRequest(BaseModel):
    knowledge_source_id: uuid.UUID
    mode: IngestionMode
    index_version_id: uuid.UUID | None = None


class IngestionRunDocumentResponse(BaseModel):
    id: str
    ingestion_run_id: str
    source_document_id: str | None
    url: str
    action: str
    error_message: str | None
    metadata_json: dict | None
    created_at: str | None


class IngestionRunResponse(BaseModel):
    id: str
    index_version_id: str | None
    started_by_user_id: str | None
    status: str
    mode: str
    started_at: str | None
    completed_at: str | None
    summary_json: dict | None
    error_message: str | None
    run_documents: list[IngestionRunDocumentResponse] | None = None


class SourceDocumentResponse(BaseModel):
    id: str
    knowledge_source_id: str
    url: str
    title: str | None
    document_type: str | None
    source_etag: str | None
    source_last_modified: str | None
    content_hash: str | None
    storage_bucket: str | None
    storage_object_key: str | None
    status: str
    first_seen_at: str | None
    last_seen_at: str | None
    downloaded_at: str | None
    created_at: str | None
    updated_at: str | None


# ── Serialization helpers ─────────────────────────────────────────────────────

def _run_doc_dict(rd: IngestionRunDocument) -> dict:
    return {
        "id": str(rd.id),
        "ingestion_run_id": str(rd.ingestion_run_id),
        "source_document_id": str(rd.source_document_id) if rd.source_document_id else None,
        "url": rd.url,
        "action": rd.action,
        "error_message": rd.error_message,
        "metadata_json": rd.metadata_json,
        "created_at": rd.created_at.isoformat() if rd.created_at else None,
    }


def _run_dict(run: IngestionRun, run_docs: list[IngestionRunDocument] | None = None) -> dict:
    d = {
        "id": str(run.id),
        "index_version_id": str(run.index_version_id) if run.index_version_id else None,
        "started_by_user_id": str(run.started_by_user_id) if run.started_by_user_id else None,
        "status": run.status,
        "mode": run.mode,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "summary_json": run.summary_json,
        "error_message": run.error_message,
        "run_documents": None,
    }
    if run_docs is not None:
        d["run_documents"] = [_run_doc_dict(rd) for rd in run_docs]
    return d


def _source_doc_dict(sd: SourceDocument) -> dict:
    return {
        "id": str(sd.id),
        "knowledge_source_id": str(sd.knowledge_source_id),
        "url": sd.url,
        "title": sd.title,
        "document_type": sd.document_type,
        "source_etag": sd.source_etag,
        "source_last_modified": sd.source_last_modified,
        "content_hash": sd.content_hash,
        "storage_bucket": sd.storage_bucket,
        "storage_object_key": sd.storage_object_key,
        "status": sd.status,
        "first_seen_at": sd.first_seen_at.isoformat() if sd.first_seen_at else None,
        "last_seen_at": sd.last_seen_at.isoformat() if sd.last_seen_at else None,
        "downloaded_at": sd.downloaded_at.isoformat() if sd.downloaded_at else None,
        "created_at": sd.created_at.isoformat() if sd.created_at else None,
        "updated_at": sd.updated_at.isoformat() if sd.updated_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/runs", status_code=status.HTTP_201_CREATED, response_model=IngestionRunResponse)
async def start_ingestion_run(
    req: StartIngestionRunRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_INGESTION_ROLES)),
):
    """
    Start an ingestion run for a knowledge source.
    Runs synchronously in MVP — returns the completed run summary.
    """
    try:
        run = await run_ingestion_for_source(
            db=db,
            source_id=req.knowledge_source_id,
            mode=req.mode,
            started_by_user_id=actor.id,
            index_version_id=req.index_version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _run_dict(run)


@router.get("/runs", response_model=list[IngestionRunResponse])
async def list_ingestion_runs(
    run_status: IngestionRunStatus | None = Query(default=None, alias="status"),
    mode: IngestionMode | None = Query(default=None),
    index_version_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_INGESTION_ROLES)),
):
    """List ingestion runs with optional filters."""
    q = select(IngestionRun)
    if run_status:
        q = q.where(IngestionRun.status == run_status)
    if mode:
        q = q.where(IngestionRun.mode == mode)
    if index_version_id:
        q = q.where(IngestionRun.index_version_id == index_version_id)
    result = await db.execute(q)
    return [_run_dict(r) for r in result.scalars().all()]


@router.get("/runs/{run_id}", response_model=IngestionRunResponse)
async def get_ingestion_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_INGESTION_ROLES)),
):
    """Return a single ingestion run with its processed document entries."""
    run = await db.get(IngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
    result = await db.execute(
        select(IngestionRunDocument).where(IngestionRunDocument.ingestion_run_id == run_id)
    )
    run_docs = list(result.scalars().all())
    return _run_dict(run, run_docs)


@router.get("/source-documents", response_model=list[SourceDocumentResponse])
async def list_source_documents(
    knowledge_source_id: uuid.UUID | None = Query(default=None),
    doc_status: SourceDocumentStatus | None = Query(default=None, alias="status"),
    document_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_INGESTION_ROLES)),
):
    """List source documents with optional filters."""
    q = select(SourceDocument)
    if knowledge_source_id:
        q = q.where(SourceDocument.knowledge_source_id == knowledge_source_id)
    if doc_status:
        q = q.where(SourceDocument.status == doc_status)
    if document_type:
        q = q.where(SourceDocument.document_type == document_type)
    result = await db.execute(q)
    return [_source_doc_dict(sd) for sd in result.scalars().all()]
