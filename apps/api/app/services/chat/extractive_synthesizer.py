"""Local extractive synthesizer — deterministic MVP fallback.

No external calls, no OpenRouter, no LLM.
Extracts relevant text from the highest-ranked retrieved chunks.
Activated when the LLM Gateway returns fake-local/debug output, empty output, or fails.
"""
from __future__ import annotations

from app.services.retrieval.retriever import RetrievedChunk

_INTRO = "על בסיס המסמכים הרשמיים שנמצאו:"
_MAX_CHUNK_CHARS = 800
_MAX_CHUNKS = 2
_SYNTHESIS_FAILURE_MSG = (
    "נמצאו מקורות רלוונטיים, אך לא הצלחתי לנסח תשובה מקצועית בבטחה. "
    "להלן המקורות שנמצאו."
)

# Markers that indicate a fake-local/debug response rather than a genuine answer
_UNUSABLE_MARKERS = ("[fake-local]", "acknowledged")


def is_usable_llm_response(content: str) -> bool:
    """Return True only when LLM output is a genuine answer.

    Returns False for empty strings, fake-local acknowledgments, and debug output.
    """
    if not content or not content.strip():
        return False
    lower = content.lower()
    for marker in _UNUSABLE_MARKERS:
        if marker in lower:
            return False
    return True


def synthesize_answer(chunks: list[RetrievedChunk]) -> str:
    """Produce a grounded Hebrew answer extracted from the top retrieved chunks.

    - Uses chunk_text only — never invents content outside retrieved sources.
    - No external calls of any kind.
    - Always returns a non-empty string.
    """
    if not chunks:
        return _SYNTHESIS_FAILURE_MSG

    parts: list[str] = [_INTRO]
    for chunk in chunks[:_MAX_CHUNKS]:
        text = chunk.chunk_text.strip()
        if len(text) > _MAX_CHUNK_CHARS:
            text = text[:_MAX_CHUNK_CHARS] + "..."
        c = chunk.citation
        label_parts: list[str] = []
        if c.source_title:
            label_parts.append(c.source_title)
        if c.section_title:
            label_parts.append(f"— {c.section_title}")
        label = " ".join(label_parts) if label_parts else "מקור"
        parts.append(f"\n[{label}]\n{text}")

    return "\n".join(parts)
