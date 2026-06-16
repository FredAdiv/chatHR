"""Expand source_documents status constraint to include 'processed'

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE source_documents DROP CONSTRAINT ck_source_documents_status")
    op.execute(
        "ALTER TABLE source_documents ADD CONSTRAINT ck_source_documents_status "
        "CHECK (status IN ('discovered', 'downloaded', 'unchanged', 'failed', 'deleted', 'processed'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE source_documents DROP CONSTRAINT ck_source_documents_status")
    op.execute(
        "ALTER TABLE source_documents ADD CONSTRAINT ck_source_documents_status "
        "CHECK (status IN ('discovered', 'downloaded', 'unchanged', 'failed', 'deleted'))"
    )
