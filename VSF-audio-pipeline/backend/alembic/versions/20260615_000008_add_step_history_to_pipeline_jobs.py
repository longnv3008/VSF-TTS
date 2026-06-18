"""add step_history to pipeline jobs

Revision ID: 20260615_000008
Revises: 20260602_000007
Create Date: 2026-06-15 00:00:08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260615_000008"
down_revision = "20260602_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("step_history", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "step_history")
