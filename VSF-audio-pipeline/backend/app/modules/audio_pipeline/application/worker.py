from __future__ import annotations

import logging
import threading
from time import perf_counter

from app.core.config import settings
from app.db.session import SessionLocal
from app.modules.audio_pipeline.application.discovery_orchestrator import start_discovery_cycle
from app.modules.audio_pipeline.application.exceptions import BatchAbortError, SkipUrlError, format_function_error
from app.modules.audio_pipeline.application.job_events import publish_job_event
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.utils import send_telegram_log

logger = logging.getLogger(__name__)


def _snapshot_run_params() -> dict:
    # Lưu tham số chạy để so sánh các run trong History.
    return {
        "vad_threshold": settings.vad_threshold,
        "vad_min_volume": settings.vad_min_volume,
        "demucs_enabled": settings.demucs_enabled,
        "demucs_model": settings.demucs_model,
        "demucs_device": settings.demucs_device,
        "asr_model": settings.asr_model,
    }


def start_pipeline_job(job_id: int) -> threading.Thread:
    # Tách helper để có thể resume job từ startup mà không block FastAPI app.
    thread = threading.Thread(target=enqueue_pipeline_job, args=(job_id,), daemon=True)
    thread.start()
    return thread


def _extract_source_duration(latest_state: object) -> float | None:
    # Độ dài audio gốc: ưu tiên bản normalize (decode thật), fallback bản crawl (yt-dlp).
    if not isinstance(latest_state, dict):
        return None
    for key in ("processed_rows", "source_rows"):
        rows = latest_state.get(key) or []
        if rows:
            raw = rows[0].get("duration_sec")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return round(value, 3)
    return None


def _map_state_to_job_paths(latest_state: object) -> dict[str, str | None]:
    # Map state cuối của graph sang các cột path của PipelineJob.
    manifest = latest_state.get("segments_manifest_path") if isinstance(latest_state, dict) else None
    return {
        "manifest_path": manifest,
        "metadata_path": manifest,
        "output_path": manifest,
        "translation_path": None,
    }


def enqueue_pipeline_job(job_id: int) -> None:
    # Background task tự mở session riêng vì nó chạy ngoài vòng đời request.
    db = SessionLocal()
    job_service = PipelineJobService(db)
    job = None
    started_at = perf_counter()
    try:
        job = job_service.get_job_optional(job_id)
        if job is None:
            logger.warning("Pipeline job not found: %s", job_id)
            return
        if job.status == "blocked":
            logger.info("Pipeline job skipped because blocked | job_id=%s | batch=%s", job.id, job.batch_name)
            return

        # Đánh dấu job đang chạy trước khi bước workflow bắt đầu xử lý file thật.
        job.status = "running"
        job.current_step = "starting"
        job.run_params = _snapshot_run_params()
        job_service.save_job(job)
        publish_job_event("job_running", job)
        logger.info("Pipeline job started | job_id=%s | batch=%s", job.id, job.batch_name)
        send_telegram_log(
            "Pipeline job started",
            job_id=job.id,
            batch_name=job.batch_name,
            status="running",
            step="starting",
            url_count=len(job.urls),
        )

        # Chỉ import workflow khi job thực sự chạy để API startup không phụ thuộc audio libs.
        from app.modules.audio_pipeline.application.workflow import audio_pipeline_graph

        job_urls = job_service.list_job_urls(job.id, statuses={"queued"})
        logger.info(
            "Invoking pipeline graph | job_id=%s | batch=%s | url_count=%s",
            job.id,
            job.batch_name,
            len(job_urls),
        )

        latest_state: dict[str, object] = {}
        skipped_urls: list[str] = []
        for index, job_url in enumerate(job_urls):
            url = job_url.url
            try:
                if job_service.has_active_video_id(job_url.video_id, exclude_url_id=job_url.id):
                    job_service.update_job_url(job_url, status="skipped", logs_fail="Skipped because video_id already exists in DB")
                    skipped_urls.append(url)
                    job.error_message = f"Skipped URLs: {len(skipped_urls)}"
                    job.current_step = f"skipped:{index + 1}/{len(job_urls)}"
                    job_service.save_job(job)
                    publish_job_event("job_running", job)
                    continue

                job_service.update_job_url(job_url, status="running", logs_fail=None)
                latest_state = audio_pipeline_graph.invoke(
                    {
                        "job_id": job.id,
                        "batch_id": job.batch_id,
                        "video_id": job_url.video_id,
                        "urls": [url],
                        "batch_name": job.batch_name,
                    }
                )
                paths = _map_state_to_job_paths(latest_state)
                job.manifest_path = paths["manifest_path"]
                job.metadata_path = paths["metadata_path"]
                job.translation_path = paths["translation_path"]
                job.output_path = paths["output_path"]
                job.current_step = f"saved:{index + 1}/{len(job_urls)}"
                job.error_message = None
                # Lưu độ dài audio gốc của video này để hiển thị trên UI.
                job_url.source_duration_sec = _extract_source_duration(latest_state)
                job_service.update_job_url(job_url, status="completed", logs_fail=None)
                job_service.save_job(job)
                publish_job_event("job_running", job)
            except SkipUrlError as exc:
                skipped_urls.append(exc.failed_url)
                job_service.update_job_url(job_url, status="skipped", logs_fail=str(exc))
                job.error_message = str(exc)
                job.current_step = f"skipped:{index + 1}/{len(job_urls)}"
                job_service.save_job(job)
                publish_job_event("job_running", job)
                logger.warning(
                    "Pipeline job skipped URL | job_id=%s | batch=%s | url=%s | reason=%s",
                    job.id,
                    job.batch_name,
                    exc.failed_url,
                    str(exc),
                )
            except BatchAbortError as exc:
                job_service.update_job_url(job_url, status="failed", logs_fail=str(exc))
                raise BatchAbortError(
                    step=exc.step,
                    failed_url=exc.failed_url or url,
                    remaining_urls=[item.url for item in job_urls[index + 1 :]],
                    cause=exc.cause,
                ) from exc
            except Exception as exc:
                job_service.update_job_url(job_url, status="failed", logs_fail=format_function_error("enqueue_pipeline_job", exc))
                raise BatchAbortError(
                    step=job.current_step or "failed",
                    failed_url=url,
                    remaining_urls=[item.url for item in job_urls[index + 1 :]],
                    cause=exc,
                ) from exc

        job.status = "completed"
        job.current_step = "completed"
        job.error_message = None if not skipped_urls else f"Skipped URLs: {len(skipped_urls)}"
        job_service.save_job(job)
        publish_job_event("job_completed", job)
        logger.info(
            "Pipeline job completed | job_id=%s | batch=%s | output=%s | duration_sec=%.2f",
            job.id,
            job.batch_name,
            job.output_path,
            perf_counter() - started_at,
        )
        send_telegram_log(
            "Pipeline batch completed",
            job_id=job.id,
            batch_name=job.batch_name,
            status="completed",
            step="completed",
            duration_sec=round(perf_counter() - started_at, 2),
        )
        start_discovery_cycle(
            trigger="batch_completed",
            completed_job_id=job.id,
            completed_batch_name=job.batch_name,
        )
    except BatchAbortError as exc:
        if job is None:
            job = job_service.get_job_optional(job_id)

        if job is not None:
            job.status = "failed"
            job.current_step = exc.step
            job.error_message = str(exc)
            job_service.save_job(job)
            publish_job_event("job_failed", job)
            blocked_jobs = job_service.block_pending_jobs_in_batch(job)
            for blocked_job in blocked_jobs:
                publish_job_event("job_blocked", blocked_job)

            send_telegram_log(
                "Pipeline batch stopped",
                job_id=job.id,
                batch_name=job.batch_name,
                status="failed",
                step=exc.step,
                url=exc.failed_url,
                error=str(exc),
                remaining_url_count=len(exc.remaining_urls),
                blocked_job_count=len(blocked_jobs),
            )

        logger.error(
            "step=%s | url=%s | error=%s | remaining=%s",
            exc.step,
            exc.failed_url,
            str(exc),
            len(exc.remaining_urls),
        )
        start_discovery_cycle(
            trigger="batch_failed",
            completed_job_id=job.id if job else None,
            completed_batch_name=job.batch_name if job else None,
        )
    except Exception as exc:
        if job is None:
            job = job_service.get_job_optional(job_id)
        if job is not None:
            job.status = "failed"
            job.current_step = job.current_step or "failed"
            job.error_message = format_function_error("enqueue_pipeline_job", exc)
            job_service.save_job(job)
            publish_job_event("job_failed", job)
        logger.exception("%s | job_id=%s", format_function_error("enqueue_pipeline_job", exc), job_id)
        start_discovery_cycle(
            trigger="job_exception",
            completed_job_id=job.id if job else None,
            completed_batch_name=job.batch_name if job else None,
        )
    finally:
        db.close()
