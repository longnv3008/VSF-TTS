from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.audio_pipeline.application.exceptions import format_function_error
from app.modules.audio_pipeline.application.progress import compute_progress


def normalize_youtube_video_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    host = parsed.netloc.lower()

    if "youtu.be" in host:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif "youtube.com" in host:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
        elif parsed.path.startswith("/embed/"):
            video_id = parsed.path.split("/embed/", 1)[1].split("/", 1)[0]
        else:
            video_id = ""
    else:
        video_id = ""

    video_id = video_id.strip()
    if not video_id:
        raise ValueError(format_function_error("validate_urls", ValueError(f"Invalid YouTube video URL: {raw_url}")))

    return f"https://www.youtube.com/watch?v={video_id}"


class IngestRequest(BaseModel):
    # Payload FE gửi lên để tạo một job crawl audio mới.
    urls: list[str] = Field(min_length=1)
    batch_name: str = Field(default="batch_001")

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, urls: list[str]) -> list[str]:
        # Chuẩn hóa về đúng URL video đơn để không vô tình crawl cả playlist/mix context.
        cleaned_urls = [url.strip() for url in urls if url.strip()]
        if not cleaned_urls:
            raise ValueError(
                format_function_error("validate_urls", ValueError("At least one YouTube URL is required"))
            )

        try:
            normalized_urls: list[str] = []
            seen_urls: set[str] = set()
            for url in cleaned_urls:
                try:
                    normalized_url = normalize_youtube_video_url(url)
                except ValueError:
                    # Bỏ qua link lỗi để batch vẫn chạy được với các link hợp lệ còn lại.
                    continue
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                normalized_urls.append(normalized_url)
            if not normalized_urls:
                raise ValueError(
                    format_function_error("validate_urls", ValueError("No valid YouTube video URLs provided"))
                )
            return normalized_urls
        except Exception as exc:
            raise ValueError(format_function_error("validate_urls", exc)) from exc

    @field_validator("batch_name")
    @classmethod
    def validate_batch_name(cls, batch_name: str) -> str:
        # Loại bỏ khoảng trắng thừa để tên batch lưu xuống DB và filesystem nhất quán hơn.
        cleaned_batch_name = batch_name.strip()
        if not cleaned_batch_name:
            raise ValueError(
                format_function_error("validate_batch_name", ValueError("Batch name is required"))
            )
        return cleaned_batch_name


class UrlRead(BaseModel):
    url: str
    video_id: str
    status: str
    logs_fail: str | None = None
    source_duration_sec: float | None = None

    model_config = {"from_attributes": True}


class StepHistoryItem(BaseModel):
    step: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_sec: float | None = None

    @model_validator(mode="after")
    def _compute_duration(self) -> "StepHistoryItem":
        if self.started_at and self.ended_at:
            self.duration_sec = round((self.ended_at - self.started_at).total_seconds(), 2)
        return self


class JobRead(BaseModel):
    # Schema trả về cho FE khi đọc thông tin job.
    id: int
    batch_id: int
    batch_status: str
    job_type: str
    status: str
    current_step: str
    batch_name: str
    manifest_path: str | None = None
    metadata_path: str | None = None
    translation_path: str | None = None
    output_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    # Theo dõi tiến trình (dẫn xuất + dữ liệu sẵn có).
    step_history: list[StepHistoryItem] = Field(default_factory=list)
    urls: list[UrlRead] = Field(default_factory=list)
    url_summary: dict[str, int] = Field(default_factory=dict)
    progress_percent: int = 0
    progress_label: str = ""

    model_config = {"from_attributes": True}

    @field_validator("step_history", mode="before")
    @classmethod
    def _default_step_history(cls, value: object) -> object:
        return value or []

    @model_validator(mode="after")
    def _compute_progress_fields(self) -> "JobRead":
        counts = {"total": len(self.urls), "completed": 0, "failed": 0, "skipped": 0, "running": 0, "queued": 0}
        for item in self.urls:
            if item.status in counts:
                counts[item.status] += 1
        self.url_summary = counts
        self.progress_percent, self.progress_label = compute_progress(self.current_step, self.status, counts)
        return self


class BatchRead(BaseModel):
    id: int
    name: str
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class StageTimingItem(BaseModel):
    # Một dòng timing (stage cha khi sub_stage=None, hoặc sub-stage cụ thể).
    id: int
    job_id: int
    batch_id: int
    video_id: str = ""
    url: str | None = None
    stage: str
    sub_stage: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_sec: float | None = None
    status: str = "running"

    model_config = {"from_attributes": True}


class StageAggregate(BaseModel):
    # Tổng thời gian một stage/sub-stage trên toàn batch.
    stage: str
    sub_stage: str | None = None
    total_duration_sec: float = 0.0
    count: int = 0
    avg_duration_sec: float = 0.0


class VideoStageBreakdown(BaseModel):
    # Drill-down: từng video kèm danh sách stage/sub-stage của nó.
    video_id: str
    url: str | None = None
    stages: list[StageTimingItem] = Field(default_factory=list)


class BatchTimingSummary(BaseModel):
    # Một run trong lịch sử: per-stage totals + snapshot params để so sánh.
    batch_id: int
    batch_name: str
    created_at: datetime
    per_stage: list[StageAggregate] = Field(default_factory=list)
    total_duration_sec: float = 0.0
    params: dict = Field(default_factory=dict)


class BatchSegmentRead(BaseModel):
    batch_id: int
    batch_name: str
    audio_id: str
    video_id: str
    segment_id: str
    start: float = 0.0
    end: float = 0.0
    duration: float = 0.0
    text: str = ""
    transcript_source: str | None = None
    transcript_status: str | None = None
    quality_label: str | None = None
    quality_score: float | None = None
    source_url: str | None = None
    title: str | None = None
    audio_url: str
    audio_available: bool = False
