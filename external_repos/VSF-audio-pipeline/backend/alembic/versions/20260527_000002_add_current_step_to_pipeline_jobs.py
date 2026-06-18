"""add current step to pipeline jobs

Revision ID: 20260527_000002
Revises: 20260526_000001
Create Date: 2026-05-27 00:00:02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000002"
down_revision = "20260526_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("current_step", sa.String(length=100), nullable=False, server_default="queued"),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "current_step")
