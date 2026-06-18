from __future__ import annotations

from app.db.session import SessionLocal
from app.modules.audio_pipeline.application.exceptions import format_function_error
from app.modules.audio_pipeline.application.job_events import publish_job_event
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.modules.audio_pipeline.application.progress import _now_iso, append_step_event
from app.utils import get_logger

logger = get_logger(__name__)


def update_job_step(job_id: int | None, step_name: str) -> None:
    if job_id is None:
        return

    db = SessionLocal()
    job_service = PipelineJobService(db)
    try:
        job = job_service.get_job_optional(job_id)
        if job is None:
            logger.warning("update_job_step skipped | job_id=%s | step=%s | reason=job_not_found", job_id, step_name)
            return
        job.current_step = step_name
        try:
            # Ghi timeline không được làm hỏng pipeline nếu lỗi.
            job.step_history = append_step_event(job.step_history, step_name, _now_iso())
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s | job_id=%s | step=%s", format_function_error("update_job_step.history", exc), job_id, step_name)
        job_service.save_job(job)
        publish_job_event("job_step_changed", job)
    except Exception as exc:
        logger.exception("%s | job_id=%s | step=%s", format_function_error("update_job_step", exc), job_id, step_name)
    finally:
        db.close()
