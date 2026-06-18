"""create pipeline batches table

Revision ID: 20260529_000005
Revises: 20260528_000004
Create Date: 2026-05-29 00:00:05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260529_000005"
down_revision = "20260528_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
    )
    op.create_index("ix_pipeline_batches_id", "pipeline_batches", ["id"], unique=False)

    op.add_column("pipeline_jobs", sa.Column("batch_id", sa.Integer(), nullable=True))
    op.create_index("ix_pipeline_jobs_batch_id", "pipeline_jobs", ["batch_id"], unique=False)
    op.create_foreign_key(
        "fk_pipeline_jobs_batch_id_pipeline_batches",
        "pipeline_jobs",
        "pipeline_batches",
        ["batch_id"],
        ["id"],
    )

    connection = op.get_bind()
    batch_rows = connection.execute(sa.text("SELECT DISTINCT batch_name FROM pipeline_jobs")).fetchall()
    for row in batch_rows:
        batch_name = row[0]
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO pipeline_batches (name, status)
                VALUES (:name, 'queued')
                RETURNING id
                """
            ),
            {"name": batch_name},
        ).fetchone()
        connection.execute(
            sa.text("UPDATE pipeline_jobs SET batch_id = :batch_id WHERE batch_name = :batch_name"),
            {"batch_id": inserted[0], "batch_name": batch_name},
        )

    op.alter_column("pipeline_jobs", "batch_id", nullable=False)
    op.drop_column("pipeline_jobs", "batch_name")


def downgrade() -> None:
    op.add_column("pipeline_jobs", sa.Column("batch_name", sa.String(length=255), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE pipeline_jobs
            SET batch_name = pipeline_batches.name
            FROM pipeline_batches
            WHERE pipeline_jobs.batch_id = pipeline_batches.id
            """
        )
    )

    op.alter_column("pipeline_jobs", "batch_name", nullable=False)
    op.drop_constraint("fk_pipeline_jobs_batch_id_pipeline_batches", "pipeline_jobs", type_="foreignkey")
    op.drop_index("ix_pipeline_jobs_batch_id", table_name="pipeline_jobs")
    op.drop_column("pipeline_jobs", "batch_id")
    op.drop_index("ix_pipeline_batches_id", table_name="pipeline_batches")
    op.drop_table("pipeline_batches")
