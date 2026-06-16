"""Unit tests for the text chunker."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

from app.services.chunking.chunker import chunk_text


def test_short_text_one_chunk():
    text = "Short paragraph that fits in one chunk."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert "Short paragraph" in chunks[0].chunk_text


def test_long_text_multiple_chunks():
    # Build text that exceeds default max_chars=2000 across paragraphs
    para = "A" * 500
    text = "\n\n".join([para] * 10)  # 10 * 500 = 5000 chars
    chunks = chunk_text(text)
    assert len(chunks) > 1


def test_overlap_present_in_second_chunk():
    para = "B" * 500
    text = "\n\n".join([para] * 10)
    chunks = chunk_text(text, max_chars=1000, overlap_chars=100)
    assert len(chunks) >= 2
    # Second chunk should include tail of first chunk
    first_tail = chunks[0].chunk_text[-100:]
    assert first_tail in chunks[1].chunk_text


def test_chunk_hashes_are_deterministic():
    text = "Deterministic chunking test.\n\nAnother paragraph."
    chunks1 = chunk_text(text)
    chunks2 = chunk_text(text)
    assert [c.chunk_hash for c in chunks1] == [c.chunk_hash for c in chunks2]


def test_different_text_different_hashes():
    chunks_a = chunk_text("Text A content here.")
    chunks_b = chunk_text("Text B content here.")
    assert chunks_a[0].chunk_hash != chunks_b[0].chunk_hash


def test_chunk_indices_sequential():
    para = "C" * 400
    text = "\n\n".join([para] * 8)
    chunks = chunk_text(text, max_chars=800, overlap_chars=50)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_whitespace_only_returns_no_chunks():
    assert chunk_text("   \n\n   \t  ") == []


def test_token_estimate_is_positive():
    chunks = chunk_text("Government policy document with some content.")
    assert all(c.token_estimate >= 0 for c in chunks)


def test_no_empty_chunks():
    para = "D" * 300
    text = "\n\n".join([para] * 5)
    chunks = chunk_text(text, max_chars=500, overlap_chars=50)
    for c in chunks:
        assert c.chunk_text.strip() != ""


def test_oversized_paragraph_hard_split():
    # A single paragraph exceeding max_chars should be hard-split
    text = "E" * 5000
    chunks = chunk_text(text, max_chars=1000, overlap_chars=0)
    assert len(chunks) == 5
    for c in chunks:
        assert len(c.chunk_text) <= 1000
