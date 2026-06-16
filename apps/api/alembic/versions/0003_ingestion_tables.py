"""Add ingestion tables: source_documents, ingestion_runs, ingestion_run_documents

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- source_documents ---
    op.create_table(
        "source_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("document_type", sa.Text(), nullable=True),
        sa.Column("source_etag", sa.Text(), nullable=True),
        sa.Column("source_last_modified", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("storage_bucket", sa.Text(), nullable=True),
        sa.Column("storage_object_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("knowledge_source_id", "url", name="uq_source_documents_source_url"),
        sa.CheckConstraint(
            "status IN ('discovered', 'downloaded', 'unchanged', 'failed', 'deleted')",
            name="ck_source_documents_status",
        ),
    )
    op.create_index("ix_source_documents_knowledge_source_id", "source_documents", ["knowledge_source_id"])
    op.create_index("ix_source_documents_content_hash", "source_documents", ["content_hash"])

    # --- ingestion_runs ---
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "index_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("index_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ingestion_runs_status",
        ),
        sa.CheckConstraint(
            "mode IN ('dry_run', 'metadata_only', 'download')",
            name="ck_ingestion_runs_mode",
        ),
    )
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    # --- ingestion_run_documents ---
    op.create_table(
        "ingestion_run_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ingestion_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action IN ('discovered', 'downloaded', 'unchanged', 'failed', 'skipped')",
            name="ck_ingestion_run_documents_action",
        ),
    )
    op.create_index("ix_ingestion_run_documents_ingestion_run_id", "ingestion_run_documents", ["ingestion_run_id"])


def downgrade() -> None:
    op.drop_table("ingestion_run_documents")
    op.drop_table("ingestion_runs")
    op.drop_table("source_documents")
