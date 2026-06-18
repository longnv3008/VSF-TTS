from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PipelineBatch(Base):
    # Bảng batch cha để gom nhiều job con của cùng một lần ingest lớn.
    __tablename__ = "pipeline_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    jobs: Mapped[list["PipelineJob"]] = relationship(back_populates="batch")


class PipelineJob(Base):
    # Bảng lưu trạng thái và artifact path của từng job pipeline.
    __tablename__ = "pipeline_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(50), default="youtube_ingest")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    current_step: Mapped[str] = mapped_column(String(100), default="queued")
    batch_id: Mapped[int] = mapped_column(ForeignKey("pipeline_batches.id"), index=True)
    manifest_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    translation_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Snapshot tham số chạy (threshold/min_volume/demucs/...) để so sánh giữa các run.
    run_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    batch: Mapped[PipelineBatch] = relationship(back_populates="jobs")
    urls: Mapped[list["PipelineJobUrl"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="PipelineJobUrl.id",
    )
    timings: Mapped[list["PipelineStageTiming"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="PipelineStageTiming.id",
    )

    @property
    def batch_name(self) -> str:
        return self.batch.name if self.batch else ""

    @property
    def batch_status(self) -> str:
        return self.batch.status if self.batch else ""


class PipelineJobUrl(Base):
    # Mỗi URL của job được theo dõi riêng để retry/resume không cần cắt mảng JSON.
    __tablename__ = "pipeline_job_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("pipeline_jobs.id"), index=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    logs_fail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Độ dài audio gốc (giây) sau khi crawl/normalize -> hiển thị phút trên UI.
    source_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    job: Mapped[PipelineJob] = relationship(back_populates="urls")


class PipelineStageTiming(Base):
    # Một dòng = wall-clock của một stage hoặc sub-stage cho một video.
    # Append-only (không bị reset như step_history) -> phục vụ aggregate/per-video/history.
    __tablename__ = "pipeline_stage_timings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("pipeline_jobs.id"), index=True)
    batch_id: Mapped[int] = mapped_column(Integer, index=True)
    video_id: Mapped[str] = mapped_column(String(50), default="", index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(String(50), index=True)
    # None = dòng stage cha; "demucs"/"vad"/"asr"/"cut" = sub-stage.
    sub_stage: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[PipelineJob] = relationship(back_populates="timings")
