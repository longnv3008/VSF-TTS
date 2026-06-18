from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Iterator

from app.db.session import SessionLocal
from app.modules.audio_pipeline.application.job_events import publish_timing_event
from app.modules.audio_pipeline.domain.models import PipelineStageTiming
from app.utils import get_logger

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TimingHandle:
    # Tham chiếu tới một dòng timing đang mở để đóng lại sau.
    timing_id: int
    started_perf: float


def _publish(row: PipelineStageTiming) -> None:
    # SSE không được làm hỏng pipeline.
    try:
        publish_timing_event(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish_timing_event failed | %s", exc)


def open_timing(
    job_id: int | None,
    batch_id: int | None,
    stage: str,
    *,
    sub_stage: str | None = None,
    video_id: str = "",
    url: str | None = None,
) -> TimingHandle | None:
    # Mở dòng timing trạng thái running + đẩy SSE. job_id None -> bỏ qua (chạy ngoài DB).
    if job_id is None:
        return None
    db = SessionLocal()
    try:
        row = PipelineStageTiming(
            job_id=job_id,
            batch_id=batch_id or 0,
            stage=stage,
            sub_stage=sub_stage,
            video_id=video_id or "",
            url=url,
            started_at=_now(),
            status="running",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        _publish(row)
        return TimingHandle(timing_id=row.id, started_perf=perf_counter())
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("open_timing failed | stage=%s | %s", stage, exc)
        return None
    finally:
        db.close()


def close_timing(handle: TimingHandle | None, *, status: str = "completed") -> None:
    if handle is None:
        return
    db = SessionLocal()
    try:
        row = db.get(PipelineStageTiming, handle.timing_id)
        if row is None:
            return
        row.ended_at = _now()
        row.duration_sec = round(perf_counter() - handle.started_perf, 3)
        row.status = status
        db.add(row)
        db.commit()
        db.refresh(row)
        _publish(row)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("close_timing failed | %s", exc)
    finally:
        db.close()


def record_completed(
    job_id: int | None,
    batch_id: int | None,
    stage: str,
    *,
    sub_stage: str | None = None,
    video_id: str = "",
    url: str | None = None,
    duration_sec: float,
    status: str = "completed",
) -> None:
    # Ghi một dòng timing đã xong (dùng cho sub-stage tích lũy: cut/asr).
    if job_id is None:
        return
    db = SessionLocal()
    try:
        ended = _now()
        row = PipelineStageTiming(
            job_id=job_id,
            batch_id=batch_id or 0,
            stage=stage,
            sub_stage=sub_stage,
            video_id=video_id or "",
            url=url,
            started_at=ended - timedelta(seconds=max(0.0, duration_sec)),
            ended_at=ended,
            duration_sec=round(duration_sec, 3),
            status=status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        _publish(row)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("record_completed failed | stage=%s | %s", stage, exc)
    finally:
        db.close()


@contextmanager
def record_stage(
    job_id: int | None,
    batch_id: int | None,
    stage: str,
    *,
    sub_stage: str | None = None,
    video_id: str = "",
    url: str | None = None,
) -> Iterator[None]:
    # Span một stage/sub-stage: running -> completed/failed. Re-raise lỗi gốc.
    handle = open_timing(job_id, batch_id, stage, sub_stage=sub_stage, video_id=video_id, url=url)
    status = "completed"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        close_timing(handle, status=status)


@dataclass
class SegmentTimingSink:
    # Sink inject vào segment_video: ghi vad (span) + tích lũy cut/asr.
    # segment_video không import DB -> giữ thuần để unit test.
    job_id: int | None
    batch_id: int | None
    video_id: str = ""
    url: str | None = None
    _acc: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def span(self, sub_stage: str) -> Iterator[None]:
        with record_stage(
            self.job_id, self.batch_id, "segment_and_label",
            sub_stage=sub_stage, video_id=self.video_id, url=self.url,
        ):
            yield

    def add(self, sub_stage: str, duration_sec: float) -> None:
        self._acc[sub_stage] = self._acc.get(sub_stage, 0.0) + max(0.0, duration_sec)

    def flush(self) -> None:
        for sub_stage, total in self._acc.items():
            record_completed(
                self.job_id, self.batch_id, "segment_and_label",
                sub_stage=sub_stage, video_id=self.video_id, url=self.url,
                duration_sec=total,
            )
        self._acc.clear()
