"""Add context_type to knowledge_sources

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = "('government_ministries', 'defense_system', 'health_system')"


def upgrade() -> None:
    op.add_column(
        "knowledge_sources",
        sa.Column("context_type", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_knowledge_sources_context_type",
        "knowledge_sources",
        f"context_type IS NULL OR context_type IN {_ALLOWED}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_knowledge_sources_context_type", "knowledge_sources", type_="check")
    op.drop_column("knowledge_sources", "context_type")
