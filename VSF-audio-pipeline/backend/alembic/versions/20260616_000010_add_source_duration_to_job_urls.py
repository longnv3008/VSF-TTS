"""add source_duration_sec to pipeline_job_urls

Revision ID: 20260616_000010
Revises: 20260616_000009
Create Date: 2026-06-16 00:00:10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260616_000010"
down_revision = "20260616_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_job_urls",
        sa.Column("source_duration_sec", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_job_urls", "source_duration_sec")
