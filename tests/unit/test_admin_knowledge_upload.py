"""Tests for POST /admin/knowledge/upload endpoint."""
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


def _make_ks():
    ks = MagicMock()
    ks.id = uuid.uuid4()
    return ks


def _make_sd(ks_id):
    sd = MagicMock()
    sd.id = uuid.uuid4()
    sd.knowledge_source_id = ks_id
    sd.status = "downloaded"
    sd.metadata_json = {}
    return sd


def _db_mock_for_upload(ks=None, sd=None):
    """Return a get_db override that returns a mock AsyncSession."""
    ks = ks or _make_ks()
    sd = sd or _make_sd(ks.id)

    call_count = [0]

    async def mock_execute(stmt):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:
            result.scalar_one_or_none.return_value = ks
        else:
            result.scalar_one_or_none.return_value = sd
        return result

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def _dep():
        yield mock_db

    return _dep, ks, sd


def _pdf_file(content=b"%PDF-1.4 test"):
    return ("file", ("doc.pdf", content, "application/pdf"))


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_anonymous_returns_401():
    """Anonymous request must be rejected with 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/knowledge/upload",
            files=[_pdf_file()],
            data={"title": "Test", "document_type": "policy", "authority_level": "1"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_upload_chat_user_returns_403():
    """chat_user role must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[_pdf_file()],
                data={"title": "Test", "document_type": "policy", "authority_level": "1"},
            )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_upload_faq_manager_returns_403():
    """faq_manager role must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[_pdf_file()],
                data={"title": "Test", "document_type": "policy", "authority_level": "1"},
            )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── knowledge_admin accepted ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_knowledge_admin_accepted():
    """knowledge_admin must succeed and return document_id + status."""
    db_dep, ks, sd = _db_mock_for_upload()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_upload.put_bytes"),
            patch("app.api.admin_knowledge_upload.sha256_hex", return_value="ab" * 32),
            patch("app.api.admin_knowledge_upload.record_audit_event", AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/admin/knowledge/upload",
                    files=[_pdf_file()],
                    data={"title": "Test Doc", "document_type": "policy", "authority_level": "2"},
                )
        assert r.status_code == 201
        body = r.json()
        assert "document_id" in body
        assert "knowledge_source_id" in body
        assert body["status"] == "pending_processing"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_system_admin_accepted():
    """system_admin must succeed (has knowledge_admin-equivalent access)."""
    db_dep, ks, sd = _db_mock_for_upload()
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_upload.put_bytes"),
            patch("app.api.admin_knowledge_upload.sha256_hex", return_value="cd" * 32),
            patch("app.api.admin_knowledge_upload.record_audit_event", AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/admin/knowledge/upload",
                    files=[_pdf_file()],
                    data={"title": "Test", "document_type": "takshir", "authority_level": "1"},
                )
        assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── File validation ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_unsupported_extension_rejected():
    """Unsupported file extension must return 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[("file", ("document.exe", b"binary content", "application/octet-stream"))],
                data={"title": "Bad File", "document_type": "policy", "authority_level": "1"},
            )
        assert r.status_code == 422
        body = r.json()
        assert body.get("detail", {}).get("error") == "unsupported_extension"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_upload_xml_extension_rejected():
    """XML extension is not in the supported list — must return 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[("file", ("data.xml", b"<root/>", "text/xml"))],
                data={"title": "XML", "document_type": "policy", "authority_level": "1"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_upload_empty_file_rejected():
    """Empty file must return 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[("file", ("empty.pdf", b"", "application/pdf"))],
                data={"title": "Empty", "document_type": "policy", "authority_level": "1"},
            )
        assert r.status_code == 422
        body = r.json()
        assert body.get("detail", {}).get("error") == "empty_file"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Required fields ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_title_required():
    """Missing title must return 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[_pdf_file()],
                data={"document_type": "policy", "authority_level": "1"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_upload_authority_level_required():
    """Missing authority_level must return 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[_pdf_file()],
                data={"title": "Test", "document_type": "policy"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_upload_authority_level_out_of_range():
    """authority_level outside 1-5 must return 422."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/admin/knowledge/upload",
                files=[_pdf_file()],
                data={"title": "Test", "document_type": "policy", "authority_level": "99"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Takshir preset ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_takshir_preset_works():
    """Takshir preset fields (document_type=takshir, authority_level=1) must succeed."""
    db_dep, ks, sd = _db_mock_for_upload()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_upload.put_bytes"),
            patch("app.api.admin_knowledge_upload.sha256_hex", return_value="ef" * 32),
            patch("app.api.admin_knowledge_upload.record_audit_event", AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/admin/knowledge/upload",
                    files=[_pdf_file(b"%PDF-1.4 takshir content")],
                    data={
                        "title": 'תקשי"ר',
                        "document_type": "takshir",
                        "authority_level": "1",
                        "source_url": "https://www.gov.il/he/departments/policies/takshir",
                    },
                )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending_processing"
        assert "document_id" in body
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Security: raw content not in response ──────────────────────────────────────

@pytest.mark.asyncio
async def test_raw_content_not_in_response():
    """File bytes must never appear in the API response body."""
    db_dep, ks, sd = _db_mock_for_upload()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep

    secret_content = b"TOP SECRET EMPLOYEE DATA: employee_id=12345 salary=99999"
    try:
        with (
            patch("app.api.admin_knowledge_upload.put_bytes"),
            patch("app.api.admin_knowledge_upload.sha256_hex", return_value="aa" * 32),
            patch("app.api.admin_knowledge_upload.record_audit_event", AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/admin/knowledge/upload",
                    files=[("file", ("secret.pdf", secret_content, "application/pdf"))],
                    data={"title": "Secret", "document_type": "policy", "authority_level": "1"},
                )
        assert r.status_code == 201
        raw_response = r.text
        assert b"TOP SECRET".decode() not in raw_response
        assert b"employee_id".decode() not in raw_response
        assert b"salary".decode() not in raw_response
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Optional fields ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_with_optional_fields():
    """Optional fields (source_url, system_context, notes) should be accepted."""
    db_dep, ks, sd = _db_mock_for_upload()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_upload.put_bytes"),
            patch("app.api.admin_knowledge_upload.sha256_hex", return_value="bb" * 32),
            patch("app.api.admin_knowledge_upload.record_audit_event", AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/admin/knowledge/upload",
                    files=[_pdf_file()],
                    data={
                        "title": "Full Upload",
                        "document_type": "circular",
                        "authority_level": "3",
                        "source_url": "https://www.gov.il/example",
                        "system_context": "government_ministries",
                        "notes": "הועלה לצורך בדיקה",
                    },
                )
        assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
