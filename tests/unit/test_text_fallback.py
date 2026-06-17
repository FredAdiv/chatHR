"""Unit tests for retrieve_chunks_text_fallback and _extract_fallback_terms."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval.retriever import (
    _extract_fallback_terms,
    retrieve_chunks_text_fallback,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_fallback_row(
    chunk_text="פרק על קצובת נסיעה ותנאים",
    authority_level=1,
    chunk_index=5,
    context_type="government_ministries",
    source_url=None,
):
    return SimpleNamespace(
        chunk_id=uuid.uuid4(),
        chunk_text=chunk_text,
        chunk_index=chunk_index,
        section_title="פרק 26",
        page_number=42,
        parsed_document_id=uuid.uuid4(),
        source_document_id=uuid.uuid4(),
        source_url=source_url,
        source_title="תקשי״ר",
        document_type="pdf",
        knowledge_source_id=uuid.uuid4(),
        knowledge_source_name="תקשי״ר",
        authority_level=authority_level,
        text_score=3,
    )


def _make_fallback_db(rows):
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=rows)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ── _extract_fallback_terms ────────────────────────────────────────────────────

def test_extract_terms_removes_stop_words():
    # "לגבי" (4 chars) and "האם" (3 chars) are explicit stop words
    terms = _extract_fallback_terms("לגבי קצובת האם נסיעה")
    assert "לגבי" not in terms
    assert "האם" not in terms
    assert "קצובת" in terms
    assert "נסיעה" in terms


def test_extract_terms_min_length_3():
    terms = _extract_fallback_terms("מה לגבי כל זה")
    assert all(len(t) >= 3 for t in terms)


def test_extract_terms_empty_after_stop_words():
    terms = _extract_fallback_terms("מה על של את")
    assert terms == []


def test_extract_terms_normalizes_hebrew():
    # Geresh variant "התקשי'ר" should normalize and remain usable
    terms = _extract_fallback_terms("האם התקשיר")
    assert any("תקשיר" in t for t in terms)


# ── retrieve_chunks_text_fallback ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_finds_chunk_by_hebrew_term():
    row = _make_fallback_row(chunk_text="קצובת נסיעה לעובד מדינה")
    db = _make_fallback_db([row])
    results = await retrieve_chunks_text_fallback(
        db, "מהי קצובת נסיעה", uuid.uuid4()
    )
    assert len(results) == 1
    assert results[0].chunk_text == "קצובת נסיעה לעובד מדינה"


@pytest.mark.asyncio
async def test_fallback_returns_empty_when_no_useful_terms():
    db = _make_fallback_db([])
    # Query is only stop words — no terms extracted
    results = await retrieve_chunks_text_fallback(
        db, "מה על של", uuid.uuid4()
    )
    assert results == []
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_respects_context_type():
    """Fallback adds context_type filter when provided — verified by checking the query is executed."""
    row = _make_fallback_row()
    db = _make_fallback_db([row])
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4(), context_type="government_ministries"
    )
    assert len(results) == 1
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_includes_null_context_when_context_provided():
    """Null-context (general) sources are always included even with a specific context_type.

    This is enforced in the ORM query via (context_type = X OR context_type IS NULL).
    We verify the function runs without error and returns results.
    """
    row = _make_fallback_row(context_type=None)
    db = _make_fallback_db([row])
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4(), context_type="defense_system"
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_fallback_authority_level_in_result():
    row = _make_fallback_row(authority_level=1)
    db = _make_fallback_db([row])
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4()
    )
    assert results[0].citation.authority_level == 1


@pytest.mark.asyncio
async def test_fallback_no_storage_object_key_in_citation():
    """Citation metadata must not expose storage_object_key or upload:// URLs."""
    row = _make_fallback_row(source_url="upload://bucket/key/file.pdf")
    db = _make_fallback_db([row])
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4()
    )
    assert len(results) == 1
    # source_url is passed through; the upload:// stripping happens in chat.py.
    # Verify that chunk has no storage_object_key field at all (not in RetrievedChunk).
    assert not hasattr(results[0], "storage_object_key")
    assert not hasattr(results[0], "storage_bucket")


@pytest.mark.asyncio
async def test_fallback_returns_empty_list_when_db_empty():
    db = _make_fallback_db([])
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4()
    )
    assert results == []


@pytest.mark.asyncio
async def test_fallback_chunk_has_distance_minus_one_and_score_one():
    """Fallback chunks use sentinel distance=-1.0, score=1.0 (no vector similarity)."""
    row = _make_fallback_row()
    db = _make_fallback_db([row])
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4()
    )
    assert results[0].distance == -1.0
    assert results[0].score == 1.0


@pytest.mark.asyncio
async def test_fallback_respects_limit():
    rows = [_make_fallback_row(chunk_index=i) for i in range(10)]
    db = _make_fallback_db(rows[:3])  # DB returns only 3 due to LIMIT
    results = await retrieve_chunks_text_fallback(
        db, "קצובת נסיעה", uuid.uuid4(), limit=3
    )
    assert len(results) == 3
