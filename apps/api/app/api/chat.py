"""Chat API — user-facing endpoints for conversation and RAG answer flow.

Authorization: chat_user OR system_admin (server-side only).
Privacy guard runs before storing/retrieval/LLM for every user message.
No full prompts stored. No external model calls (fake-local only by default).
Only active index versions used for chat retrieval.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_any_role
from app.db.models.conversation import Conversation
from app.db.models.feedback import AnswerFeedback
from app.db.models.index_version import IndexVersion
from app.db.models.message import Message
from app.db.models.message_source import MessageSource
from app.db.session import get_db
from app.services.audit import record_audit_event
from app.services.chat.extractive_synthesizer import is_usable_llm_response, synthesize_answer
from app.services.chat.prompt_builder import build_chat_prompt, no_source_answer
from app.services.guardrails.input_guard import check_feedback_comment, check_user_input
from app.services.llm_gateway.gateway import generate_with_gateway
from app.services.llm_gateway.protocol import LLMProviderError, PrivacyGuardBlockedError
from app.services.privacy.guard import check_text
from app.services.retrieval.retriever import retrieve_chunks

router = APIRouter(prefix="/chat", tags=["chat"])

_CHAT_ROLES = ["chat_user", "system_admin"]

# ── Schemas ───────────────────────────────────────────────────────────────────

ContextType = Literal["government_ministries", "defense_system", "health_system"]


class CreateConversationRequest(BaseModel):
    context_type: ContextType
    title: str | None = Field(None, max_length=500)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    context_type: str
    title: str | None
    created_at: str

    @classmethod
    def from_orm(cls, c: Conversation) -> "ConversationResponse":
        return cls(
            id=c.id,
            context_type=c.context_type,
            title=c.title,
            created_at=c.created_at.isoformat(),
        )


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: str

    @classmethod
    def from_orm(cls, m: Message) -> "MessageResponse":
        return cls(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat(),
        )


class ConversationDetailResponse(BaseModel):
    id: uuid.UUID
    context_type: str
    title: str | None
    created_at: str
    messages: list[MessageResponse]


class CitationResponse(BaseModel):
    chunk_id: str
    source_document_id: str
    knowledge_source_id: str
    knowledge_source_name: str
    authority_level: int
    source_title: str | None
    source_url: str | None
    section_title: str | None
    page_number: int | None
    document_type: str | None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    index_version_id: uuid.UUID | None = None
    limit: int = Field(default=5, ge=1, le=10)


class SendMessageResponse(BaseModel):
    message: MessageResponse
    sources: list[CitationResponse]
    retrieval_count: int


class FeedbackRequest(BaseModel):
    rating: Literal["positive", "negative"]
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    rating: str


class PrivacyFindingSummary(BaseModel):
    type: str
    severity: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_active_index_version(db: AsyncSession) -> IndexVersion | None:
    result = await db.execute(
        select(IndexVersion).where(IndexVersion.status == "active")
    )
    return result.scalar_one_or_none()


async def _get_conversation_for_user(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


def _build_privacy_block_response(guard_result: Any) -> dict:
    findings = [
        {"type": f.type, "severity": f.severity}
        for f in guard_result.findings
        if f.severity == "high"
    ]
    return {
        "error": "privacy_guard_blocked",
        "reason": guard_result.reason or "High-severity PII detected.",
        "findings": findings,
    }


def _build_guardrail_block_response(guardrail_result: Any) -> dict:
    return {
        "error": "guardrail_blocked",
        "category": guardrail_result.category,
        "public_message": guardrail_result.public_message,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationResponse)
async def create_conversation(
    body: CreateConversationRequest,
    current_user=Depends(require_any_role(_CHAT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    conv = Conversation(
        user_id=current_user.id,
        context_type=body.context_type,
        title=body.title,
    )
    db.add(conv)
    await db.flush()
    await record_audit_event(
        db,
        action="conversation_created",
        actor_user_id=current_user.id,
        target_type="conversation",
        target_id=str(conv.id),
        metadata_json={"context_type": body.context_type},
    )
    await db.commit()
    await db.refresh(conv)
    return ConversationResponse.from_orm(conv)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user=Depends(require_any_role(_CHAT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    convs = result.scalars().all()
    return [ConversationResponse.from_orm(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user=Depends(require_any_role(_CHAT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    conv = await _get_conversation_for_user(conversation_id, current_user.id, db)

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()

    return ConversationDetailResponse(
        id=conv.id,
        context_type=conv.context_type,
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        messages=[MessageResponse.from_orm(m) for m in messages],
    )


@router.post("/conversations/{conversation_id}/messages", response_model=SendMessageResponse)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    current_user=Depends(require_any_role(_CHAT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> SendMessageResponse:
    conv = await _get_conversation_for_user(conversation_id, current_user.id, db)

    # 1. Privacy guard on user content — BEFORE storing or any downstream call
    guard_result = check_text(body.content)
    if not guard_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_build_privacy_block_response(guard_result),
        )

    # 1b. Product guardrails — after privacy, before storing
    input_guard_result = check_user_input(body.content)
    if not input_guard_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_build_guardrail_block_response(input_guard_result),
        )

    # 2. Resolve index version
    if body.index_version_id is not None:
        iv_result = await db.execute(
            select(IndexVersion).where(
                IndexVersion.id == body.index_version_id,
                IndexVersion.status == "active",
            )
        )
        index_version = iv_result.scalar_one_or_none()
        if index_version is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Requested index version is not active or does not exist.",
            )
    else:
        index_version = await _get_active_index_version(db)
        if index_version is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No active knowledge index available. Please try again later.",
            )

    # 3. Store user message (privacy guard passed)
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.flush()

    # 4. Retrieve relevant chunks
    try:
        chunks = await retrieve_chunks(
            db=db,
            query_text=body.content,
            index_version_id=index_version.id,
            context_type=conv.context_type,
            limit=body.limit,
        )
    except Exception:
        chunks = []

    # 5. No sources → safe refusal, no LLM call
    if not chunks:
        refusal_text = no_source_answer()
        assistant_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=refusal_text,
            metadata_json={
                "answer_mode": "no_sources",
                "retrieval_count": 0,
                "index_version_id": str(index_version.id),
            },
        )
        db.add(assistant_msg)
        await db.commit()
        await db.refresh(assistant_msg)

        return SendMessageResponse(
            message=MessageResponse.from_orm(assistant_msg),
            sources=[],
            retrieval_count=0,
        )

    # 6. Build transient prompt (never stored)
    messages_for_llm = build_chat_prompt(
        user_question=body.content,
        retrieval_results=chunks,
        context_type=conv.context_type,
    )

    # 7. Call LLM Gateway; fall back to local extractive synthesizer when unavailable
    try:
        llm_response = await generate_with_gateway(
            messages=messages_for_llm,
            purpose="chat_answer",
            user_id=current_user.id,
            db=db,
        )
        answer_content = llm_response.content
    except PrivacyGuardBlockedError:
        # Assembled prompt triggered privacy guard — return safe refusal
        answer_content = no_source_answer()
        chunks = []
    except LLMProviderError:
        # All providers failed — fall through to local synthesizer below
        answer_content = ""

    # 7b. If LLM returned unusable debug/fake-local output, use local extractive synthesizer
    if chunks and not is_usable_llm_response(answer_content):
        answer_content = synthesize_answer(chunks)

    source_chunk_ids = [c.chunk_id for c in chunks]

    # 8. Store assistant message with safe metadata only
    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=answer_content,
        metadata_json={
            "answer_mode": "retrieval_augmented" if chunks else "no_sources",
            "retrieval_count": len(chunks),
            "source_chunk_ids": source_chunk_ids,
            "index_version_id": str(index_version.id),
        },
    )
    db.add(assistant_msg)
    await db.flush()

    # 9. Store MessageSource rows
    citation_list: list[CitationResponse] = []
    for chunk in chunks:
        c = chunk.citation
        citation_data: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "knowledge_source_id": c.knowledge_source_id,
            "knowledge_source_name": c.knowledge_source_name,
            "authority_level": c.authority_level,
            "source_title": c.source_title,
            "source_url": c.source_url,
            "section_title": c.section_title,
            "page_number": c.page_number,
            "document_type": c.document_type,
        }
        ms = MessageSource(
            message_id=assistant_msg.id,
            document_chunk_id=uuid.UUID(chunk.chunk_id) if chunk.chunk_id else None,
            source_document_id=uuid.UUID(chunk.source_document_id) if chunk.source_document_id else None,
            knowledge_source_id=uuid.UUID(c.knowledge_source_id) if c.knowledge_source_id else None,
            citation_json=citation_data,
        )
        db.add(ms)
        citation_list.append(CitationResponse(
            chunk_id=chunk.chunk_id,
            source_document_id=chunk.source_document_id,
            knowledge_source_id=c.knowledge_source_id,
            knowledge_source_name=c.knowledge_source_name,
            authority_level=c.authority_level,
            source_title=c.source_title,
            source_url=c.source_url,
            section_title=c.section_title,
            page_number=c.page_number,
            document_type=c.document_type,
        ))

    await db.commit()
    await db.refresh(assistant_msg)

    return SendMessageResponse(
        message=MessageResponse.from_orm(assistant_msg),
        sources=citation_list,
        retrieval_count=len(chunks),
    )


@router.post("/messages/{message_id}/feedback", status_code=status.HTTP_201_CREATED, response_model=FeedbackResponse)
async def submit_feedback(
    message_id: uuid.UUID,
    body: FeedbackRequest,
    current_user=Depends(require_any_role(_CHAT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    # Privacy guard on optional comment
    if body.comment:
        guard_result = check_text(body.comment)
        if not guard_result.allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_build_privacy_block_response(guard_result),
            )
        # Inappropriate content check on feedback comment (scope check does not apply)
        feedback_guard_result = check_feedback_comment(body.comment)
        if not feedback_guard_result.allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_build_guardrail_block_response(feedback_guard_result),
            )

    # Load message and verify ownership via conversation
    msg_result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    message = msg_result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == message.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if message.role != "assistant":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Feedback can only be submitted for assistant messages.",
        )

    feedback = AnswerFeedback(
        message_id=message.id,
        user_id=current_user.id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(feedback)
    await db.flush()
    await record_audit_event(
        db,
        action="feedback_submitted",
        actor_user_id=current_user.id,
        target_type="message",
        target_id=str(message.id),
        metadata_json={"rating": body.rating},
    )
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        rating=feedback.rating,
    )
