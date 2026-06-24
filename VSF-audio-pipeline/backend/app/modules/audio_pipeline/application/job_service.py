from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy import desc, func, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.modules.audio_pipeline.api.schemas import IngestRequest
from app.modules.audio_pipeline.application.exceptions import AudioPipelineError, format_function_error
from app.modules.audio_pipeline.domain.models import (
    PipelineBatch,
    PipelineJob,
    PipelineJobUrl,
    PipelineStageTiming,
)
from app.utils.filesystem import read_csv
from app.utils import get_logger

logger = get_logger(__name__)
_DISCOVERY_ADVISORY_LOCK_KEY = 20260603


class PipelineJobService:
    # Service làm việc với batch cha và các job con của audio pipeline.
    def __init__(self, db: Session) -> None:
        self.db = db

    def _commit(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _extract_video_id(url: str) -> str:
        parsed = urlparse(url.strip())
        if parsed.netloc.lower().endswith("youtu.be"):
            return parsed.path.strip("/").split("/", 1)[0]
        return parse_qs(parsed.query).get("v", [""])[0].strip()

    @staticmethod
    def _chunk_urls(urls: list[str], chunk_size: int) -> list[list[str]]:
        safe_chunk_size = max(1, chunk_size)
        return [urls[index:index + safe_chunk_size] for index in range(0, len(urls), safe_chunk_size)]

    def _build_batch_status(self, jobs: list[PipelineJob]) -> str:
        statuses = {job.status for job in jobs}
        if not statuses:
            return "queued"
        if statuses == {"completed"}:
            return "completed"
        if "failed" in statuses:
            return "failed"
        if "running" in statuses:
            return "running"
        if "blocked" in statuses:
            return "blocked"
        if statuses == {"queued"}:
            return "queued"
        return "running"

    def _refresh_batch_status(self, batch_id: int) -> None:
        batch = self.get_batch(batch_id)
        batch.status = self._build_batch_status(batch.jobs)
        self.db.add(batch)
        self._commit()
        self.db.refresh(batch)

    def get_batch(self, batch_id: int) -> PipelineBatch:
        try:
            batch = (
                self.db.query(PipelineBatch)
                .options(selectinload(PipelineBatch.jobs))
                .filter(PipelineBatch.id == batch_id)
                .first()
            )
            if batch is None:
                raise AudioPipelineError(
                    format_function_error("get_batch", ValueError(f"Batch not found: {batch_id}")),
                    status_code=404,
                )
            return batch
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("get_batch", exc)
            logger.exception("%s | batch_id=%s", error_message, batch_id)
            raise AudioPipelineError(error_message) from exc

    def create_batch(self, name: str) -> PipelineBatch:
        try:
            batch = PipelineBatch(name=name, status="queued")
            self.db.add(batch)
            self._commit()
            self.db.refresh(batch)
            return batch
        except Exception as exc:
            error_message = format_function_error("create_batch", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def list_batches(self) -> list[PipelineBatch]:
        try:
            return list(
                self.db.query(PipelineBatch)
                .options(selectinload(PipelineBatch.jobs))
                .order_by(desc(PipelineBatch.created_at))
                .all()
            )
        except Exception as exc:
            error_message = format_function_error("list_batches", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    @staticmethod
    def _to_float(value: str | None) -> float:
        try:
            return round(float(value or 0.0), 3)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _segment_audio_url(batch_id: int, segment_id: str) -> str:
        return f"/api/v1/audio-pipeline/batches/{batch_id}/segments/{segment_id}/audio"

    @staticmethod
    def _resolve_audio_path(raw_path: str | None) -> Path | None:
        cleaned = (raw_path or "").strip()
        if not cleaned:
            return None

        candidate = Path(cleaned)
        candidates = [candidate]
        if candidate.is_absolute():
            try:
                relative_candidate = candidate.relative_to("/")
                candidates.append(Path.cwd() / relative_candidate)
            except ValueError:
                pass
        else:
            candidates.append(Path.cwd() / candidate)

        for item in candidates:
            try:
                if item.exists() and item.is_file():
                    return item.resolve()
            except OSError:
                continue
        return candidate if candidate.is_absolute() else (Path.cwd() / candidate)

    def _metadata_csv_path(self, batch_id: int) -> tuple[PipelineBatch, Path]:
        batch = self.get_batch(batch_id)
        return batch, settings.metadata_dir / f"{batch.name}_segments.csv"

    def list_batch_segments(self, batch_id: int, *, offset: int = 0, limit: int = 50) -> dict:
        try:
            batch, csv_path = self._metadata_csv_path(batch_id)
            normalized_offset = max(0, offset)
            normalized_limit = min(max(1, limit), 200)
            segments: list[dict] = []
            total = 0
            for row in read_csv(csv_path):
                segment_id = (row.get("segment_id") or "").strip()
                if not segment_id:
                    continue
                if total < normalized_offset:
                    total += 1
                    continue
                if len(segments) >= normalized_limit:
                    total += 1
                    continue
                audio_path = self._resolve_audio_path(row.get("segment_file"))
                segments.append(
                    {
                        "batch_id": batch.id,
                        "batch_name": batch.name,
                        "audio_id": row.get("audio_id", ""),
                        "video_id": row.get("video_id", ""),
                        "segment_id": segment_id,
                        "start": self._to_float(row.get("start")),
                        "end": self._to_float(row.get("end")),
                        "duration": self._to_float(row.get("duration")),
                        "text": row.get("text", ""),
                        "transcript_source": row.get("transcript_source"),
                        "transcript_status": row.get("transcript_status"),
                        "quality_label": row.get("quality_label"),
                        "quality_score": self._to_float(row.get("quality_score")) if row.get("quality_score") else None,
                        "source_url": row.get("source_url"),
                        "title": row.get("title"),
                        "audio_url": self._segment_audio_url(batch.id, segment_id),
                        "audio_available": bool(audio_path and audio_path.exists() and audio_path.is_file()),
                    }
                )
                total += 1
            if len(segments) < normalized_limit:
                total = normalized_offset + len(segments)
            return {
                "items": segments,
                "total": total,
                "offset": normalized_offset,
                "limit": normalized_limit,
                "has_more": normalized_offset + len(segments) < total,
            }
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("list_batch_segments", exc)
            logger.exception("%s | batch_id=%s", error_message, batch_id)
            raise AudioPipelineError(error_message) from exc

    def get_segment_audio_path(self, batch_id: int, segment_id: str) -> Path:
        try:
            _batch, csv_path = self._metadata_csv_path(batch_id)
            for row in read_csv(csv_path):
                if (row.get("segment_id") or "").strip() != segment_id:
                    continue
                audio_path = self._resolve_audio_path(row.get("segment_file"))
                if audio_path is None or not audio_path.exists() or not audio_path.is_file():
                    raise AudioPipelineError(
                        format_function_error(
                            "get_segment_audio_path",
                            FileNotFoundError(f"Segment audio not found: {segment_id}"),
                        ),
                        status_code=404,
                    )
                return audio_path
            raise AudioPipelineError(
                format_function_error("get_segment_audio_path", ValueError(f"Segment not found: {segment_id}")),
                status_code=404,
            )
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("get_segment_audio_path", exc)
            logger.exception("%s | batch_id=%s | segment_id=%s", error_message, batch_id, segment_id)
            raise AudioPipelineError(error_message) from exc

    def create_jobs(self, payload: IngestRequest) -> list[PipelineJob]:
        return self.create_jobs_from_urls(payload.urls, batch_name=payload.batch_name)

    def create_jobs_from_urls(
        self,
        urls: list[str],
        *,
        batch_name: str,
        batch_id: int | None = None,
    ) -> list[PipelineJob]:
        try:
            batch = self.get_batch(batch_id) if batch_id is not None else self.create_batch(batch_name)
            chunks = self._chunk_urls(urls, settings.ingest_urls_per_job)
            jobs: list[PipelineJob] = []
            for chunk_urls in chunks:
                job = PipelineJob(batch_id=batch.id)
                self.db.add(job)
                self.db.flush()
                for url in chunk_urls:
                    video_id = self._extract_video_id(url)
                    if not video_id:
                        raise AudioPipelineError(
                            format_function_error("create_jobs", ValueError(f"Invalid normalized YouTube URL: {url}"))
                        )
                    self.db.add(
                        PipelineJobUrl(
                            job_id=job.id,
                            video_id=video_id,
                            url=url,
                            status="queued",
                        )
                    )
                jobs.append(job)
            self._commit()
            for job in jobs:
                self.db.refresh(job)
            self._refresh_batch_status(batch.id)
            return jobs
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("create_jobs", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def list_jobs(self) -> list[PipelineJob]:
        try:
            return list(
                self.db.query(PipelineJob)
                .options(selectinload(PipelineJob.batch), selectinload(PipelineJob.urls))
                .order_by(desc(PipelineJob.created_at))
                .all()
            )
        except Exception as exc:
            error_message = format_function_error("list_jobs", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def get_job_optional(self, job_id: int) -> PipelineJob | None:
        try:
            return (
                self.db.query(PipelineJob)
                .options(selectinload(PipelineJob.batch), selectinload(PipelineJob.urls))
                .filter(PipelineJob.id == job_id)
                .first()
            )
        except Exception as exc:
            error_message = format_function_error("get_job_optional", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def get_job(self, job_id: int) -> PipelineJob:
        try:
            job = self.get_job_optional(job_id)
            if job is None:
                raise AudioPipelineError(
                    format_function_error("get_job", ValueError(f"Job not found: {job_id}")),
                    status_code=404,
                )
            return job
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("get_job", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def save_job(self, job: PipelineJob) -> PipelineJob:
        try:
            self.db.add(job)
            self._commit()
            self.db.refresh(job)
            if job.batch_id:
                self._refresh_batch_status(job.batch_id)
                self.db.refresh(job)
            return job
        except Exception as exc:
            error_message = format_function_error("save_job", exc)
            logger.exception("%s | job_id=%s", error_message, getattr(job, "id", None))
            raise AudioPipelineError(error_message) from exc

    def retry_job(self, job_id: int) -> PipelineJob:
        try:
            source_job = self.get_job(job_id)
            queued_urls = self.list_job_urls(source_job.id, statuses={"queued"})
            if not queued_urls:
                raise AudioPipelineError(
                    format_function_error("retry_job", ValueError("No queued URLs available to retry")),
                    status_code=400,
                )
            payload = IngestRequest(urls=[item.url for item in queued_urls], batch_name=source_job.batch.name)
            return self.create_jobs_from_urls(
                payload.urls,
                batch_name=payload.batch_name,
                batch_id=source_job.batch_id,
            )[0]
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("retry_job", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def list_job_urls(self, job_id: int, *, statuses: set[str] | None = None) -> list[PipelineJobUrl]:
        try:
            query = self.db.query(PipelineJobUrl).filter(PipelineJobUrl.job_id == job_id)
            if statuses:
                query = query.filter(PipelineJobUrl.status.in_(statuses))
            return list(query.order_by(PipelineJobUrl.id).all())
        except Exception as exc:
            error_message = format_function_error("list_job_urls", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def update_job_url(
        self,
        job_url: PipelineJobUrl,
        *,
        status: str,
        logs_fail: str | None = None,
    ) -> PipelineJobUrl:
        try:
            job_url.status = status
            job_url.logs_fail = logs_fail
            self.db.add(job_url)
            self._commit()
            self.db.refresh(job_url)
            return job_url
        except Exception as exc:
            error_message = format_function_error("update_job_url", exc)
            logger.exception("%s | url_id=%s", error_message, getattr(job_url, "id", None))
            raise AudioPipelineError(error_message) from exc

    def mark_job_urls(self, job_id: int, from_status: str, to_status: str) -> int:
        try:
            updated = (
                self.db.query(PipelineJobUrl)
                .filter(PipelineJobUrl.job_id == job_id, PipelineJobUrl.status == from_status)
                .update({"status": to_status}, synchronize_session=False)
            )
            self._commit()
            return int(updated or 0)
        except Exception as exc:
            error_message = format_function_error("mark_job_urls", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def has_active_video_id(self, video_id: str, *, exclude_url_id: int | None = None) -> bool:
        try:
            query = self.db.query(PipelineJobUrl.id).filter(
                PipelineJobUrl.video_id == video_id,
                PipelineJobUrl.status.in_({"queued", "running", "completed", "skipped"}),
            )
            if exclude_url_id is not None:
                query = query.filter(PipelineJobUrl.id != exclude_url_id)
            return query.first() is not None
        except Exception as exc:
            error_message = format_function_error("has_active_video_id", exc)
            logger.exception("%s | video_id=%s", error_message, video_id)
            raise AudioPipelineError(error_message) from exc

    def has_active_jobs(self) -> bool:
        try:
            return (
                self.db.query(PipelineJob.id)
                .filter(PipelineJob.status.in_({"queued", "running", "blocked"}))
                .first()
                is not None
            )
        except Exception as exc:
            error_message = format_function_error("has_active_jobs", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def try_acquire_discovery_lock(self) -> bool:
        try:
            return bool(
                self.db.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": _DISCOVERY_ADVISORY_LOCK_KEY},
                ).scalar()
            )
        except Exception as exc:
            error_message = format_function_error("try_acquire_discovery_lock", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def release_discovery_lock(self) -> None:
        try:
            self.db.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _DISCOVERY_ADVISORY_LOCK_KEY},
            )
        except Exception as exc:
            error_message = format_function_error("release_discovery_lock", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def block_pending_jobs_in_batch(self, source_job: PipelineJob) -> list[PipelineJob]:
        try:
            sibling_jobs = (
                self.db.query(PipelineJob)
                .options(selectinload(PipelineJob.batch))
                .filter(PipelineJob.batch_id == source_job.batch_id)
                .all()
            )
            blocked_jobs: list[PipelineJob] = []
            for job in sibling_jobs:
                if job.id == source_job.id or job.status != "queued":
                    continue
                job.status = "blocked"
                job.current_step = "blocked_by_batch_failure"
                job.error_message = f"Blocked because batch stopped after job {source_job.id} failed"
                self.db.add(job)
                blocked_jobs.append(job)
            self._commit()
            for job in blocked_jobs:
                self.db.refresh(job)
            self._refresh_batch_status(source_job.batch_id)
            return blocked_jobs
        except Exception as exc:
            error_message = format_function_error("block_pending_jobs_in_batch", exc)
            logger.exception("%s | job_id=%s", error_message, getattr(source_job, "id", None))
            raise AudioPipelineError(error_message) from exc

    def resume_batch(self, job_id: int) -> list[PipelineJob]:
        try:
            source_job = self.get_job(job_id)
            jobs = (
                self.db.query(PipelineJob)
                .options(selectinload(PipelineJob.batch))
                .filter(PipelineJob.batch_id == source_job.batch_id)
                .all()
            )
            resumed_jobs: list[PipelineJob] = []
            for job in jobs:
                if job.status not in {"failed", "blocked"}:
                    continue
                has_queued_urls = (
                    self.db.query(PipelineJobUrl.id)
                    .filter(PipelineJobUrl.job_id == job.id, PipelineJobUrl.status == "queued")
                    .first()
                    is not None
                )
                if not has_queued_urls:
                    continue
                job.status = "queued"
                job.current_step = "queued"
                job.error_message = None
                self.db.add(job)
                resumed_jobs.append(job)
            self._commit()
            for job in resumed_jobs:
                self.db.refresh(job)
            self._refresh_batch_status(source_job.batch_id)
            return resumed_jobs
        except AudioPipelineError:
            raise
        except Exception as exc:
            error_message = format_function_error("resume_batch", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def list_job_timings(self, job_id: int) -> list[PipelineStageTiming]:
        # Tất cả dòng timing (stage cha + sub-stage) của một job, theo thứ tự thời gian.
        try:
            return list(
                self.db.query(PipelineStageTiming)
                .filter(PipelineStageTiming.job_id == job_id)
                .order_by(PipelineStageTiming.id)
                .all()
            )
        except Exception as exc:
            error_message = format_function_error("list_job_timings", exc)
            logger.exception("%s | job_id=%s", error_message, job_id)
            raise AudioPipelineError(error_message) from exc

    def aggregate_batch_timings(self, batch_id: int) -> list[dict]:
        # Tổng thời gian theo (stage, sub_stage) trên toàn batch -> bar chart.
        try:
            rows = (
                self.db.query(
                    PipelineStageTiming.stage,
                    PipelineStageTiming.sub_stage,
                    func.coalesce(func.sum(PipelineStageTiming.duration_sec), 0.0),
                    func.count(PipelineStageTiming.id),
                    func.coalesce(func.avg(PipelineStageTiming.duration_sec), 0.0),
                )
                .filter(PipelineStageTiming.batch_id == batch_id)
                .group_by(PipelineStageTiming.stage, PipelineStageTiming.sub_stage)
                .all()
            )
            return [
                {
                    "stage": stage,
                    "sub_stage": sub_stage,
                    "total_duration_sec": round(float(total or 0.0), 3),
                    "count": int(count or 0),
                    "avg_duration_sec": round(float(avg or 0.0), 3),
                }
                for stage, sub_stage, total, count, avg in rows
            ]
        except Exception as exc:
            error_message = format_function_error("aggregate_batch_timings", exc)
            logger.exception("%s | batch_id=%s", error_message, batch_id)
            raise AudioPipelineError(error_message) from exc

    def batch_timings_by_video(self, batch_id: int) -> list[dict]:
        # Drill-down: gom timing theo video_id.
        try:
            timings = (
                self.db.query(PipelineStageTiming)
                .filter(PipelineStageTiming.batch_id == batch_id)
                .order_by(PipelineStageTiming.id)
                .all()
            )
            grouped: dict[str, dict] = {}
            for timing in timings:
                key = timing.video_id or ""
                bucket = grouped.setdefault(key, {"video_id": key, "url": timing.url, "stages": []})
                if bucket["url"] is None and timing.url:
                    bucket["url"] = timing.url
                bucket["stages"].append(timing)
            return list(grouped.values())
        except Exception as exc:
            error_message = format_function_error("batch_timings_by_video", exc)
            logger.exception("%s | batch_id=%s", error_message, batch_id)
            raise AudioPipelineError(error_message) from exc

    def list_timing_history(self, limit: int = 20) -> list[dict]:
        # Lịch sử các run: per-stage totals (dòng cha) + snapshot params để so sánh.
        try:
            safe_limit = max(1, min(200, limit))
            batches = (
                self.db.query(PipelineBatch)
                .options(selectinload(PipelineBatch.jobs))
                .order_by(desc(PipelineBatch.created_at))
                .limit(safe_limit)
                .all()
            )
            summaries: list[dict] = []
            for batch in batches:
                rows = (
                    self.db.query(
                        PipelineStageTiming.stage,
                        func.coalesce(func.sum(PipelineStageTiming.duration_sec), 0.0),
                        func.count(PipelineStageTiming.id),
                        func.coalesce(func.avg(PipelineStageTiming.duration_sec), 0.0),
                    )
                    .filter(
                        PipelineStageTiming.batch_id == batch.id,
                        PipelineStageTiming.sub_stage.is_(None),
                    )
                    .group_by(PipelineStageTiming.stage)
                    .all()
                )
                per_stage = [
                    {
                        "stage": stage,
                        "sub_stage": None,
                        "total_duration_sec": round(float(total or 0.0), 3),
                        "count": int(count or 0),
                        "avg_duration_sec": round(float(avg or 0.0), 3),
                    }
                    for stage, total, count, avg in rows
                ]
                total_duration = round(sum(item["total_duration_sec"] for item in per_stage), 3)
                params: dict = {}
                for job in batch.jobs:
                    if job.run_params:
                        params = job.run_params
                        break
                summaries.append(
                    {
                        "batch_id": batch.id,
                        "batch_name": batch.name,
                        "created_at": batch.created_at,
                        "per_stage": per_stage,
                        "total_duration_sec": total_duration,
                        "params": params,
                    }
                )
            return summaries
        except Exception as exc:
            error_message = format_function_error("list_timing_history", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc

    def resume_incomplete_batches(self) -> list[PipelineJob]:
        try:
            batches = (
                self.db.query(PipelineBatch)
                .options(selectinload(PipelineBatch.jobs))
                .filter(PipelineBatch.status != "completed")
                .all()
            )

            resumed_jobs: list[PipelineJob] = []
            for batch in batches:
                for job in batch.jobs:
                    self.db.query(PipelineJobUrl).filter(
                        PipelineJobUrl.job_id == job.id,
                        PipelineJobUrl.status.in_({"running", "failed"}),
                    ).update({"status": "queued", "logs_fail": None}, synchronize_session=False)

                    has_queued_urls = (
                        self.db.query(PipelineJobUrl.id)
                        .filter(PipelineJobUrl.job_id == job.id, PipelineJobUrl.status == "queued")
                        .first()
                        is not None
                    )
                    if not has_queued_urls:
                        continue

                    job.status = "queued"
                    job.current_step = "queued"
                    job.error_message = None
                    self.db.add(job)
                    resumed_jobs.append(job)

            self._commit()
            refreshed_jobs: list[PipelineJob] = []
            touched_batch_ids = {job.batch_id for job in resumed_jobs}
            for job in resumed_jobs:
                self.db.refresh(job)
                refreshed_jobs.append(job)
            for batch_id in touched_batch_ids:
                self._refresh_batch_status(batch_id)
            return refreshed_jobs
        except Exception as exc:
            error_message = format_function_error("resume_incomplete_batches", exc)
            logger.exception("%s", error_message)
            raise AudioPipelineError(error_message) from exc
