"""Deterministic text chunker with paragraph-boundary preservation.

Strategy:
- Split on double-newlines (paragraph boundaries) where possible.
- If a paragraph exceeds max_chars, hard-split it.
- Consecutive chunks overlap by overlap_chars characters from the previous chunk.
- Each chunk gets a sha256 hash for deduplication.
- Token estimate: len(chunk_text) // 4 (rough approximation).
"""
from dataclasses import dataclass

from app.services.ingestion.hash_utils import sha256_hex


@dataclass
class Chunk:
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    token_estimate: int


def chunk_text(
    text: str,
    max_chars: int = 2000,
    overlap_chars: int = 200,
) -> list[Chunk]:
    """
    Split text into overlapping chunks, preserving paragraph boundaries.

    Returns an empty list for empty/whitespace-only input.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    raw_chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        if para_len > max_chars:
            # Flush current accumulation first
            if current:
                raw_chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            # Hard-split the oversized paragraph
            offset = 0
            while offset < para_len:
                raw_chunks.append(para[offset : offset + max_chars])
                offset += max_chars
            continue

        # Would adding this paragraph exceed the limit?
        separator_cost = 2 if current else 0  # "\n\n"
        if current_len + separator_cost + para_len > max_chars and current:
            raw_chunks.append("\n\n".join(current))
            current = []
            current_len = 0

        current.append(para)
        current_len += (2 if len(current) > 1 else 0) + para_len

    if current:
        raw_chunks.append("\n\n".join(current))

    # Apply overlap between consecutive chunks
    result: list[Chunk] = []
    for idx, chunk_str in enumerate(raw_chunks):
        if idx > 0 and overlap_chars > 0:
            prev = raw_chunks[idx - 1]
            overlap_tail = prev[-overlap_chars:] if len(prev) > overlap_chars else prev
            chunk_str = overlap_tail + "\n\n" + chunk_str

        chunk_str = chunk_str.strip()
        if not chunk_str:
            continue

        result.append(Chunk(
            chunk_index=len(result),
            chunk_text=chunk_str,
            chunk_hash=sha256_hex(chunk_str.encode("utf-8")),
            token_estimate=len(chunk_str) // 4,
        ))

    return result
