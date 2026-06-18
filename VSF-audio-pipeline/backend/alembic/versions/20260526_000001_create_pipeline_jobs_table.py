"""create pipeline jobs table

Revision ID: 20260526_000001
Revises:
Create Date: 2026-05-26 00:00:01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260526_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=50), nullable=False, server_default="youtube_ingest"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("input_urls", sa.Text(), nullable=False),
        sa.Column("batch_name", sa.String(length=255), nullable=False),
        sa.Column("manifest_path", sa.String(length=500), nullable=True),
        sa.Column("metadata_path", sa.String(length=500), nullable=True),
        sa.Column("output_path", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
    )
    op.create_index("ix_pipeline_jobs_id", "pipeline_jobs", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pipeline_jobs_id", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")
