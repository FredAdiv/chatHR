"""Add 'draft' status to index_versions status constraint.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-16
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE index_versions DROP CONSTRAINT ck_index_versions_status")
    op.execute(
        "ALTER TABLE index_versions ADD CONSTRAINT ck_index_versions_status "
        "CHECK (status IN ('building', 'draft', 'quality_check_failed', 'ready', 'active', 'archived'))"
    )


def downgrade():
    op.execute("ALTER TABLE index_versions DROP CONSTRAINT ck_index_versions_status")
    op.execute(
        "ALTER TABLE index_versions ADD CONSTRAINT ck_index_versions_status "
        "CHECK (status IN ('building', 'quality_check_failed', 'ready', 'active', 'archived'))"
    )
