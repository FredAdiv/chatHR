"""Unit tests for retrieve_chunks service and citation builder."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval.citation import build_citation_metadata
from app.services.retrieval.retriever import ALLOWED_CONTEXT_TYPES, retrieve_chunks


def _make_row(distance=0.2, authority_level=3, chunk_index=0):
    return SimpleNamespace(
        chunk_id=uuid.uuid4(),
        chunk_text="Government HR policy excerpt",
        chunk_index=chunk_index,
        section_title="Section 4",
        page_number=None,
        parsed_document_id=uuid.uuid4(),
        source_document_id=uuid.uuid4(),
        source_url="https://example.gov.il/doc.pdf",
        source_title="HR Policy 2026",
        document_type="pdf",
        knowledge_source_id=uuid.uuid4(),
        knowledge_source_name="Civil Service Commission",
        authority_level=authority_level,
        distance=distance,
    )


def _make_db(rows):
    from app.db.models.index_version import IndexVersion
    fake_iv = MagicMock(spec=IndexVersion)
    fake_iv.embedding_provider = "fake-local"
    fake_iv.embedding_model = "fake-local-v1"
    fake_iv.embedding_dimensions = 16

    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(rows))
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=fake_iv)
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


# ── Input validation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rejects_empty_query_text():
    db = _make_db([])
    with pytest.raises(ValueError, match="empty"):
        await retrieve_chunks(db, "", uuid.uuid4())


@pytest.mark.asyncio
async def test_requires_index_version_id():
    db = _make_db([])
    with pytest.raises(ValueError, match="index_version_id"):
        await retrieve_chunks(db, "HR leave policy", None)


@pytest.mark.asyncio
async def test_invalid_context_type_raises():
    db = _make_db([])
    with pytest.raises(ValueError, match="not valid"):
        await retrieve_chunks(db, "query", uuid.uuid4(), context_type="invalid_type")


# ── Result formatting ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_returns_results_with_citation_metadata():
    row = _make_row()
    db = _make_db([row])

    results = await retrieve_chunks(db, "annual leave", uuid.uuid4())

    assert len(results) == 1
    r = results[0]
    assert r.chunk_text == "Government HR policy excerpt"
    assert r.citation.authority_level == row.authority_level
    assert r.citation.knowledge_source_name == "Civil Service Commission"
    assert r.citation.source_url == "https://example.gov.il/doc.pdf"
    assert r.citation.chunk_index == 0


@pytest.mark.asyncio
async def test_score_is_one_minus_distance():
    row = _make_row(distance=0.3)
    db = _make_db([row])

    results = await retrieve_chunks(db, "pension rules", uuid.uuid4())

    assert abs(results[0].score - 0.7) < 1e-6
    assert results[0].distance == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    db = _make_db([])
    results = await retrieve_chunks(db, "obscure query", uuid.uuid4())
    assert results == []


# ── min_score filter ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_min_score_filters_low_score_results():
    row_close = _make_row(distance=0.1)   # score=0.9
    row_far = _make_row(distance=0.8)     # score=0.2
    db = _make_db([row_close, row_far])

    results = await retrieve_chunks(db, "HR policy", uuid.uuid4(), min_score=0.5)

    assert len(results) == 1
    assert results[0].score >= 0.5


# ── Context type ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_context_type_passes():
    db = _make_db([_make_row()])
    for ct in ALLOWED_CONTEXT_TYPES:
        results = await retrieve_chunks(db, "query", uuid.uuid4(), context_type=ct)
        assert isinstance(results, list)


@pytest.mark.asyncio
async def test_context_type_none_passes():
    db = _make_db([_make_row()])
    results = await retrieve_chunks(db, "query", uuid.uuid4(), context_type=None)
    assert isinstance(results, list)


# ── Provider model name used ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_uses_provider_model_name_in_query():
    db = _make_db([])
    await retrieve_chunks(db, "query", uuid.uuid4())

    call_args = db.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params") or call_args[0][1]
    assert params["embedding_model"] == "fake-local-v1"


# ── Query text not in params ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_text_not_stored_in_sql_params():
    """query_text must not appear in SQL parameters — only its vector is passed."""
    db = _make_db([])
    query = "Sensitive HR recruitment query"
    await retrieve_chunks(db, query, uuid.uuid4())

    call_args = db.execute.call_args
    params = call_args[0][1]
    for v in params.values():
        assert query not in str(v), "query_text should not appear in SQL parameters"


# ── SQL param completeness ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_version_id_in_sql_params():
    """index_version_id must appear as a SQL parameter, not interpolated."""
    db = _make_db([])
    vid = uuid.uuid4()
    await retrieve_chunks(db, "query", vid)
    params = db.execute.call_args[0][1]
    assert params.get("index_version_id") == str(vid)


@pytest.mark.asyncio
async def test_context_type_param_and_null_fallback_sql():
    """When context_type is provided:
    - it must be passed as a SQL param (not interpolated)
    - the SQL must include OR ks.context_type IS NULL (null = general sources)
    """
    db = _make_db([])
    await retrieve_chunks(db, "query", uuid.uuid4(), context_type="government_ministries")
    call_args = db.execute.call_args
    params = call_args[0][1]
    sql_text = str(call_args[0][0])
    assert params.get("context_type") == "government_ministries"
    assert "ks.context_type IS NULL" in sql_text


# ── Citation builder ──────────────────────────────────────────────────────────

def test_build_citation_metadata_all_fields():
    citation = build_citation_metadata(
        chunk_index=3,
        section_title="Section 7",
        page_number=12,
        source_url="https://gov.il/policy.pdf",
        source_title="Leave Policy",
        document_type="pdf",
        knowledge_source_id="ks-uuid",
        knowledge_source_name="HR Commission",
        authority_level=2,
    )

    assert citation.chunk_index == 3
    assert citation.section_title == "Section 7"
    assert citation.page_number == 12
    assert citation.source_url == "https://gov.il/policy.pdf"
    assert citation.authority_level == 2
    assert citation.knowledge_source_name == "HR Commission"


def test_build_citation_metadata_nullable_fields():
    citation = build_citation_metadata(
        chunk_index=0,
        section_title=None,
        page_number=None,
        source_url=None,
        source_title=None,
        document_type=None,
        knowledge_source_id="ks-uuid",
        knowledge_source_name="General Source",
        authority_level=5,
    )

    assert citation.section_title is None
    assert citation.page_number is None
    assert citation.source_url is None
