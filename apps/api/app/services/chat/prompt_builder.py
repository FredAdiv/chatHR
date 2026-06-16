"""Chat prompt assembly — builds transient LLM messages from user question + retrieval results.

The assembled prompt is NEVER persisted. No full prompt content is stored in DB or audit logs.
Only source IDs and citation labels appear in the prompt as structural markers.
"""
from __future__ import annotations

from app.services.llm_gateway.protocol import LLMMessage
from app.services.retrieval.retriever import RetrievedChunk

_SYSTEM_TEMPLATE = (
    "אתה עוזר מקצועי לעובדי HR בשירות המדינה הישראלי. "
    "ענה **רק** על סמך המקורות הרשמיים שסופקו להלן. "
    "אם המקורות אינם מספיקים לתשובה ברורה, ציין: 'לא נמצא מקור רשמי מספיק ברור'. "
    "אל תשתמש בידע כללי מחוץ למקורות שניתנו. "
    "צרף הפניה למקור עבור כל עובדה שאתה מציין."
)

_NO_SOURCE_ANSWER = "לא נמצא מקור רשמי מספיק ברור כדי לענות על השאלה."


def build_chat_prompt(
    user_question: str,
    retrieval_results: list[RetrievedChunk],
    context_type: str,
) -> list[LLMMessage]:
    """Assemble LLM messages for a RAG chat answer.

    - Never persisted — callers must not store the return value.
    - Includes chunk_text and citation labels, NOT chunk IDs as raw UUIDs in human-visible text.
    - Instruction is strict: answer only from provided sources.
    - context_type is included for debugging/routing but NOT as user-visible text that leaks context.
    """
    source_blocks: list[str] = []
    for i, chunk in enumerate(retrieval_results, start=1):
        c = chunk.citation
        label_parts = []
        if c.source_title:
            label_parts.append(c.source_title)
        if c.knowledge_source_name:
            label_parts.append(f"({c.knowledge_source_name})")
        if c.section_title:
            label_parts.append(f"— {c.section_title}")
        label = " ".join(label_parts) if label_parts else f"מקור {i}"

        block = f"[מקור {i}] {label}\n{chunk.chunk_text}"
        source_blocks.append(block)

    sources_text = "\n\n".join(source_blocks)
    user_content = f"שאלה: {user_question}\n\nמקורות רשמיים:\n{sources_text}"

    return [
        LLMMessage(role="system", content=_SYSTEM_TEMPLATE),
        LLMMessage(role="user", content=user_content),
    ]


def no_source_answer() -> str:
    return _NO_SOURCE_ANSWER
