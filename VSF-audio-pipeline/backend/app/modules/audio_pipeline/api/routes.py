from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.modules.audio_pipeline.api.schemas import (
    BatchRead,
    BatchTimingSummary,
    IngestRequest,
    JobRead,
    ReviewRequest,
    ReviewSegment,
    StageAggregate,
    StageTimingItem,
    VideoStageBreakdown,
    WerSummary,
)
from app.modules.audio_pipeline.application.segment_review_service import (
    SegmentReviewService,
)
from app.modules.audio_pipeline.application.job_events import job_event_broker, publish_job_event
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.modules.audio_pipeline.application.worker import enqueue_pipeline_job, start_pipeline_job

# Router này chỉ chịu trách nhiệm nhận request và gọi đúng service.
router = APIRouter()


def get_job_service(db: Session = Depends(get_db)) -> PipelineJobService:
    # Tạo service cho từng request từ session hiện tại của request đó.
    return PipelineJobService(db)


@router.get("/jobs", response_model=list[JobRead])
async def list_jobs(job_service: PipelineJobService = Depends(get_job_service)) -> list[JobRead]:
    # send_telegram_log("Test log", source="API test endpoint")
    return job_service.list_jobs()


@router.get("/batches", response_model=list[BatchRead])
async def list_batches(job_service: PipelineJobService = Depends(get_job_service)) -> list[BatchRead]:
    return job_service.list_batches()


@router.get("/batches/{batch_id}", response_model=BatchRead)
async def get_batch(batch_id: int, job_service: PipelineJobService = Depends(get_job_service)) -> BatchRead:
    return job_service.get_batch(batch_id)


@router.get("/jobs/events")
async def stream_job_events() -> StreamingResponse:
    return StreamingResponse(job_event_broker.stream(), media_type="text/event-stream")


@router.get("/timings/history", response_model=list[BatchTimingSummary])
async def list_timing_history(
    limit: int = 20,
    job_service: PipelineJobService = Depends(get_job_service),
) -> list[BatchTimingSummary]:
    # Lịch sử các run để so sánh thời gian sau khi đổi param.
    return job_service.list_timing_history(limit)


@router.get("/batches/{batch_id}/timings/aggregate", response_model=list[StageAggregate])
async def aggregate_batch_timings(
    batch_id: int,
    job_service: PipelineJobService = Depends(get_job_service),
) -> list[StageAggregate]:
    return job_service.aggregate_batch_timings(batch_id)


@router.get("/batches/{batch_id}/timings/by-video", response_model=list[VideoStageBreakdown])
async def batch_timings_by_video(
    batch_id: int,
    job_service: PipelineJobService = Depends(get_job_service),
) -> list[VideoStageBreakdown]:
    return job_service.batch_timings_by_video(batch_id)


@router.get("/jobs/{job_id}/timings", response_model=list[StageTimingItem])
async def list_job_timings(
    job_id: int,
    job_service: PipelineJobService = Depends(get_job_service),
) -> list[StageTimingItem]:
    return job_service.list_job_timings(job_id)


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: int, job_service: PipelineJobService = Depends(get_job_service)) -> JobRead:
    return job_service.get_job(job_id)


@router.post("/jobs/ingest", response_model=JobRead, status_code=201)
async def create_ingest_job(
    payload: IngestRequest,
    background_tasks: BackgroundTasks,
    job_service: PipelineJobService = Depends(get_job_service),
) -> JobRead:
    # Batch lon se duoc chia thanh nhieu job nho de giam rui ro khi crawl.
    jobs = job_service.create_jobs(payload)
    for job in jobs:
        publish_job_event("job_created", job)
        background_tasks.add_task(enqueue_pipeline_job, job.id)
    return jobs[0]


@router.post("/jobs/{job_id}/retry", response_model=JobRead, status_code=201)
async def retry_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    job_service: PipelineJobService = Depends(get_job_service),
) -> JobRead:
    job = job_service.retry_job(job_id)
    publish_job_event("job_created", job)
    background_tasks.add_task(enqueue_pipeline_job, job.id)
    return job


@router.post("/jobs/{job_id}/resume-batch", response_model=list[JobRead], status_code=201)
async def resume_batch(
    job_id: int,
    background_tasks: BackgroundTasks,
    job_service: PipelineJobService = Depends(get_job_service),
) -> list[JobRead]:
    jobs = job_service.resume_batch(job_id)
    for job in jobs:
        publish_job_event("job_created", job)
        background_tasks.add_task(start_pipeline_job, job.id)
    return jobs


def get_review_service() -> SegmentReviewService:
    return SegmentReviewService(
        metadata_dir=settings.metadata_dir,
        segments_dir=settings.segments_dir,
    )


@router.get("/batches/{batch_name}/segments", response_model=list[ReviewSegment])
async def list_review_segments(
    batch_name: str,
    status: str = "needs_review",
    review_service: SegmentReviewService = Depends(get_review_service),
) -> list[ReviewSegment]:
    try:
        return review_service.list_segments(batch_name, status=status)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_name}/segments/{segment_id}/audio")
async def get_segment_audio(
    batch_name: str,
    segment_id: str,
    review_service: SegmentReviewService = Depends(get_review_service),
) -> FileResponse:
    try:
        path = review_service.resolve_audio_path(batch_name, segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@router.post("/batches/{batch_name}/segments/{segment_id}/review", response_model=ReviewSegment)
async def submit_segment_review(
    batch_name: str,
    segment_id: str,
    payload: ReviewRequest,
    review_service: SegmentReviewService = Depends(get_review_service),
) -> ReviewSegment:
    try:
        return review_service.submit_review(batch_name, segment_id, payload.reference)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_name}/wer-summary", response_model=WerSummary)
async def get_wer_summary(
    batch_name: str,
    review_service: SegmentReviewService = Depends(get_review_service),
) -> WerSummary:
    try:
        return review_service.wer_summary(batch_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
