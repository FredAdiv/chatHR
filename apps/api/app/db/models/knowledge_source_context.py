import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ALLOWED_CONTEXTS = (
    "government_ministries",
    "defense_system",
    "health_system",
    "general",
)

ALLOWED_CONTEXT_VALUES: frozenset[str] = frozenset(_ALLOWED_CONTEXTS)


class KnowledgeSourceContext(Base):
    __tablename__ = "knowledge_source_contexts"
    __table_args__ = (
        CheckConstraint(
            "context_type IN ('government_ministries', 'defense_system', 'health_system', 'general')",
            name="ck_ksc_context_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
