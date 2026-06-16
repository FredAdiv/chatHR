"""Add pgvector extension and chunk_embeddings table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Requires pgvector-enabled PostgreSQL (docker: pgvector/pgvector:pg16)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create table using raw SQL so the vector column type is handled correctly.
    # SQLAlchemy's create_table does not natively support pgvector types.
    op.execute("""
        CREATE TABLE chunk_embeddings (
            id              UUID        NOT NULL PRIMARY KEY,
            document_chunk_id UUID      NOT NULL REFERENCES document_chunks(id)  ON DELETE CASCADE,
            source_document_id UUID     NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
            parsed_document_id UUID     NOT NULL REFERENCES parsed_documents(id) ON DELETE CASCADE,
            index_version_id  UUID               REFERENCES index_versions(id)   ON DELETE SET NULL,
            embedding_model   TEXT      NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            embedding         vector   NOT NULL,
            content_hash      TEXT     NOT NULL,
            status            TEXT     NOT NULL,
            error_message     TEXT,
            metadata_json     JSONB,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_chunk_embeddings_status CHECK (status IN ('embedded', 'failed')),
            CONSTRAINT uq_chunk_embeddings_key
                UNIQUE (document_chunk_id, embedding_model, content_hash, index_version_id)
        )
    """)

    op.create_index("ix_chunk_embeddings_document_chunk_id", "chunk_embeddings", ["document_chunk_id"])
    op.create_index("ix_chunk_embeddings_source_document_id", "chunk_embeddings", ["source_document_id"])
    op.create_index("ix_chunk_embeddings_parsed_document_id", "chunk_embeddings", ["parsed_document_id"])
    op.create_index("ix_chunk_embeddings_index_version_id", "chunk_embeddings", ["index_version_id"])
    op.create_index("ix_chunk_embeddings_embedding_model", "chunk_embeddings", ["embedding_model"])
    # IVFFlat/HNSW vector index: add after data volume warrants it (requires min rows for IVFFlat).


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
