"""Tests for answer synthesis: extractive fallback, fake-local detection, citation quality."""
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
from app.services.chat.extractive_synthesizer import is_usable_llm_response, synthesize_answer
from app.services.llm_gateway.protocol import LLMProviderError, LLMResponse
from app.services.retrieval.citation import CitationMetadata
from app.services.retrieval.retriever import RetrievedChunk


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


def _make_takshir_chunk(chunk_text: str | None = None) -> RetrievedChunk:
    """Create a chunk that resembles a real Takshir document chunk."""
    text = chunk_text or (
        "הוראות התקשי\"ר חלות על כל סוגי העובדים בשירות המדינה, "
        "בכפוף להוראות התחולה שנקבעו לכל הוראה בתקשי\"ר. "
        "בין היתר, התקשי\"ר מונה עובדים בניסיון, עובדים קבועים, עובדים זמניים."
    )
    citation = CitationMetadata(
        source_url=None,
        source_title='תקשי"ר',
        knowledge_source_id=str(uuid.uuid4()),
        knowledge_source_name='נציבות שירות המדינה',
        authority_level=1,
        section_title="01.021 — תחולה",
        page_number=1,
        chunk_index=0,
        document_type="takshir",
    )
    return RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        chunk_text=text,
        parsed_document_id=str(uuid.uuid4()),
        source_document_id=str(uuid.uuid4()),
        distance=0.1,
        score=0.9,
        citation=citation,
    )


def _make_db_for_chat(conv, iv):
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
    returns = [conv, iv]

    async def _execute(stmt, *args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        val = returns[idx] if idx < len(returns) else None

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


# ── Unit tests: is_usable_llm_response ────────────────────────────────────────

def test_is_usable_empty_string_returns_false():
    assert is_usable_llm_response("") is False


def test_is_usable_whitespace_only_returns_false():
    assert is_usable_llm_response("   \n  ") is False


def test_is_usable_fake_local_prefix_returns_false():
    fake = "[fake-local] Acknowledged 2 message(s) for purpose='chat_answer' using model='gpt-4'."
    assert is_usable_llm_response(fake) is False


def test_is_usable_fake_local_suffix_returns_false():
    fake = "Acknowledged 2 message(s) for purpose='chat_answer' using model='gpt-4' [fake-local]"
    assert is_usable_llm_response(fake) is False


def test_is_usable_acknowledged_without_fake_local_returns_false():
    # "acknowledged" alone triggers the filter (conservative)
    assert is_usable_llm_response("Acknowledged something") is False


def test_is_usable_real_hebrew_answer_returns_true():
    assert is_usable_llm_response("הוראות התקשי\"ר חלות על כל סוגי העובדים.") is True


def test_is_usable_english_answer_returns_true():
    assert is_usable_llm_response("The regulations apply to all government employees.") is True


# ── Unit tests: synthesize_answer ─────────────────────────────────────────────

def test_synthesize_empty_chunks_returns_safe_message():
    result = synthesize_answer([])
    assert "נמצאו מקורות" in result or "לא" in result


def test_synthesize_includes_chunk_text():
    chunk = _make_takshir_chunk()
    result = synthesize_answer([chunk])
    assert "חלות על כל סוגי העובדים" in result


def test_synthesize_includes_source_title():
    chunk = _make_takshir_chunk()
    result = synthesize_answer([chunk])
    assert 'תקשי"ר' in result


def test_synthesize_includes_section_title():
    chunk = _make_takshir_chunk()
    result = synthesize_answer([chunk])
    assert "01.021" in result


def test_synthesize_never_empty():
    chunk = _make_takshir_chunk(chunk_text="א")
    result = synthesize_answer([chunk])
    assert result.strip() != ""


def test_synthesize_truncates_very_long_chunk():
    long_text = "א" * 2000
    chunk = _make_takshir_chunk(chunk_text=long_text)
    result = synthesize_answer([chunk])
    assert len(result) < 2000


def test_synthesize_max_two_chunks_used():
    chunks = [_make_takshir_chunk(f"טקסט {i}") for i in range(5)]
    result = synthesize_answer(chunks)
    # Only first 2 chunks should appear
    assert "טקסט 0" in result
    assert "טקסט 1" in result
    assert "טקסט 2" not in result


# ── Integration tests: chat API with extractive fallback ──────────────────────

@pytest.mark.asyncio
async def test_fake_local_llm_response_not_returned_to_user():
    """Fake-local acknowledgment must never appear in the API response."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()
    fake_response = LLMResponse(
        content="[fake-local] Acknowledged 2 message(s) for purpose='chat_answer' using model='gpt-4'.",
        model="gpt-4",
        provider="fake-local",
        input_token_count=10,
        output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(return_value=fake_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "על מי חלות הוראות התקשי\"ר?"},
                )
            assert r.status_code == 200
            data = r.json()
            answer = data["message"]["content"]
            assert "[fake-local]" not in answer
            assert "Acknowledged" not in answer
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_fake_local_mode_returns_grounded_hebrew_answer():
    """With fake-local LLM and a Takshir chunk, the response must contain chunk text."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()
    fake_response = LLMResponse(
        content="[fake-local] Acknowledged 2 message(s).",
        model="gpt-4",
        provider="fake-local",
        input_token_count=10,
        output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(return_value=fake_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "על מי חלות הוראות התקשי\"ר?"},
                )
            assert r.status_code == 200
            data = r.json()
            answer = data["message"]["content"]
            # Answer must be non-empty and contain text from the Takshir chunk
            assert answer.strip() != ""
            assert "חלות על כל סוגי העובדים" in answer
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_fake_local_answer_includes_citations():
    """Response must include at least one citation when retrieval succeeds."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()
    fake_response = LLMResponse(
        content="[fake-local] Acknowledged 2 message(s).",
        model="gpt-4",
        provider="fake-local",
        input_token_count=10,
        output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(return_value=fake_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "על מי חלות הוראות התקשי\"ר?"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["retrieval_count"] >= 1
            assert len(data["sources"]) >= 1
            src = data["sources"][0]
            assert src["document_type"] == "takshir"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_empty_llm_response_triggers_local_fallback():
    """Empty LLM response content must trigger the local extractive synthesizer."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()
    empty_response = LLMResponse(
        content="",
        model="gpt-4",
        provider="openrouter",
        input_token_count=10,
        output_token_count=0,
    )

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(return_value=empty_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה לגבי התקשי\"ר?"},
                )
            assert r.status_code == 200
            data = r.json()
            answer = data["message"]["content"]
            assert answer.strip() != ""
            assert "חלות על כל סוגי העובדים" in answer
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_llm_provider_error_triggers_local_fallback():
    """LLMProviderError (all providers failed) must trigger local extractive synthesizer."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(side_effect=LLMProviderError("all providers failed"))):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה לגבי התקשי\"ר?"},
                )
            assert r.status_code == 200
            data = r.json()
            answer = data["message"]["content"]
            assert answer.strip() != ""
            # Should contain chunk text from local synthesizer
            assert "חלות על כל סוגי העובדים" in answer
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_citations_only_response_not_allowed_when_retrieval_succeeds():
    """When retrieval succeeds, the answer must not be empty (citations only is not acceptable)."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()
    fake_response = LLMResponse(
        content="[fake-local] Acknowledged.",
        model="gpt-4",
        provider="fake-local",
        input_token_count=10,
        output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(return_value=fake_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה?"},
                )
            assert r.status_code == 200
            data = r.json()
            # Answer must be non-empty — citations alone are not sufficient
            answer = data["message"]["content"]
            assert answer.strip() != ""
            # There must also be sources
            assert data["retrieval_count"] >= 1
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_no_sources_returns_safe_no_source_answer():
    """When no sources are retrieved, return safe refusal — no hallucination."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[])), \
         patch("app.api.chat.generate_with_gateway") as mock_llm:
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה שאין לה מקור"},
                )
            assert r.status_code == 200
            data = r.json()
            assert data["retrieval_count"] == 0
            assert data["sources"] == []
            # LLM must NOT be called when no sources available
            mock_llm.assert_not_called()
            answer = data["message"]["content"]
            assert answer.strip() != ""
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_takshir_question_answer_contains_key_text():
    """Specific test: Takshir scope question must return grounded Hebrew answer."""
    dep, user = _auth(["chat_user"])
    conv = _make_conv(user_id=user.id)
    iv = _make_index_version()
    db = _make_db_for_chat(conv, iv)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_dep(db)

    chunk = _make_takshir_chunk()
    fake_response = LLMResponse(
        content="[fake-local] Acknowledged 2 message(s) for purpose='chat_answer' using model='openai/gpt-4'.",
        model="openai/gpt-4",
        provider="fake-local",
        input_token_count=50,
        output_token_count=5,
    )

    with patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[chunk])), \
         patch("app.api.chat.generate_with_gateway", AsyncMock(return_value=fake_response)):
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": 'על מי חלות הוראות התקשי"ר?'},
                )
            assert r.status_code == 200
            data = r.json()
            answer = data["message"]["content"]

            # Must not contain fake-local markers
            assert "[fake-local]" not in answer
            assert "Acknowledged" not in answer
            assert "fake-local" not in answer

            # Must contain grounded text from the Takshir chunk
            assert "חלות על כל סוגי העובדים בשירות המדינה" in answer

            # Must include a citation to Takshir
            assert data["retrieval_count"] >= 1
            source_titles = [s["source_title"] for s in data["sources"]]
            assert any('תקשי"ר' in (t or "") for t in source_titles)
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)
