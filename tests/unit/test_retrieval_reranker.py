"""Tests for the deterministic lexical reranker used in hybrid retrieval.

Covers:
- normalize_hebrew_text: geresh/gershayim/nikud normalization
- keyword_overlap_score: stop-word filtering, fraction matching
- rerank_candidates: combines distance + lexical boost
- Applicability chunk promotion over semantically-similar wrong sections
- Authority hierarchy preserved after reranking
- Spelling variant matching (התקשיר vs התקשי''ר vs התקשי"ר)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.retrieval.reranker import (
    normalize_hebrew_text,
    keyword_overlap_score,
    rerank_candidates,
)
from app.services.retrieval.retriever import RetrievedChunk
from app.services.retrieval.citation import CitationMetadata


def _make_citation(authority_level: int = 1) -> CitationMetadata:
    return CitationMetadata(
        chunk_index=0,
        section_title=None,
        page_number=None,
        source_url=None,
        source_title="תקשיר",
        document_type="pdf",
        knowledge_source_id=str(uuid.uuid4()),
        knowledge_source_name="Civil Service Commission",
        authority_level=authority_level,
    )


def _chunk(text: str, distance: float, authority_level: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        chunk_text=text,
        parsed_document_id=str(uuid.uuid4()),
        source_document_id=str(uuid.uuid4()),
        distance=distance,
        score=max(0.0, 1.0 - distance),
        citation=_make_citation(authority_level),
    )


# ── normalize_hebrew_text ─────────────────────────────────────────────────────

def test_normalize_removes_geresh():
    assert "התקשיר" in normalize_hebrew_text("התקשי'ר")


def test_normalize_removes_gershayim():
    assert "התקשיר" in normalize_hebrew_text('התקשי"ר')


def test_normalize_removes_double_prime():
    assert "התקשיר" in normalize_hebrew_text("התקשי''ר")


def test_normalize_removes_hebrew_gershayim_char():
    # Hebrew gershayim U+05F4
    assert "התקשיר" in normalize_hebrew_text("התקשי״ר")


def test_normalize_lowercases_latin():
    result = normalize_hebrew_text("ABC")
    assert result == "abc"


def test_normalize_strips_nikud():
    # Bet with dagesh (U+05D1 + U+05BC)
    result = normalize_hebrew_text("בּ")
    assert result == "ב"


# ── keyword_overlap_score ─────────────────────────────────────────────────────

def test_overlap_full_match():
    query = "הוראות התקשיר"
    chunk = "הוראות התקשיר חלות על עובדים"
    score = keyword_overlap_score(query, chunk)
    assert score == 1.0


def test_overlap_partial_match():
    query = "הוראות חלות התקשיר"
    # only "הוראות" and "התקשיר" appear (not "חלות")... wait, "חלות" is not a stop word
    chunk = "הוראות התקשיר"
    score = keyword_overlap_score(query, chunk)
    assert 0.0 < score < 1.0


def test_overlap_no_match():
    query = "הוראות התקשיר"
    chunk = "נהלי גיוס עובדים חדשים"
    score = keyword_overlap_score(query, chunk)
    assert score == 0.0


def test_overlap_stop_words_filtered():
    # "על מי" are stop words — should not count as keywords
    query = "על מי"
    chunk = "ב ל מ"  # only stop words
    score = keyword_overlap_score(query, chunk)
    assert score == 0.0


def test_overlap_gershayim_variant_matches():
    # Query uses plain form, chunk has gershayim variant
    query = "הוראות התקשיר"
    chunk = 'הוראות התקשי"ר חלות על כל סוגי העובדים'
    score = keyword_overlap_score(query, chunk)
    assert score == 1.0


def test_overlap_geresh_variant_matches():
    query = "הוראות התקשיר"
    chunk = "הוראות התקשי''ר חלות"
    score = keyword_overlap_score(query, chunk)
    assert score == 1.0


# ── rerank_candidates ─────────────────────────────────────────────────────────

def test_rerank_promotes_keyword_match():
    """Chunk with worse vector distance but full keyword match should rank higher."""
    query = "הוראות התקשיר חלות"
    # Semantically closest but no keyword match
    top_semantic = _chunk("קצובת שהייה ולינה בחוץ-לארץ לעובדים", distance=0.46)
    # Less similar semantically but has all keywords
    applicability = _chunk(
        "01.02 - חלות התקשיר\n01.021 הוראות התקשיר חלות על כל סוגי העובדים",
        distance=0.55,
    )
    result = rerank_candidates(query, [top_semantic, applicability])
    assert result[0].chunk_text == applicability.chunk_text


def test_rerank_preserves_order_without_keywords():
    """When no chunk has keyword overlap, original vector order is preserved."""
    query = "הוראות התקשיר"
    chunk_a = _chunk("נהלי גיוס", distance=0.40)
    chunk_b = _chunk("טפסי אגרה", distance=0.50)
    result = rerank_candidates(query, [chunk_a, chunk_b])
    assert result[0].distance == 0.40
    assert result[1].distance == 0.50


def test_rerank_returns_all_candidates():
    query = "חלות הוראות"
    chunks = [_chunk(f"chunk {i}", distance=0.5 - i * 0.05) for i in range(5)]
    result = rerank_candidates(query, chunks)
    assert len(result) == 5


def test_rerank_empty_candidates():
    assert rerank_candidates("query", []) == []


def test_rerank_authority_level_preserved():
    """After reranking, authority_level is not altered."""
    query = "הוראות התקשיר"
    # high_auth has full keyword overlap (הוראות + התקשיר); low_auth has none
    high_auth = _chunk("הוראות התקשיר חלות", distance=0.55, authority_level=1)
    low_auth = _chunk("קצובת נסיעות לעובדים", distance=0.45, authority_level=4)
    result = rerank_candidates(query, [low_auth, high_auth])
    # high_auth combined = 0.55 - 0.15*1.0 = 0.40 < low_auth combined = 0.45 - 0 = 0.45
    assert result[0].citation.authority_level == 1


def test_rerank_applicability_vs_specific_section():
    """General applicability chunk outranks relocation-specific applicability chunk.

    Query keywords (after stop-word removal of 'על', 'מי'): חלות, הוראות, התקשיר (3 total).
    relocation has חלות + הוראות but NOT התקשיר → overlap 2/3 = 0.667
      combined = 0.52 - 0.15 * 0.667 = 0.42
    general has all three → overlap 1.0
      combined = 0.55 - 0.15 * 1.0 = 0.40 → wins
    """
    query = "על מי חלות הוראות התקשיר"
    # Specific section applicability (relocation chapter) — semantically similar but
    # lacks "התקשיר"; distance is 0.52 (semantic gap for missing the source name)
    relocation = _chunk(
        "הוראות פרק משנה זה חלות על עובד קבוע, זמני ועובד על-פי חוזה מיוחד (26.41)",
        distance=0.52,
    )
    # General Takshir applicability — weaker semantic but contains all query keywords
    general = _chunk(
        "01.02 - חלות התקשיר\n01.021 הוראות התקשיר חלות על כל סוגי העובדים בשירות המדינה",
        distance=0.55,
    )
    result = rerank_candidates(query, [relocation, general])
    assert result[0].chunk_text == general.chunk_text


def test_rerank_spelling_variant_query():
    """Query with gershayim variant of Takshir matches normalized chunk."""
    query = "על מי חלות הוראות התקשי״ר"
    chunk = _chunk(
        "הוראות התקשיר חלות על כל סוגי העובדים",
        distance=0.55,
    )
    other = _chunk("נהלי גיוס עובדים", distance=0.46)
    result = rerank_candidates(query, [other, chunk])
    assert result[0].chunk_text == chunk.chunk_text
