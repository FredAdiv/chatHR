"""Add knowledge_source_contexts many-to-many table and backfill

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = "('government_ministries', 'defense_system', 'health_system', 'general')"


def upgrade() -> None:
    op.create_table(
        "knowledge_source_contexts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_source_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("context_type", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"context_type IN {_ALLOWED}",
            name="ck_ksc_context_type",
        ),
        sa.UniqueConstraint(
            "knowledge_source_id", "context_type",
            name="uq_ksc_source_context",
        ),
    )
    op.create_index(
        "ix_ksc_knowledge_source_id",
        "knowledge_source_contexts",
        ["knowledge_source_id"],
    )

    # Backfill: existing context_type values → explicit rows.
    # NULL context_type (was "applies to all") → 'general'.
    op.execute("""
        INSERT INTO knowledge_source_contexts (id, knowledge_source_id, context_type, created_at)
        SELECT
            gen_random_uuid(),
            id,
            CASE WHEN context_type IS NULL THEN 'general' ELSE context_type END,
            COALESCE(created_at, NOW())
        FROM knowledge_sources
        ON CONFLICT (knowledge_source_id, context_type) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_ksc_knowledge_source_id", table_name="knowledge_source_contexts")
    op.drop_table("knowledge_source_contexts")
