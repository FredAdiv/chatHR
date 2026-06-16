"""Ingestion API — authorization and endpoint tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.models.ingestion_run import IngestionRun
from app.db.models.ingestion_run_document import IngestionRunDocument
from app.db.models.source_document import SourceDocument
from app.db.session import get_db
from app.main import app


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


def _now_str():
    return datetime.now(timezone.utc).isoformat()


def _make_run(status="completed", mode="dry_run"):
    now = datetime.now(timezone.utc)
    run = MagicMock(spec=IngestionRun)
    run.id = uuid.uuid4()
    run.index_version_id = None
    run.started_by_user_id = uuid.uuid4()
    run.status = status
    run.mode = mode
    run.started_at = now
    run.completed_at = now
    run.summary_json = {"mode": mode, "documents_processed": 1, "actions": {"discovered": 1}}
    run.error_message = None
    return run


def _db_for_start_run(run):
    """DB mock for POST /admin/ingestion/runs — orchestrator is patched separately."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _db_for_list(items):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = items
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


def _db_for_get_run(run, run_docs=None):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = run_docs or []
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=run)
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingestion_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/ingestion/runs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ingestion_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/runs")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_ingestion_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/runs")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_ingestion_faq_manager_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/runs")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST /admin/ingestion/runs ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_admin_can_start_run():
    run = _make_run(status="completed", mode="dry_run")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_start_run(run)
    try:
        with patch("app.api.admin_ingestion.run_ingestion_for_source", return_value=run):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/admin/ingestion/runs", json={
                    "knowledge_source_id": str(uuid.uuid4()),
                    "mode": "dry_run",
                })
        assert r.status_code == 201
        assert r.json()["status"] == "completed"
        assert r.json()["mode"] == "dry_run"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_system_admin_can_start_run():
    run = _make_run(status="completed", mode="metadata_only")
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_for_start_run(run)
    try:
        with patch("app.api.admin_ingestion.run_ingestion_for_source", return_value=run):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/admin/ingestion/runs", json={
                    "knowledge_source_id": str(uuid.uuid4()),
                    "mode": "metadata_only",
                })
        assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_invalid_mode_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/ingestion/runs", json={
                "knowledge_source_id": str(uuid.uuid4()),
                "mode": "full_crawl",  # invalid
            })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_missing_knowledge_source_id_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/ingestion/runs", json={"mode": "dry_run"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── GET /admin/ingestion/runs ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_runs_returns_200():
    run = _make_run()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([run])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/runs")
        assert r.status_code == 200
        assert len(r.json()) == 1
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── GET /admin/ingestion/runs/{run_id} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_run_returns_200_with_documents():
    run = _make_run()
    now = datetime.now(timezone.utc)
    rd = MagicMock(spec=IngestionRunDocument)
    rd.id = uuid.uuid4()
    rd.ingestion_run_id = run.id
    rd.source_document_id = None
    rd.url = "https://www.gov.il/docs"
    rd.action = "discovered"
    rd.error_message = None
    rd.metadata_json = None
    rd.created_at = now

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get_run(run, run_docs=[rd])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/ingestion/runs/{uuid.uuid4()}")
        assert r.status_code == 200
        body = r.json()
        assert body["run_documents"] is not None
        assert len(body["run_documents"]) == 1
        assert body["run_documents"][0]["action"] == "discovered"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_run_missing_id_returns_404():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get_run(None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/ingestion/runs/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── GET /admin/ingestion/source-documents ─────────────────────────────────────

# ── GET filter validation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_runs_invalid_status_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/runs?status=invalid_status")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_list_runs_invalid_mode_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/runs?mode=invalid_mode")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_list_source_documents_invalid_status_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/source-documents?status=invalid_status")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_list_source_documents_document_type_is_freeform():
    """document_type is a freeform string filter — any value returns 200, not 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/source-documents?document_type=any_value")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_source_documents_returns_200():
    now = datetime.now(timezone.utc)
    sd = MagicMock(spec=SourceDocument)
    sd.id = uuid.uuid4()
    sd.knowledge_source_id = uuid.uuid4()
    sd.url = "https://www.gov.il/docs"
    sd.title = None
    sd.document_type = "html"
    sd.source_etag = None
    sd.source_last_modified = None
    sd.content_hash = None
    sd.storage_bucket = None
    sd.storage_object_key = None
    sd.status = "discovered"
    sd.first_seen_at = now
    sd.last_seen_at = now
    sd.downloaded_at = None
    sd.created_at = now
    sd.updated_at = now

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([sd])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/ingestion/source-documents")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["status"] == "discovered"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
