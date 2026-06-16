"""Tests for quality-check and activation endpoints.

POST /admin/knowledge/index-versions/{id}/quality-check
POST /admin/knowledge/index-versions/{id}/activate
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.main import app


# ── Helpers ────────────────────────────────────────────────────────────────────

def _user_with_roles(*role_names):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.user_roles = [SimpleNamespace(role=SimpleNamespace(name=r)) for r in role_names]
    return user


def _auth(roles):
    u = _user_with_roles(*roles)
    def _dep():
        return u
    return _dep


def _make_iv(status="draft", version_label=None):
    iv = MagicMock()
    iv.id = uuid.uuid4()
    iv.version_label = version_label or f"test-v-{str(iv.id)[:8]}"
    iv.status = status
    iv.metadata_json = {}
    iv.created_at = datetime.now(timezone.utc)
    iv.activated_at = None
    iv.activated_by_user_id = None
    return iv


def _make_ks(authority_level=1):
    ks = MagicMock()
    ks.id = uuid.uuid4()
    ks.authority_level = authority_level
    return ks


def _make_sd(ks_id, doc_type="pdf", semantic_type="takshir", title="תקשי\"ר", authority_level=1):
    sd = MagicMock()
    sd.id = uuid.uuid4()
    sd.knowledge_source_id = ks_id
    sd.document_type = doc_type
    sd.title = title
    sd.metadata_json = {"semantic_type": semantic_type, "file_format": doc_type}
    return sd


def _db_mock_for_qc(iv, sd_ids=None, ks=None, embedding_count=3, orphan_count=0, chunk_texts=None):
    """Build a DB mock that answers all quality-check queries."""
    sd_ids = sd_ids or []
    chunk_texts = chunk_texts or ["chunk text " * 10 for _ in range(embedding_count)]

    call_index = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        c = call_index[0]
        call_index[0] += 1

        if c == 0:
            # count embeddings
            result.scalar_one.return_value = embedding_count
        elif c == 1:
            # count orphan embeddings
            result.scalar_one.return_value = orphan_count
        elif c == 2:
            # distinct source_document_ids
            result.scalars.return_value.all.return_value = sd_ids
        elif c == 3:
            # source documents
            from app.db.models.source_document import SourceDocument
            if ks:
                sd = _make_sd(ks.id)
                result.scalars.return_value.all.return_value = [sd]
            else:
                result.scalars.return_value.all.return_value = []
        elif c == 4:
            # knowledge sources
            result.scalars.return_value.all.return_value = [ks] if ks else []
        elif c == 5:
            # chunk texts
            result.scalars.return_value.all.return_value = chunk_texts
        elif c == 6:
            # count embeddings (for response)
            result.scalar_one.return_value = embedding_count
        else:
            result.scalar_one.return_value = 0
            result.scalars.return_value.all.return_value = []

        return result

    async def mock_get(model_class, pk):
        from app.db.models.index_version import IndexVersion
        if model_class is IndexVersion:
            return iv if str(pk) == str(iv.id) else None
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def _dep():
        yield mock_db
    return _dep


def _db_mock_for_activate(iv, existing_active_iv=None):
    """Build a DB mock for the activate endpoint."""
    async def mock_get(model_class, pk):
        from app.db.models.index_version import IndexVersion
        if model_class is IndexVersion:
            return iv if str(pk) == str(iv.id) else None
        return None

    async def mock_execute(stmt):
        result = MagicMock()
        # Returns active versions list
        result.scalars.return_value.all.return_value = [existing_active_iv] if existing_active_iv else []
        return result

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def _dep():
        yield mock_db
    return _dep


# ── Quality check: Authorization ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quality_check_anonymous_returns_401():
    """Anonymous request must return 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/quality-check")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_quality_check_chat_user_returns_403():
    """chat_user must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/quality-check")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_quality_check_faq_manager_returns_403():
    """faq_manager must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/quality-check")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Quality check: Resource checks ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quality_check_missing_index_version_returns_404():
    """Missing index version must return 404."""
    async def mock_get(model_class, pk):
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/quality-check")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_quality_check_active_index_returns_409():
    """Active index version must return 409 — cannot quality-check the live index."""
    iv = _make_iv(status="active")

    async def mock_get(model_class, pk):
        from app.db.models.index_version import IndexVersion
        if model_class is IndexVersion:
            return iv
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/quality-check")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_quality_check_non_draft_status_returns_409():
    """Index version with 'ready' status must return 409 (already quality-checked)."""
    iv = _make_iv(status="ready")

    async def mock_get(model_class, pk):
        from app.db.models.index_version import IndexVersion
        if model_class is IndexVersion:
            return iv
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/quality-check")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Quality check: Business logic ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quality_check_index_with_no_chunks_fails():
    """Index with zero embeddings must fail quality check."""
    iv = _make_iv(status="draft")
    ks = _make_ks()
    db_dep = _db_mock_for_qc(iv, ks=ks, embedding_count=0)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/quality-check")
        assert r.status_code == 200
        body = r.json()
        assert body["overall_passed"] is False
        assert body["status"] == "quality_check_failed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_quality_check_takshir_with_correct_metadata_passes():
    """Takshir draft with document_type=takshir and authority_level=1 must pass."""
    iv = _make_iv(status="draft")
    ks = _make_ks(authority_level=1)
    sd = _make_sd(ks.id, doc_type="pdf", semantic_type="takshir", authority_level=1)
    sd_ids = [sd.id]
    chunk_texts = ["chunk text about takshir policy " * 5 for _ in range(3)]

    call_index = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        c = call_index[0]
        call_index[0] += 1
        if c == 0:
            result.scalar_one.return_value = 3  # embedding count
        elif c == 1:
            result.scalar_one.return_value = 0  # orphan count
        elif c == 2:
            result.scalars.return_value.all.return_value = sd_ids
        elif c == 3:
            result.scalars.return_value.all.return_value = [sd]
        elif c == 4:
            result.scalars.return_value.all.return_value = [ks]
        elif c == 5:
            result.scalars.return_value.all.return_value = chunk_texts
        elif c == 6:
            result.scalar_one.return_value = 3
        else:
            result.scalar_one.return_value = 0
            result.scalars.return_value.all.return_value = []
        return result

    async def mock_get(model_class, pk):
        from app.db.models.index_version import IndexVersion
        if model_class is IndexVersion:
            return iv if str(pk) == str(iv.id) else None
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/quality-check")
        assert r.status_code == 200
        body = r.json()
        assert body["overall_passed"] is True
        assert body["status"] == "ready"
        assert body["chunk_count"] == 3
        assert "checks" in body
        # Takshir check should be present and passed
        takshir_check = next((c for c in body["checks"] if c["name"] == "takshir_metadata_valid"), None)
        assert takshir_check is not None
        assert takshir_check["passed"] is True
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_quality_check_does_not_activate_index():
    """Quality check must not set status='active', only 'ready' or 'quality_check_failed'."""
    iv = _make_iv(status="draft")
    ks = _make_ks(authority_level=1)
    sd = _make_sd(ks.id)
    sd_ids = [sd.id]
    chunk_texts = ["chunk text " * 10]

    call_index = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        c = call_index[0]
        call_index[0] += 1
        if c == 0:
            result.scalar_one.return_value = 1
        elif c == 1:
            result.scalar_one.return_value = 0
        elif c == 2:
            result.scalars.return_value.all.return_value = sd_ids
        elif c == 3:
            result.scalars.return_value.all.return_value = [sd]
        elif c == 4:
            result.scalars.return_value.all.return_value = [ks]
        elif c == 5:
            result.scalars.return_value.all.return_value = chunk_texts
        elif c == 6:
            result.scalar_one.return_value = 1
        else:
            result.scalar_one.return_value = 0
            result.scalars.return_value.all.return_value = []
        return result

    async def mock_get(model_class, pk):
        from app.db.models.index_version import IndexVersion
        if model_class is IndexVersion:
            return iv if str(pk) == str(iv.id) else None
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/quality-check")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] != "active"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_quality_check_raw_content_not_in_response():
    """Quality check response must not include raw chunk texts."""
    iv = _make_iv(status="draft")
    ks = _make_ks()
    db_dep = _db_mock_for_qc(iv, sd_ids=[uuid.uuid4()], ks=ks, embedding_count=1,
                              chunk_texts=["supersecretcontent"])

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/quality-check")
        assert r.status_code == 200
        assert "supersecretcontent" not in r.text
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Activation: Authorization ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_anonymous_returns_401():
    """Anonymous request must return 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/activate")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_activate_chat_user_returns_403():
    """chat_user must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_activate_faq_manager_returns_403():
    """faq_manager must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Activation: Business logic ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_draft_index_returns_409():
    """Cannot activate a draft (not quality-checked) index."""
    iv = _make_iv(status="draft")
    db_dep = _db_mock_for_activate(iv)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/activate")
        assert r.status_code == 409
        assert "quality" in r.json()["detail"].lower() or "ready" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_quality_failed_index_returns_409():
    """Cannot activate an index that failed quality checks."""
    iv = _make_iv(status="quality_check_failed")
    db_dep = _db_mock_for_activate(iv)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/activate")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_ready_index_succeeds_for_knowledge_admin():
    """knowledge_admin can activate a ready index."""
    iv = _make_iv(status="ready")
    db_dep = _db_mock_for_activate(iv)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/activate")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "active"
        assert body["index_version_id"] == str(iv.id)
        assert body["previous_active_id"] is None
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_ready_index_succeeds_for_system_admin():
    """system_admin can activate a ready index."""
    iv = _make_iv(status="ready")
    db_dep = _db_mock_for_activate(iv)

    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/activate")
        assert r.status_code == 200
        assert r.json()["status"] == "active"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_archives_previous_active_index():
    """Activation must archive the previous active index."""
    iv = _make_iv(status="ready", version_label="new-v1")
    old_active_iv = _make_iv(status="active", version_label="old-v1")
    db_dep = _db_mock_for_activate(iv, existing_active_iv=old_active_iv)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/activate")
        assert r.status_code == 200
        body = r.json()
        assert body["previous_active_id"] == str(old_active_iv.id)
        # Verify old_active_iv was actually updated
        assert old_active_iv.status == "archived"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_raw_content_not_in_response():
    """Activation response must not contain raw content."""
    iv = _make_iv(status="ready")
    db_dep = _db_mock_for_activate(iv)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with patch("app.api.admin_knowledge_index.record_audit_event", AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/index-versions/{iv.id}/activate")
        assert r.status_code == 200
        assert "chunk_text" not in r.text
        assert "storage_object_key" not in r.text
        assert "embedding" not in r.text
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
