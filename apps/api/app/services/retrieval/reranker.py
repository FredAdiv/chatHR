"""Deterministic lexical reranker for Hebrew legal/HR text retrieval.

After vector search retrieves a candidate set, this reranker re-scores
candidates by combining vector distance with keyword overlap between the
query and chunk text. This improves retrieval for queries whose key terms
appear in the correct chunk but not as the dominant semantic signal
(e.g., applicability headers that appear in many Takshir chapters).

Design:
- No LLM calls, no external services, fully deterministic and testable.
- Normalizes Hebrew quotation marks (geresh/gershayim, maqaf) so that
  "התקשי''ר", "התקשי\"ר", and "התקשיר" all match each other.
- Filters common Hebrew function words before overlap counting.
- Combined score = vector_distance - lexical_weight * overlap_ratio
  (lower combined distance = higher rank, consistent with vector ordering).
"""
from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.retrieval.retriever import RetrievedChunk

# Common Hebrew function words to exclude from keyword matching.
# These appear everywhere and add noise to overlap scores.
_HE_STOP_WORDS: frozenset[str] = frozenset({
    "על", "מי", "של", "את", "הם", "הן", "הוא", "היא",
    "כי", "אם", "לא", "כל", "זה", "זו", "אלה", "אלו",
    "עם", "בין", "כן", "גם", "רק", "עד", "לפי", "אך",
    "ב", "ל", "מ", "ו", "כ", "ה",   # single-letter prepositions/articles
    "בכל", "לכל", "מכל", "כלל",
    "שם", "שם", "פה", "כן", "לו", "לה", "להם", "להן",
    "יש", "אין", "היו", "יהיו", "הוא", "היא",
    "שכן", "כן", "כך", "כאן", "שם",
    "לגבי", "בין", "אצל", "אחרי", "לפני", "בתוך",
    "א", "ב", "ג", "ד",  # parenthetical list markers
})

# Patterns that normalize Hebrew quotation variants to plain text
_GERESH_PATTERN = re.compile(r"[''׳`]")       # geresh and lookalikes
_GERSHAYIM_PATTERN = re.compile(r'["״]')       # gershayim and lookalikes
_MAQAF_PATTERN = re.compile(r"[‐‑‒–—֊-]+")   # various hyphen/maqaf
_WHITESPACE_PATTERN = re.compile(r"\s+")
_NON_ALPHA_PATTERN = re.compile(r"[^א-תA-Za-z0-9\s]")


def normalize_hebrew_text(text: str) -> str:
    """Normalize Hebrew punctuation variants for comparison.

    - Strips geresh/gershayim/maqaf so ״ר  ''ר  'ר all become ר
    - Removes diacritics (nikud)
    - Lowercases Latin, collapses whitespace
    """
    # Unicode normalize (e.g., strip combining chars like nikud)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _GERESH_PATTERN.sub("", text)
    text = _GERSHAYIM_PATTERN.sub("", text)
    text = _MAQAF_PATTERN.sub(" ", text)
    text = _NON_ALPHA_PATTERN.sub(" ", text)
    text = text.lower()
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    return text


def _query_keywords(query_text: str) -> list[str]:
    """Return meaningful keywords from query after normalization and stop-word removal."""
    normalized = normalize_hebrew_text(query_text)
    tokens = normalized.split()
    return [t for t in tokens if t and t not in _HE_STOP_WORDS and len(t) > 1]


def keyword_overlap_score(query_text: str, chunk_text: str) -> float:
    """Return fraction of query keywords found in chunk_text (0.0–1.0).

    Both texts are normalized before comparison so that geresh/gershayim
    variants of "התקשיר" match regardless of original punctuation.
    Returns 0.0 if there are no keywords (after stop-word removal).
    """
    keywords = _query_keywords(query_text)
    if not keywords:
        return 0.0
    normalized_chunk = normalize_hebrew_text(chunk_text)
    matches = sum(1 for kw in keywords if kw in normalized_chunk)
    return matches / len(keywords)


def rerank_candidates(
    query_text: str,
    candidates: list[RetrievedChunk],
    *,
    lexical_weight: float = 0.15,
) -> list[RetrievedChunk]:
    """Re-sort candidates by combining vector distance with lexical overlap.

    Combined distance = vector_distance - lexical_weight * overlap_ratio

    A chunk with full keyword overlap gets up to `lexical_weight` subtracted
    from its vector distance, boosting it relative to semantically similar
    but lexically mismatched chunks.

    The weight is intentionally modest (default 0.15) so that pure semantic
    retrieval remains the dominant signal; lexical overlap only breaks ties
    or rescues chunks whose embeddings are diluted by mixed content.
    """
    if not candidates:
        return candidates

    scored: list[tuple[float, RetrievedChunk]] = []
    for chunk in candidates:
        overlap = keyword_overlap_score(query_text, chunk.chunk_text)
        combined = chunk.distance - lexical_weight * overlap
        scored.append((combined, chunk))

    scored.sort(key=lambda t: t[0])
    return [chunk for _, chunk in scored]
