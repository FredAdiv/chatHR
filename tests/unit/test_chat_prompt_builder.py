"""Chat prompt builder — unit tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid

from app.services.chat.prompt_builder import build_chat_prompt, no_source_answer
from app.services.retrieval.citation import CitationMetadata
from app.services.retrieval.retriever import RetrievedChunk


def _make_chunk(text="כאן תוכן הקטע.", title="מדיניות חופשה"):
    citation = CitationMetadata(
        source_url="https://example.gov.il/leave.pdf",
        source_title=title,
        knowledge_source_id=str(uuid.uuid4()),
        knowledge_source_name="נציבות שירות המדינה",
        authority_level=1,
        section_title=None,
        page_number=None,
        chunk_index=0,
        document_type="pdf",
    )
    return RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        chunk_text=text,
        parsed_document_id=str(uuid.uuid4()),
        source_document_id=str(uuid.uuid4()),
        distance=0.2,
        score=0.8,
        citation=citation,
    )


def test_prompt_has_system_and_user_messages():
    chunks = [_make_chunk()]
    messages = build_chat_prompt("מה מדיניות החופשות?", chunks, "government_ministries")
    roles = [m.role for m in messages]
    assert "system" in roles
    assert "user" in roles


def test_prompt_includes_chunk_text():
    # Chunks live in the system message (not user) to avoid privacy-guard
    # false positives on regulation text patterns.
    chunk_text = "ניתן לצבור עד 30 ימי חופשה שנתית."
    chunks = [_make_chunk(text=chunk_text)]
    messages = build_chat_prompt("שאלה?", chunks, "government_ministries")
    system_msg = next(m for m in messages if m.role == "system")
    assert chunk_text in system_msg.content


def test_prompt_includes_user_question():
    chunks = [_make_chunk()]
    question = "כמה ימי מחלה מגיעים לי?"
    messages = build_chat_prompt(question, chunks, "government_ministries")
    user_msg = next(m for m in messages if m.role == "user")
    assert question in user_msg.content


def test_prompt_instruction_is_strict():
    """System prompt must instruct to answer only from provided sources."""
    chunks = [_make_chunk()]
    messages = build_chat_prompt("שאלה?", chunks, "government_ministries")
    system_msg = next(m for m in messages if m.role == "system")
    assert "רק" in system_msg.content or "only" in system_msg.content.lower()


def test_prompt_is_deterministic():
    chunks = [_make_chunk(text="Fixed text")]
    m1 = build_chat_prompt("שאלה", chunks, "government_ministries")
    m2 = build_chat_prompt("שאלה", chunks, "government_ministries")
    assert m1[0].content == m2[0].content
    assert m1[1].content == m2[1].content


def test_no_source_answer_is_hebrew_string():
    answer = no_source_answer()
    assert isinstance(answer, str)
    assert len(answer) > 0
    assert "מקור" in answer or "לא" in answer
