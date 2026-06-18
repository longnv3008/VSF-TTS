"""add translation_path to pipeline_jobs

Revision ID: 20260528_000003
Revises: 20260527_000002
Create Date: 2026-05-28 00:00:03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260528_000003"
down_revision = "20260527_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipeline_jobs", sa.Column("translation_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "translation_path")
