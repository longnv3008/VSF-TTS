"""drop obsolete retry_of_job_id and failed_url from pipeline_jobs

Revision ID: 20260602_000007
Revises: 20260602_000006
Create Date: 2026-06-02 00:00:07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260602_000007"
down_revision = "20260602_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("pipeline_jobs", "failed_url")
    op.drop_column("pipeline_jobs", "retry_of_job_id")


def downgrade() -> None:
    op.add_column("pipeline_jobs", sa.Column("retry_of_job_id", sa.Integer(), nullable=True))
    op.add_column("pipeline_jobs", sa.Column("failed_url", sa.Text(), nullable=True))
