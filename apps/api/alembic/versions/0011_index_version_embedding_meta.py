"""Add embedding_provider and embedding_dimensions to index_versions.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("index_versions", sa.Column("embedding_provider", sa.String(50), nullable=True))
    op.add_column("index_versions", sa.Column("embedding_dimensions", sa.Integer, nullable=True))


def downgrade():
    op.drop_column("index_versions", "embedding_dimensions")
    op.drop_column("index_versions", "embedding_provider")
