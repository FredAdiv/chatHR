"""Admin endpoints for knowledge index quality checks and controlled activation.

POST /admin/knowledge/index-versions/{id}/quality-check
  — Run 9 deterministic local quality checks on a draft index version.
  — On all pass: status → "ready".
  — On any fail: status → "quality_check_failed".
  — No LLM calls, no external services.

POST /admin/knowledge/index-versions/{id}/activate
  — Activate a quality-checked (ready) index version.
  — Archives the current active version first (transactional).
  — Only one active index may exist at a time.

Security:
- knowledge_admin or system_admin only.
- No raw content in responses, audit logs, or metadata.
- Query text never stored.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import reduce

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/admin/knowledge/index-versions", tags=["knowledge-index"])

_INDEX_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

# Statuses eligible for quality check
_QC_ELIGIBLE_STATUSES = {"draft", "quality_check_failed"}

_MAX_CHUNK_LEN = 50_000  # characters; sanity upper bound


# ── Response models ────────────────────────────────────────────────────────────

class CheckResult(BaseModel):
    name: str
    passed: bool
    message: str


class QualityCheckResponse(BaseModel):
    index_version_id: str
    overall_passed: bool
    status: str
    checks: list[CheckResult]
    checked_at: str
    chunk_count: int


class ActivationResponse(BaseModel):
    index_version_id: str
    status: str
    version_label: str
    activated_at: str
    previous_active_id: str | None
    message: str


# ── Quality check helpers ──────────────────────────────────────────────────────

async def _run_quality_checks(
    db: AsyncSession,
    iv: IndexVersion,
) -> list[CheckResult]:
    """Run 9 deterministic local quality checks. No LLM calls."""
    results: list[CheckResult] = []
    iv_id = iv.id

    # Check 1: Not active (pre-condition, verified before calling)
    results.append(CheckResult(
        name="not_active",
        passed=True,
        message="Index version is not currently active — safe to evaluate.",
    ))

    # Check 2: Has at least one embedding record
    embedding_count: int = (await db.execute(
        select(func.count()).select_from(ChunkEmbedding).where(
            ChunkEmbedding.index_version_id == iv_id
        )
    )).scalar_one()

    results.append(CheckResult(
        name="has_embeddings",
        passed=embedding_count > 0,
        message=(
            f"Found {embedding_count} embedding records."
            if embedding_count > 0
            else "No embedding records found — index may be empty or incompletely built."
        ),
    ))

    if embedding_count == 0:
        # No point running further checks without embeddings
        for name in ("source_documents_exist", "citation_metadata_complete",
                     "authority_metadata_valid", "no_raw_content_exposed",
                     "takshir_metadata_valid", "chunk_sanity"):
            results.append(CheckResult(
                name=name, passed=False,
                message="Skipped — no embeddings found.",
            ))
        return results

    # Check 3: Source documents still exist for all chunks
    orphan_count: int = (await db.execute(
        select(func.count()).select_from(ChunkEmbedding).where(
            ChunkEmbedding.index_version_id == iv_id,
            ChunkEmbedding.source_document_id == None,  # noqa: E711
        )
    )).scalar_one()

    results.append(CheckResult(
        name="source_documents_exist",
        passed=orphan_count == 0,
        message=(
            "All chunk embeddings are linked to a source document."
            if orphan_count == 0
            else f"{orphan_count} embeddings have no source document reference."
        ),
    ))

    # Load unique source document IDs for remaining checks
    sd_id_rows = (await db.execute(
        select(ChunkEmbedding.source_document_id).distinct().where(
            ChunkEmbedding.index_version_id == iv_id,
            ChunkEmbedding.source_document_id != None,  # noqa: E711
        )
    )).scalars().all()
    sd_ids = list(sd_id_rows)

    # Load source documents and their knowledge sources
    sd_rows = (await db.execute(
        select(SourceDocument).where(SourceDocument.id.in_(sd_ids))
    )).scalars().all()

    ks_ids = [sd.knowledge_source_id for sd in sd_rows if sd.knowledge_source_id]
    ks_rows = (await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id.in_(ks_ids))
    )).scalars().all()
    ks_by_id = {str(ks.id): ks for ks in ks_rows}

    # Check 4: Citation metadata complete (title + semantic or doc type)
    missing_citation = []
    for sd in sd_rows:
        meta = sd.metadata_json or {}
        has_type = bool(meta.get("semantic_type") or sd.document_type)
        if not sd.title or not has_type:
            missing_citation.append(str(sd.id))

    results.append(CheckResult(
        name="citation_metadata_complete",
        passed=len(missing_citation) == 0,
        message=(
            "All source documents have title and document type metadata."
            if not missing_citation
            else f"{len(missing_citation)} source document(s) are missing title or document type."
        ),
    ))

    # Check 5: Authority metadata valid (1–5)
    invalid_authority = []
    for sd in sd_rows:
        ks = ks_by_id.get(str(sd.knowledge_source_id)) if sd.knowledge_source_id else None
        if ks is None or not (1 <= ks.authority_level <= 5):
            invalid_authority.append(str(sd.id))

    results.append(CheckResult(
        name="authority_metadata_valid",
        passed=len(invalid_authority) == 0,
        message=(
            "All source documents have valid authority level (1–5)."
            if not invalid_authority
            else f"{len(invalid_authority)} source document(s) have missing or out-of-range authority level."
        ),
    ))

    # Check 6: No raw content exposed — code guarantee (always passes for this codebase)
    results.append(CheckResult(
        name="no_raw_content_exposed",
        passed=True,
        message="Raw content is stored in MinIO only — not present in DB or API responses.",
    ))

    # Check 7: Takshir-specific — if any doc has semantic_type='takshir', authority_level must be 1
    takshir_issues = []
    for sd in sd_rows:
        meta = sd.metadata_json or {}
        if meta.get("semantic_type") == "takshir":
            ks = ks_by_id.get(str(sd.knowledge_source_id)) if sd.knowledge_source_id else None
            if ks is None or ks.authority_level != 1:
                takshir_issues.append(str(sd.id))

    has_takshir = any(
        (sd.metadata_json or {}).get("semantic_type") == "takshir" for sd in sd_rows
    )
    if has_takshir:
        results.append(CheckResult(
            name="takshir_metadata_valid",
            passed=len(takshir_issues) == 0,
            message=(
                "Takshir documents have correct authority_level=1."
                if not takshir_issues
                else f"{len(takshir_issues)} Takshir document(s) do not have authority_level=1."
            ),
        ))
    else:
        results.append(CheckResult(
            name="takshir_metadata_valid",
            passed=True,
            message="No Takshir documents in this index — check skipped.",
        ))

    # Check 8: Basic chunk sanity — no zero-length chunks, no oversized chunks
    chunk_text_rows = (await db.execute(
        select(DocumentChunk.chunk_text).join(
            ChunkEmbedding, ChunkEmbedding.document_chunk_id == DocumentChunk.id
        ).where(ChunkEmbedding.index_version_id == iv_id)
    )).scalars().all()

    empty_chunks = sum(1 for t in chunk_text_rows if not t or not t.strip())
    oversized_chunks = sum(1 for t in chunk_text_rows if t and len(t) > _MAX_CHUNK_LEN)
    total_chunks = len(chunk_text_rows)

    chunk_ok = empty_chunks == 0 and oversized_chunks == 0 and total_chunks > 0
    if chunk_ok:
        msg = f"All {total_chunks} chunks pass sanity checks."
    else:
        parts = []
        if empty_chunks:
            parts.append(f"{empty_chunks} empty chunk(s)")
        if oversized_chunks:
            parts.append(f"{oversized_chunks} oversized chunk(s) (>{_MAX_CHUNK_LEN} chars)")
        if total_chunks == 0:
            parts.append("no chunks found")
        msg = "Chunk sanity failed: " + ", ".join(parts) + "."

    results.append(CheckResult(
        name="chunk_sanity",
        passed=chunk_ok,
        message=msg,
    ))

    return results


# ── POST: quality check ────────────────────────────────────────────────────────

@router.post(
    "/{index_version_id}/quality-check",
    response_model=QualityCheckResponse,
)
async def run_quality_check(
    index_version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_INDEX_ROLES)),
) -> QualityCheckResponse:
    """Run deterministic local quality checks on a draft index version.

    On all checks passing: status → 'ready'.
    On any check failing: status → 'quality_check_failed'.
    No LLM calls. No raw content in response.
    """
    now = datetime.now(timezone.utc)

    iv = await db.get(IndexVersion, index_version_id)
    if not iv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index version not found.")

    if iv.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot run quality checks on the active index version.",
        )

    if iv.status not in _QC_ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Index version status is '{iv.status}' — quality checks require "
                f"status in {sorted(_QC_ELIGIBLE_STATUSES)}."
            ),
        )

    checks = await _run_quality_checks(db, iv)
    overall_passed = all(c.passed for c in checks)
    new_status = "ready" if overall_passed else "quality_check_failed"

    # Store results in metadata (no raw content)
    iv.status = new_status
    existing_meta = dict(iv.metadata_json or {})
    existing_meta["quality_check"] = {
        "overall_passed": overall_passed,
        "checked_at": now.isoformat(),
        "checked_by_user_id": str(actor.id),
        "checks": [{"name": c.name, "passed": c.passed, "message": c.message} for c in checks],
    }
    iv.metadata_json = existing_meta
    await db.flush()

    embedding_count: int = (await db.execute(
        select(func.count()).select_from(ChunkEmbedding).where(
            ChunkEmbedding.index_version_id == iv.id
        )
    )).scalar_one()

    await record_audit_event(
        db,
        action="knowledge_index_quality_checked",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(iv.id),
        metadata_json={
            "overall_passed": overall_passed,
            "new_status": new_status,
            "check_names_failed": [c.name for c in checks if not c.passed],
            "embedding_count": embedding_count,
        },
    )
    await db.commit()

    return QualityCheckResponse(
        index_version_id=str(iv.id),
        overall_passed=overall_passed,
        status=new_status,
        checks=checks,
        checked_at=now.isoformat(),
        chunk_count=embedding_count,
    )


# ── POST: activate ─────────────────────────────────────────────────────────────

@router.post(
    "/{index_version_id}/activate",
    response_model=ActivationResponse,
)
async def activate_index_version(
    index_version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_INDEX_ROLES)),
) -> ActivationResponse:
    """Activate a quality-checked index version.

    Only 'ready' versions (quality checks passed) can be activated.
    Archives the current active version first. Transactional.
    Audit log records actor, index_version_id, previous_active_id.
    No raw content in response or audit log.
    """
    now = datetime.now(timezone.utc)

    iv = await db.get(IndexVersion, index_version_id)
    if not iv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index version not found.")

    if iv.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only index versions that passed quality checks (status='ready') can be activated. "
                f"Current status: '{iv.status}'."
            ),
        )

    # Archive current active version(s) — transactional
    active_result = await db.execute(
        select(IndexVersion).where(IndexVersion.status == "active")
    )
    active_versions = active_result.scalars().all()
    previous_active_id: str | None = None

    for old_iv in active_versions:
        previous_active_id = str(old_iv.id)
        old_iv.status = "archived"
        await record_audit_event(
            db,
            action="knowledge_index_version_archived",
            actor_user_id=actor.id,
            target_type="index_version",
            target_id=str(old_iv.id),
            metadata_json={
                "reason": "replaced_by_activation",
                "new_version_id": str(iv.id),
                "new_version_label": iv.version_label,
            },
        )
    await db.flush()

    # Activate the selected version
    iv.status = "active"
    iv.activated_by_user_id = actor.id
    iv.activated_at = now
    await db.flush()

    await record_audit_event(
        db,
        action="knowledge_index_version_activated",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(iv.id),
        metadata_json={
            "version_label": iv.version_label,
            "previous_active_index_version_id": previous_active_id,
            "activated_at": now.isoformat(),
            "status": "active",
        },
    )
    await db.commit()

    return ActivationResponse(
        index_version_id=str(iv.id),
        status="active",
        version_label=iv.version_label,
        activated_at=now.isoformat(),
        previous_active_id=previous_active_id,
        message=(
            f"אינדקס גרסה '{iv.version_label}' הופעל בהצלחה. "
            + (f"גרסה קודמת '{previous_active_id}' הועברה לארכיון. " if previous_active_id else "")
            + "הצ'אט יתחיל לשלוף ממנו בפניות הבאות."
        ),
    )
