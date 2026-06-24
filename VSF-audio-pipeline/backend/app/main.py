from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.modules.audio_pipeline.application.exceptions import AudioPipelineError
from app.modules.audio_pipeline.application.discovery_orchestrator import start_discovery_cycle
from app.modules.audio_pipeline.application.job_events import publish_job_event
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.modules.audio_pipeline.application.worker import start_pipeline_job
from app.modules.router import router as app_router
from app.observability.tracing import configure_tracing
from app.utils import send_telegram_log
from app.utils.filesystem import ensure_dir

logger = logging.getLogger(__name__)


def _validate_writable_dir(path: Path, *, label: str) -> str | None:
    try:
        ensure_dir(path)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return None
    except Exception as exc:
        return f"{label}: {exc}"


def _validate_runtime_paths() -> list[str]:
    issues: list[str] = []
    issues.extend(
        issue
        for issue in [
            _validate_writable_dir(settings.raw_youtube_dir, label="raw_youtube_dir"),
            _validate_writable_dir(settings.processed_audio_dir, label="processed_audio_dir"),
            _validate_writable_dir(settings.metadata_dir, label="metadata_dir"),
            _validate_writable_dir(settings.segments_dir, label="segments_dir"),
            _validate_writable_dir(settings.log_dir, label="log_dir"),
        ]
        if issue
    )

    if settings.discovery_enabled:
        topic_file = settings.resolved_discovery_topic_file
        if topic_file is not None:
            topic_path = topic_file if topic_file.is_absolute() else Path.cwd() / topic_file
            if not topic_path.exists() or not topic_path.is_file():
                issues.append(f"discovery_topic_file_missing: {topic_path}")

    return issues


def _cleanup_zombie_jobs() -> None:
    """Mark zombie running/queued jobs as failed on startup.

    Khi container restart, các jobs đang running/queued sẽ bị stuck vĩnh viễn
    vì worker thread đã chết. Cần dọn để discovery có thể chạy.
    """
    from app.modules.audio_pipeline.domain.models import PipelineJob, PipelineJobUrl

    db = SessionLocal()
    try:
        zombie_jobs = (
            db.query(PipelineJob)
            .filter(PipelineJob.status.in_({"running", "queued"}))
            .all()
        )
        if not zombie_jobs:
            logger.info("No zombie jobs found on startup")
            return

        for job in zombie_jobs:
            old_status = job.status
            job.status = "failed"
            job.current_step = "failed_zombie_cleanup"
            job.error_message = f"Marked failed on startup — was '{old_status}' when container restarted"
            db.add(job)
            # Cũng mark các URL running → failed
            db.query(PipelineJobUrl).filter(
                PipelineJobUrl.job_id == job.id,
                PipelineJobUrl.status.in_({"running"}),
            ).update(
                {"status": "failed", "logs_fail": "Container restarted while running"},
                synchronize_session=False,
            )
        db.commit()
        logger.info(
            "Cleaned up zombie jobs on startup | count=%s | job_ids=%s",
            len(zombie_jobs),
            [j.id for j in zombie_jobs],
        )
        send_telegram_log(
            "Zombie jobs cleaned up on startup",
            step="startup",
            status="warning",
            zombie_count=len(zombie_jobs),
            job_ids=str([j.id for j in zombie_jobs]),
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to clean up zombie jobs | error=%s", exc)
    finally:
        db.close()


def _trigger_startup_discovery() -> None:
    if not settings.discovery_enabled:
        logger.info("Startup discovery disabled | DISCOVERY_ENABLED=false")
        return

    _cleanup_zombie_jobs()

    logger.info("Startup discovery enabled | scheduling initial discovery cycle")
    start_discovery_cycle(
        trigger="startup_idle",
        completed_job_id=None,
        completed_batch_name=None,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Khởi tạo logging và tracing đúng một lần khi app start.
    configure_logging()
    configure_tracing()
    cookie_file = settings.resolved_yt_dlp_cookie_file
    backup_cookie_file = settings.resolved_yt_dlp_cookie_backup_file
    proxy_backups = settings.resolved_yt_dlp_proxy_backups
    cookie_status = "guest"
    active_cookie = "guest"
    backup_cookie_status = "missing"
    backup_cookie_path = str(backup_cookie_file) if backup_cookie_file is not None else ""
    if backup_cookie_file is not None and backup_cookie_file.exists() and backup_cookie_file.is_file():
        backup_cookie_status = "loaded"
        if active_cookie == "guest":
            active_cookie = "backup"
    if cookie_file is not None:
        if cookie_file.exists() and cookie_file.is_file():
            logger.info("yt-dlp cookies enabled | cookie_file=%s", cookie_file)
            cookie_status = "loaded"
            active_cookie = "primary"
            send_telegram_log(
                "yt-dlp runtime config loaded",
                step="startup",
                status="ok",
                cookie_status=cookie_status,
                active_cookie=active_cookie,
                cookie_file=str(cookie_file),
                cookie_backup_status=backup_cookie_status,
                cookie_backup_file=backup_cookie_path,
                proxy_backup_count=len(proxy_backups),
            )
        else:
            logger.warning("yt-dlp cookies configured but file missing | cookie_file=%s", cookie_file)
            if backup_cookie_status == "loaded":
                send_telegram_log(
                    "yt-dlp runtime config loaded",
                    step="startup",
                    status="ok",
                    cookie_status="loaded",
                    active_cookie=active_cookie,
                    cookie_file=backup_cookie_path,
                    cookie_backup_status=backup_cookie_status,
                    cookie_backup_file=backup_cookie_path,
                    primary_cookie_status="missing",
                    primary_cookie_file=str(cookie_file),
                    proxy_backup_count=len(proxy_backups),
                )
            else:
                cookie_status = "missing"
                send_telegram_log(
                    "yt-dlp cookies configured but file missing",
                    step="startup",
                    status="warning",
                    active_cookie=active_cookie,
                    cookie_file=str(cookie_file),
                    cookie_backup_status=backup_cookie_status,
                    cookie_backup_file=backup_cookie_path,
                    proxy_backup_count=len(proxy_backups),
                )
    else:
        send_telegram_log(
            "yt-dlp runtime config loaded",
            step="startup",
            status="ok",
            cookie_status=cookie_status,
            active_cookie=active_cookie,
            cookie_backup_status=backup_cookie_status,
            cookie_backup_file=backup_cookie_path,
            proxy_backup_count=len(proxy_backups),
        )
    runtime_path_issues = _validate_runtime_paths()
    if runtime_path_issues:
        logger.warning("runtime path validation issues | count=%s | issues=%s", len(runtime_path_issues), runtime_path_issues)
        send_telegram_log(
            "Runtime path validation warning",
            step="startup",
            status="warning",
            issue_count=len(runtime_path_issues),
            issues=" | ".join(runtime_path_issues),
        )
    else:
        logger.info("runtime path validation ok")
    if settings.resume_incomplete_jobs_on_startup:
        db = SessionLocal()
        try:
            resumed_jobs = PipelineJobService(db).resume_incomplete_batches()
            for job in resumed_jobs:
                publish_job_event("job_created", job)
                start_pipeline_job(job.id)
            if resumed_jobs:
                logger.info("Resumed incomplete pipeline jobs on startup | count=%s", len(resumed_jobs))
        finally:
            db.close()
    else:
        logger.info("Startup auto-resume disabled | RESUME_INCOMPLETE_JOBS_ON_STARTUP=false")
    _trigger_startup_discovery()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount toàn bộ router nghiệp vụ dưới cùng một app FastAPI.
app.include_router(app_router)


@app.exception_handler(AudioPipelineError)
async def handle_audio_pipeline_error(_: Request, exc: AudioPipelineError) -> JSONResponse:
    # Chuẩn hóa lỗi nghiệp vụ để frontend luôn nhận được status + detail rõ ràng.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled API exception | method=%s | path=%s",
        request.method,
        request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
