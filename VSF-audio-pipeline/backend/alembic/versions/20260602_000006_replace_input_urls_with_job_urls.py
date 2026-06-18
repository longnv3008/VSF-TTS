"""replace input_urls with pipeline_job_urls

Revision ID: 20260602_000006
Revises: 20260529_000005
Create Date: 2026-06-02 00:00:06
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from alembic import op
import sqlalchemy as sa


revision = "20260602_000006"
down_revision = "20260529_000005"
branch_labels = None
depends_on = None


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.netloc.lower().endswith("youtu.be"):
        return parsed.path.strip("/").split("/", 1)[0]
    return parse_qs(parsed.query).get("v", [""])[0].strip()


def upgrade() -> None:
    op.create_table(
        "pipeline_job_urls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=50), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("logs_fail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["job_id"], ["pipeline_jobs.id"], name="fk_pipeline_job_urls_job_id_pipeline_jobs"),
    )
    op.create_index("ix_pipeline_job_urls_id", "pipeline_job_urls", ["id"], unique=False)
    op.create_index("ix_pipeline_job_urls_job_id", "pipeline_job_urls", ["job_id"], unique=False)
    op.create_index("ix_pipeline_job_urls_video_id", "pipeline_job_urls", ["video_id"], unique=False)
    op.create_index("ix_pipeline_job_urls_status", "pipeline_job_urls", ["status"], unique=False)

    connection = op.get_bind()
    job_rows = connection.execute(
        sa.text("SELECT id, input_urls, status, failed_url FROM pipeline_jobs ORDER BY id")
    ).fetchall()
    for row in job_rows:
        urls = json.loads(row.input_urls or "[]")
        failed_found = False
        for url in urls:
            video_id = _extract_video_id(url)
            if not video_id:
                continue

            url_status = "queued"
            if row.status == "completed":
                url_status = "completed"
            elif row.status == "failed":
                if row.failed_url and url == row.failed_url and not failed_found:
                    url_status = "failed"
                    failed_found = True
                else:
                    url_status = "queued"
            elif row.status == "running":
                url_status = "running"
            elif row.status == "blocked":
                url_status = "queued"

            connection.execute(
                sa.text(
                    """
                    INSERT INTO pipeline_job_urls (job_id, video_id, url, status, logs_fail)
                    VALUES (:job_id, :video_id, :url, :status, :logs_fail)
                    """
                ),
                {
                    "job_id": row.id,
                    "video_id": video_id,
                    "url": url,
                    "status": url_status,
                    "logs_fail": row.failed_url if url_status == "failed" else None,
                },
            )

    op.drop_column("pipeline_jobs", "input_urls")


def downgrade() -> None:
    op.add_column("pipeline_jobs", sa.Column("input_urls", sa.Text(), nullable=True))

    connection = op.get_bind()
    job_rows = connection.execute(sa.text("SELECT id FROM pipeline_jobs ORDER BY id")).fetchall()
    for row in job_rows:
        urls = connection.execute(
            sa.text(
                """
                SELECT url
                FROM pipeline_job_urls
                WHERE job_id = :job_id
                ORDER BY id
                """
            ),
            {"job_id": row.id},
        ).fetchall()
        connection.execute(
            sa.text("UPDATE pipeline_jobs SET input_urls = :input_urls WHERE id = :job_id"),
            {"job_id": row.id, "input_urls": json.dumps([item.url for item in urls], ensure_ascii=False)},
        )

    op.alter_column("pipeline_jobs", "input_urls", nullable=False)
    op.drop_index("ix_pipeline_job_urls_status", table_name="pipeline_job_urls")
    op.drop_index("ix_pipeline_job_urls_video_id", table_name="pipeline_job_urls")
    op.drop_index("ix_pipeline_job_urls_job_id", table_name="pipeline_job_urls")
    op.drop_index("ix_pipeline_job_urls_id", table_name="pipeline_job_urls")
    op.drop_table("pipeline_job_urls")
