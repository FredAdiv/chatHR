import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('embedded', 'failed')",
            name="ck_chunk_embeddings_status",
        ),
        UniqueConstraint(
            "document_chunk_id", "embedding_model", "content_hash", "index_version_id",
            name="uq_chunk_embeddings_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    parsed_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parsed_documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    index_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("index_versions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # Vector stored without fixed dimension constraint to support configurable dimensions.
    # embedding_dimension field records the actual dimension of each row.
    embedding: Mapped[list] = mapped_column(Vector(), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
