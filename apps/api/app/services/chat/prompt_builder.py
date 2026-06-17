"""Chat prompt assembly — builds transient LLM messages from user question + retrieval results.

The assembled prompt is NEVER persisted. No full prompt content is stored in DB or audit logs.
Only source IDs and citation labels appear in the prompt as structural markers.
"""
from __future__ import annotations

from app.services.llm_gateway.protocol import LLMMessage
from app.services.retrieval.retriever import RetrievedChunk

_SYSTEM_INSTRUCTIONS = (
    "אתה עוזר מקצועי לעובדי HR בשירות המדינה הישראלי. "
    "ענה **רק** על סמך המקורות הרשמיים שסופקו להלן — אין להשתמש בידע כללי, באינטרנט או במקורות חיצוניים. "
    "אם המקורות אינם מספיקים לתשובה ברורה, ציין: 'לא נמצא מקור רשמי מספיק ברור'. "
    "אל תחפש מידע באינטרנט ואל תפנה למקורות מחוץ למסמכים שסופקו. "
    "סרב בנימוס לשאלות שאינן קשורות לעבודת HR בשירות המדינה או לבקשות לא הולמות. "
    "אין לעבד פרטים מזהים אישיים (תעודת זהות, טלפון, כתובת מייל וכדומה). "
    "אל תספק החלטות משפטיות או HR אישיות מחייבות — צרף הפניות למקורות והמלץ לפנות לגורם מוסמך. "
    "צרף הפניה למקור עבור כל עובדה שאתה מציין.\n\n"
    "החזר את תשובתך **בפורמט JSON בלבד** (ללא טקסט נוסף מחוץ ל-JSON). "
    "אל תעטוף את ה-JSON בגדרות קוד markdown (כגון ```json). "
    "אל תשתמש ב-HTML — אין תגי `<p>`, `<ul>`, `<li>`, `<br>`, `<b>` וכדומה. "
    "השתמש בטקסט עברי פשוט בלבד; פסקאות ורשימות מופרדות בשורות חדשות בלבד:\n"
    '{"answer_text":"<התשובה המלאה בעברית>",'
    '"answer_blocks":['
    '{"block_id":"b1","text":"<פסקה ראשונה>","citation_ids":["מקור 1"]},'
    '{"block_id":"b2","text":"<פסקה שנייה>","citation_ids":["מקור 2","מקור 3"]}'
    "]}\n"
    "ב-citation_ids ציין רק את מספרי המקורות הרלוונטיים לפסקה זו (בדיוק כפי שמופיעים: \"מקור 1\", \"מקור 2\" וכו׳). "
    "אל תכלול מקורות שלא הופיעו ברשימה."
)

_NO_SOURCE_ANSWER = "לא נמצא מקור רשמי מספיק ברור כדי לענות על השאלה."


def build_chat_prompt(
    user_question: str,
    retrieval_results: list[RetrievedChunk],
    context_type: str,
) -> list[LLMMessage]:
    """Assemble LLM messages for a RAG chat answer.

    - Never persisted — callers must not store the return value.
    - Document chunks are placed in the system message so that the privacy guard's
      full-name-in-HR-context check (which targets user input) does not trigger
      false positives on regulation text like "עובד הנותן שירות".
    - The user message contains only the user's question — no chunk text.
    - Includes chunk_text and citation labels, NOT chunk IDs as raw UUIDs in human-visible text.
    - Instruction is strict: answer only from provided sources.
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
    system_content = f"{_SYSTEM_INSTRUCTIONS}\n\nמקורות רשמיים:\n{sources_text}"

    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content=f"שאלה: {user_question}"),
    ]


def no_source_answer() -> str:
    return _NO_SOURCE_ANSWER
