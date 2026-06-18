from __future__ import annotations

import random
import threading
from datetime import datetime

from app.core.config import settings
from app.db.session import SessionLocal
from app.modules.audio_pipeline.application.discovery_service import DiscoveryService
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.utils import get_logger, send_telegram_log

logger = get_logger(__name__)
_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_COUNTER_LOCK = threading.Lock()
_DISCOVERY_CYCLE_COUNT = 0


def _reserve_discovery_cycle_slot(*, trigger: str) -> bool:
    global _DISCOVERY_CYCLE_COUNT

    limit = max(0, settings.discovery_cycle_limit_per_start)
    if limit == 0:
        return True

    with _DISCOVERY_COUNTER_LOCK:
        if _DISCOVERY_CYCLE_COUNT >= limit:
            logger.info(
                "discovery:skip | reason=cycle_limit_reached | trigger=%s | cycle_count=%s | cycle_limit=%s",
                trigger,
                _DISCOVERY_CYCLE_COUNT,
                limit,
            )
            return False

        _DISCOVERY_CYCLE_COUNT += 1
        logger.info(
            "discovery:cycle_reserved | trigger=%s | cycle_count=%s | cycle_limit=%s",
            trigger,
            _DISCOVERY_CYCLE_COUNT,
            limit,
        )
        return True


def start_discovery_cycle(*, trigger: str, completed_job_id: int | None, completed_batch_name: str | None) -> None:
    if not settings.discovery_enabled:
        logger.info("discovery:skip | reason=disabled | trigger=%s", trigger)
        return

    thread = threading.Thread(
        target=_run_discovery_cycle,
        kwargs={
            "trigger": trigger,
            "completed_job_id": completed_job_id,
            "completed_batch_name": completed_batch_name,
        },
        daemon=True,
        name="discovery-cycle",
    )
    thread.start()


def _run_discovery_cycle(*, trigger: str, completed_job_id: int | None, completed_batch_name: str | None) -> None:
    if not _DISCOVERY_LOCK.acquire(blocking=False):
        logger.info("discovery:skip | reason=already_running | trigger=%s", trigger)
        return
    if not _reserve_discovery_cycle_slot(trigger=trigger):
        _DISCOVERY_LOCK.release()
        return

    db = SessionLocal()
    acquired_discovery_lock = False
    job_service: PipelineJobService | None = None
    try:
        job_service = PipelineJobService(db)
        if job_service.has_active_jobs():
            logger.info("discovery:skip | reason=active_jobs_present | trigger=%s", trigger)
            return

        min_delay = max(0.0, settings.discovery_min_delay_sec)
        max_delay = max(min_delay, settings.discovery_max_delay_sec)
        sleep_sec = random.uniform(min_delay, max_delay) if max_delay > 0 else 0.0
        logger.info(
            "discovery:start | trigger=%s | completed_job_id=%s | completed_batch=%s | sleep_sec=%.2f",
            trigger,
            completed_job_id,
            completed_batch_name,
            sleep_sec,
        )
        send_telegram_log(
            "Discovery agent started",
            trigger=trigger,
            completed_job_id=completed_job_id or "",
            completed_batch_name=completed_batch_name or "",
            topic_scope="vietnamese",
            target_url_count=settings.discovery_batch_size,
            sleep_sec=round(sleep_sec, 2),
        )
        if sleep_sec > 0:
            threading.Event().wait(sleep_sec)

        if job_service.has_active_jobs():
            logger.info("discovery:skip | reason=active_jobs_after_wait | trigger=%s", trigger)
            return

        acquired_discovery_lock = job_service.try_acquire_discovery_lock()
        if not acquired_discovery_lock:
            logger.info("discovery:skip | reason=advisory_lock_busy | trigger=%s", trigger)
            return

        discovery_service = DiscoveryService(job_service)
        query_set = discovery_service.get_query_set()
        send_telegram_log(
            "Discovery agent searching",
            status="searching",
            trigger=trigger,
            topic_scope="vietnamese",
            topic_source=query_set.query_source,
            topic_count=len(query_set.queries),
            signal_count=len(query_set.signals),
            target_url_count=settings.discovery_batch_size,
        )
        urls = discovery_service.discover_urls(limit=settings.discovery_batch_size)
        if job_service.has_active_jobs():
            logger.info("discovery:skip | reason=active_jobs_before_create | trigger=%s", trigger)
            send_telegram_log(
                "Discovery agent finished",
                status="skipped",
                reason="active_jobs_before_create",
                topic_source=query_set.query_source,
                topic_count=len(query_set.queries),
                signal_count=len(query_set.signals),
            )
            return
        if not urls:
            logger.info("discovery:done | created_batch=no | reason=no_new_urls")
            send_telegram_log(
                "Discovery agent finished",
                status="idle",
                discovered_url_count=0,
                reason="no_new_urls",
                topic_source=query_set.query_source,
                topic_count=len(query_set.queries),
                signal_count=len(query_set.signals),
            )
            return

        batch_name = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        jobs = job_service.create_jobs_from_urls(urls, batch_name=batch_name)
        logger.info(
            "discovery:batch_created | batch_name=%s | job_count=%s | discovered_url_count=%s",
            batch_name,
            len(jobs),
            len(urls),
        )
        send_telegram_log(
            "Discovery batch created",
            status="created",
            batch_name=batch_name,
            discovered_url_count=len(urls),
            topic_scope="vietnamese",
            topic_source=query_set.query_source,
            topic_count=len(query_set.queries),
            signal_count=len(query_set.signals),
        )

        from app.modules.audio_pipeline.application.job_events import publish_job_event
        from app.modules.audio_pipeline.application.worker import enqueue_pipeline_job

        for job in jobs:
            publish_job_event("job_created", job)
            thread = threading.Thread(target=enqueue_pipeline_job, args=(job.id,), daemon=True)
            thread.start()
    except Exception as exc:
        logger.exception("discovery:failed | trigger=%s | error=%s", trigger, exc)
        send_telegram_log(
            "Discovery agent failed",
            status="failed",
            trigger=trigger,
            error=str(exc),
        )
    finally:
        if acquired_discovery_lock and job_service is not None:
            try:
                job_service.release_discovery_lock()
            except Exception:
                logger.exception("discovery:unlock_failed | trigger=%s", trigger)
        db.close()
        _DISCOVERY_LOCK.release()
