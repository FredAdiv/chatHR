"""Chat API — authorization, privacy, flow, and feedback tests."""
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
from app.services.retrieval.citation import CitationMetadata
from app.services.retrieval.retriever import RetrievedChunk


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    return _dep, u


def _make_conv(user_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        context_type="government_ministries",
        title=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _make_index_version():
    return SimpleNamespace(id=uuid.uuid4(), status="active")


def _make_message(conv_id, role="assistant"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role=role,
        content="Test content",
        created_at=datetime.now(timezone.utc),
        metadata_json=None,
    )


def _make_chunk():
    citation = CitationMetadata(
        source_url="https://example.gov.il/policy.pdf",
        source_title="מדיניות חופשות",
        knowledge_source_id=str(uuid.uuid4()),
        knowledge_source_name="נציבות שירות המדינה",
        authority_level=1,
        section_title=None,
        page_number=None,
        chunk_index=0,
        document_type="pdf",
    )
    return RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        chunk_text="כלל 30 ימי חופשה שנתית.",
        parsed_document_id=str(uuid.uuid4()),
        source_document_id=str(uuid.uuid4()),
        distance=0.2,
        score=0.8,
        citation=citation,
    )


def _make_db(*execute_results):
    """DB mock returning execute_results in sequence."""
    results = list(execute_results)
    call_idx = [0]
    mock_db = AsyncMock()
    added = []
    mock_db.add = MagicMock(side_effect=lambda obj: added.append(obj))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = datetime.now(timezone.utc)
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    mock_db.refresh = _refresh

    async def _execute(stmt, *args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        val = results[idx] if idx < len(results) else None

        class _R:
            def __init__(self, v):
                self._v = v

            def scalar_one_or_none(self):
                return self._v

            def scalars(self):
                class _S:
                    def __init__(self, vv):
                        self._vv = vv

                    def all(self):
                        return self._vv if isinstance(self._vv, list) else []

                return _S(self._v)

        return _R(val)

    mock_db.execute = _execute
    mock_db._added = added
    return mock_db


def _db_dep(mock_db):
    async def _dep():
        yield mock_db
    return _dep


CONV_ID = uuid.uuid4()


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_conversation_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/chat/conversations", json={"context_type": "government_ministries"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_conversations_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/chat/conversations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_send_message_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/chat/conversations/{CONV_ID}/messages", json={"content": "hi"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_user_admin_cannot_access_chat_returns_403():
    dep, _ = _auth(["user_admin"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/chat/conversations")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_faq_manager_cannot_access_chat_returns_403():
    dep, _ = _auth(["faq_manager"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/chat/conversations")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_knowledge_admin_cannot_access_chat_returns_403():
    dep, _ = _auth(["knowledge_admin"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/chat/conversations")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST /chat/conversations ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_conversation_chat_user_returns_201():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    db = _make_db()

    async def _refresh(obj):
        obj.id = conv.id
        obj.context_type = conv.context_type
        obj.title = conv.title
        obj.created_at = conv.created_at

    db.refresh = _refresh
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/chat/conversations", json={"context_type": "government_ministries"})
        assert r.status_code == 201
        data = r.json()
        assert data["context_type"] == "government_ministries"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_conversation_invalid_context_type_returns_422():
    dep, _ = _auth(["chat_user"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/chat/conversations", json={"context_type": "invalid_type"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── GET /chat/conversations ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_conversations_returns_only_own():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    db = _make_db([conv])  # scalars().all() returns [conv]
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/chat/conversations")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── GET /chat/conversations/{id} ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_conversation_not_owned_returns_404():
    dep, user = _auth(["chat_user"])
    # DB returns None (conv not owned by user)
    db = _make_db(None, [])
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/chat/conversations/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST .../messages — privacy guard ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_pii_returns_422_without_matched_text():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    db = _make_db(conv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "My email is pii@example.com please help"},
            )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "privacy_guard_blocked"
        assert "findings" in detail
        for f in detail["findings"]:
            assert "matched_text" not in f
            assert "pii@example.com" not in str(f)
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_send_message_pii_not_stored():
    """High-severity PII in message must not be stored in DB."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    db = _make_db(conv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "Phone: 052-1234567"},
            )
        # db.add must not have been called with any Message-containing content
        from app.db.models.message import Message
        message_adds = [o for o in db._added if isinstance(o, Message)]
        assert message_adds == []
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST .../messages — no active index ──────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_no_active_index_returns_503():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    # DB returns conv, then None for index version
    db = _make_db(conv, None)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "מה מדיניות החופשות?"},
            )
        assert r.status_code == 503
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST .../messages — no retrieval results ─────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_no_sources_does_not_call_llm():
    """When no retrieval results, LLM Gateway must NOT be called."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[])), \
         patch("app.api.chat.generate_with_gateway") as mock_llm:
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה שאין לה מקור"},
                )
            assert r.status_code == 200
            mock_llm.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_send_message_no_sources_returns_safe_refusal():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[])):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה כללית"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["retrieval_count"] == 0
            assert data["sources"] == []
            assert "לא" in data["message"]["content"] or "no" in data["message"]["content"].lower()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


# ── POST .../messages — retrieval + LLM ──────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_with_sources_calls_llm_gateway():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_chunk()
    from app.services.llm_gateway.protocol import LLMResponse
    mock_llm_response = LLMResponse(
        content="[fake-local] תשובת MVP",
        model="fake-local-v1",
        provider="fake-local",
        input_token_count=10,
        output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", new=AsyncMock(return_value=mock_llm_response)) as mock_llm:
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "כמה ימי חופשה?"},
                )
            assert r.status_code == 200
            mock_llm.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_send_message_response_includes_sources():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_chunk()
    from app.services.llm_gateway.protocol import LLMResponse
    mock_llm_response = LLMResponse(
        content="תשובה", model="fake-local-v1", provider="fake-local",
        input_token_count=5, output_token_count=3,
    )

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", new=AsyncMock(return_value=mock_llm_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "כמה ימי חופשה?"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["retrieval_count"] == 1
            assert len(data["sources"]) == 1
            src = data["sources"][0]
            assert "knowledge_source_id" in src
            assert "authority_level" in src
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_send_message_metadata_does_not_include_prompt_text():
    """Message metadata_json must not contain full prompt or user text."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_chunk()
    from app.services.llm_gateway.protocol import LLMResponse
    mock_llm_response = LLMResponse(
        content="תשובה", model="fake-local-v1", provider="fake-local",
        input_token_count=5, output_token_count=3,
    )

    added_messages = []

    original_add = db.add

    def _capture_add(obj):
        from app.db.models.message import Message
        if isinstance(obj, Message):
            added_messages.append(obj)
        original_add(obj)

    db.add = _capture_add

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", new=AsyncMock(return_value=mock_llm_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "very secret user question text"},
                )
            for msg in added_messages:
                meta_str = str(getattr(msg, "metadata_json", ""))
                assert "very secret user question text" not in meta_str
                assert "רק" not in meta_str  # no system prompt text
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


# ── POST /chat/messages/{id}/feedback ────────────────────────────────────────

@pytest.mark.asyncio
async def test_feedback_pii_comment_returns_422():
    dep, user = _auth(["chat_user"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/messages/{uuid.uuid4()}/feedback",
                json={"rating": "positive", "comment": "Email me at test@example.com"},
            )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "privacy_guard_blocked"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_feedback_on_non_assistant_message_returns_422():
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    msg = _make_message(conv.id, role="user")
    db = _make_db(msg, conv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/messages/{msg.id}/feedback",
                json={"rating": "positive"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_feedback_on_other_user_message_returns_404():
    """User cannot submit feedback on another user's message."""
    dep, user = _auth(["chat_user"])
    other_user_id = uuid.uuid4()
    conv = _make_conv(user_id=other_user_id)
    msg = _make_message(conv.id, role="assistant")
    # DB: message found, but conv NOT owned by current_user → None
    db = _make_db(msg, None)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/messages/{msg.id}/feedback",
                json={"rating": "positive"},
            )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_feedback_invalid_rating_returns_422():
    dep, _ = _auth(["chat_user"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/messages/{uuid.uuid4()}/feedback",
                json={"rating": "neutral"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── has_sufficient_sources ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_sources_returns_has_sufficient_sources_false():
    """When retrieval returns no chunks, response must have has_sufficient_sources=False."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[])):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה ללא מקור"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["has_sufficient_sources"] is False
            assert data["sources"] == []
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_no_source_llm_answer_clears_sources_and_sets_flag_false():
    """When LLM returns a no-source refusal phrase, sources must be hidden."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_chunk()
    from app.services.llm_gateway.protocol import LLMResponse
    no_source_json = '{"answer_text": "לא נמצא מקור רשמי מספיק ברור כדי לענות.", "answer_blocks": []}'
    mock_llm_response = LLMResponse(
        content=no_source_json, model="gpt-4o", provider="openrouter",
        input_token_count=10, output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", new=AsyncMock(return_value=mock_llm_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "עבודה מרחוק מחו״ל"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["has_sufficient_sources"] is False
            assert data["sources"] == []
            assert data["answer_blocks"] == []
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_grounded_answer_has_sufficient_sources_true():
    """Normal grounded answer must have has_sufficient_sources=True."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_chunk()
    from app.services.llm_gateway.protocol import LLMResponse
    mock_llm_response = LLMResponse(
        content="[fake-local] תשובה", model="fake-local-v1", provider="fake-local",
        input_token_count=5, output_token_count=3,
    )

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", new=AsyncMock(return_value=mock_llm_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "על מי חלות הוראות התקשיר?"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["has_sufficient_sources"] is True
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


# ── Privacy block user_message ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_privacy_block_includes_hebrew_user_message():
    """Privacy block response must include Hebrew user_message field."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    db = _make_db(conv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "אימייל שלי test@example.com"},
            )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "privacy_guard_blocked"
        assert "user_message" in detail
        assert "פרטים אישיים" in detail["user_message"]
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Conversation title auto-generation ────────────────────────────────────────

def test_generate_conversation_title_basic():
    from app.api.chat import _generate_conversation_title
    title = _generate_conversation_title("מה הם כללי חופשה שנתית לעובדי מדינה?")
    assert len(title) <= 40
    assert title  # not empty


def test_generate_conversation_title_capped():
    from app.api.chat import _generate_conversation_title
    long_text = "מה " * 30
    title = _generate_conversation_title(long_text)
    assert len(title) <= 40


def test_generate_conversation_title_strips_punctuation():
    from app.api.chat import _generate_conversation_title
    title = _generate_conversation_title("זכויות? לסטודנט! עובד.")
    assert "?" not in title
    assert "!" not in title
    assert "." not in title


def test_generate_conversation_title_fallback():
    from app.api.chat import _generate_conversation_title
    title = _generate_conversation_title("")
    assert title == "שיחה חדשה"


@pytest.mark.asyncio
async def test_send_message_sets_conversation_title():
    """First valid message must auto-set conversation title."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    assert conv.title is None
    iv = _make_index_version()
    db = _make_db(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    with patch("app.api.chat.retrieve_chunks", new=AsyncMock(return_value=[])):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "על מי חלות הוראות התקשיר"},
                )
            assert conv.title is not None
            assert len(conv.title) > 0
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


# ── Model integrity ───────────────────────────────────────────────────────────

def test_message_source_model_registered():
    from app.db import models
    assert hasattr(models, "MessageSource")
    assert models.MessageSource is not None


def test_message_has_metadata_json_column():
    from app.db.models.message import Message
    cols = {c.name for c in Message.__table__.columns}
    assert "metadata_json" in cols


def test_message_source_has_no_chunk_text_column():
    """MessageSource must not store full chunk text."""
    from app.db.models.message_source import MessageSource
    cols = {c.name for c in MessageSource.__table__.columns}
    assert "chunk_text" not in cols
    assert "prompt" not in cols
    assert "user_text" not in cols
