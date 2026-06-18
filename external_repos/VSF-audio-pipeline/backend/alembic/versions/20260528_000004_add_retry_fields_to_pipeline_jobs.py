"""add retry fields to pipeline_jobs

Revision ID: 20260528_000004
Revises: 20260528_000003
Create Date: 2026-05-28 00:00:04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260528_000004"
down_revision = "20260528_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipeline_jobs", sa.Column("retry_of_job_id", sa.Integer(), nullable=True))
    op.add_column("pipeline_jobs", sa.Column("failed_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "failed_url")
    op.drop_column("pipeline_jobs", "retry_of_job_id")
