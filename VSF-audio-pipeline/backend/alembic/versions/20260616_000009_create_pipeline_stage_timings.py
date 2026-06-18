"""create pipeline_stage_timings + run_params

Revision ID: 20260616_000009
Revises: 20260615_000008
Create Date: 2026-06-16 00:00:09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260616_000009"
down_revision = "20260615_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("run_params", sa.JSON(), nullable=True),
    )
    op.create_table(
        "pipeline_stage_timings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("pipeline_jobs.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("sub_stage", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pipeline_stage_timings_id", "pipeline_stage_timings", ["id"])
    op.create_index("ix_pipeline_stage_timings_job_id", "pipeline_stage_timings", ["job_id"])
    op.create_index("ix_pipeline_stage_timings_batch_id", "pipeline_stage_timings", ["batch_id"])
    op.create_index("ix_pipeline_stage_timings_video_id", "pipeline_stage_timings", ["video_id"])
    op.create_index("ix_pipeline_stage_timings_stage", "pipeline_stage_timings", ["stage"])
    op.create_index("ix_pipeline_stage_timings_sub_stage", "pipeline_stage_timings", ["sub_stage"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_stage_timings_sub_stage", table_name="pipeline_stage_timings")
    op.drop_index("ix_pipeline_stage_timings_stage", table_name="pipeline_stage_timings")
    op.drop_index("ix_pipeline_stage_timings_video_id", table_name="pipeline_stage_timings")
    op.drop_index("ix_pipeline_stage_timings_batch_id", table_name="pipeline_stage_timings")
    op.drop_index("ix_pipeline_stage_timings_job_id", table_name="pipeline_stage_timings")
    op.drop_index("ix_pipeline_stage_timings_id", table_name="pipeline_stage_timings")
    op.drop_table("pipeline_stage_timings")
    op.drop_column("pipeline_jobs", "run_params")
