from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.modules.audio_pipeline.application.exceptions import format_function_error
from app.modules.audio_pipeline.application.job_progress import update_job_step
from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService
from app.modules.audio_pipeline.application.stage_timing import record_stage
from app.utils import get_logger


class PipelineState(TypedDict, total=False):
    # State dùng để truyền dữ liệu giữa các bước trong graph.
    job_id: int
    batch_id: int
    video_id: str
    current_step: str
    urls: list[str]
    batch_name: str
    source_rows: list[dict[str, str]]
    processed_rows: list[dict[str, str]]
    segment_rows: list[dict]
    segments_manifest_path: str


service = AudioPipelineService()
logger = get_logger(__name__)


def mark_step_started(state: PipelineState, step_name: str) -> None:
    update_job_step(state.get("job_id"), step_name)
    logger.info("step=%s", step_name)
    # send_telegram_log(
    #     "Pipeline step started",
    #     job_id=state.get("job_id") or "",
    #     batch_name=state.get("batch_name", "batch_001"),
    #     step=step_name,
    #     status="started",
    # )


def _first_url(state: PipelineState) -> str | None:
    urls = state.get("urls") or []
    return urls[0] if urls else None


def _stage_span(state: PipelineState, stage: str):
    # Mở dòng timing cha cho stage (append-only, bền hơn step_history).
    return record_stage(
        state.get("job_id"),
        state.get("batch_id"),
        stage,
        video_id=state.get("video_id", ""),
        url=_first_url(state),
    )


def validate_urls(state: PipelineState) -> PipelineState:
    # Chuẩn hóa input đầu vào trước khi thực sự bắt đầu crawl.
    mark_step_started(state, "validate_urls")
    with _stage_span(state, "validate_urls"):
        urls = [url.strip() for url in state.get("urls", []) if url.strip()]
        if not urls:
            raise ValueError(format_function_error("validate_urls", ValueError("No valid URLs provided")))
    logger.info("step=validate_urls")
    return {
        "job_id": state.get("job_id"),
        "batch_id": state.get("batch_id"),
        "video_id": state.get("video_id", ""),
        "current_step": "validate_urls",
        "urls": urls,
        "batch_name": state.get("batch_name", "batch_001"),
    }


def crawl_audio(state: PipelineState) -> PipelineState:
    mark_step_started(state, "crawl_audio")
    with _stage_span(state, "crawl_audio"):
        source_rows = service.crawl_youtube(
            state["urls"],
            job_id=state.get("job_id"),
            batch_name=state["batch_name"],
        )
    logger.info("step=crawl_audio")
    return {"current_step": "crawl_audio", "source_rows": source_rows}


def vocal_separation(state: PipelineState) -> PipelineState:
    # Tách vocal bằng Demucs trên raw trước normalize. No-op khi DEMUCS_ENABLED=false.
    mark_step_started(state, "vocal_separation")
    with _stage_span(state, "vocal_separation"):
        source_rows = service.separate_vocals(
            state.get("source_rows", []),
            job_id=state.get("job_id"),
            batch_id=state.get("batch_id"),
            batch_name=state.get("batch_name"),
        )
    logger.info("step=vocal_separation")
    return {"current_step": "vocal_separation", "source_rows": source_rows}


def normalize_audio(state: PipelineState) -> PipelineState:
    mark_step_started(state, "normalize_audio")
    with _stage_span(state, "normalize_audio"):
        processed_rows = service.normalize_audio(
            state.get("source_rows", []),
            job_id=state.get("job_id"),
            batch_name=state.get("batch_name"),
        )
    logger.info("step=normalize_audio")
    return {"current_step": "normalize_audio", "processed_rows": processed_rows}


def segment_and_label(state: PipelineState) -> PipelineState:
    mark_step_started(state, "segment_and_label")
    with _stage_span(state, "segment_and_label"):
        segment_rows = service.segment_and_label(
            state.get("processed_rows", []),
            job_id=state.get("job_id"),
            batch_id=state.get("batch_id"),
            batch_name=state["batch_name"],
        )
    logger.info("step=segment_and_label")
    return {"current_step": "segment_and_label", "segment_rows": segment_rows}


def build_segment_metadata(state: PipelineState) -> PipelineState:
    mark_step_started(state, "build_segment_metadata")
    with _stage_span(state, "build_segment_metadata"):
        manifest_path = service.build_segment_metadata(
            state.get("segment_rows", []),
            job_id=state.get("job_id"),
            batch_name=state["batch_name"],
        )
    logger.info("step=build_segment_metadata")
    return {"current_step": "build_segment_metadata", "segments_manifest_path": str(manifest_path)}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("validate_urls", validate_urls)
    graph.add_node("crawl_audio", crawl_audio)
    graph.add_node("vocal_separation", vocal_separation)
    graph.add_node("normalize_audio", normalize_audio)
    graph.add_node("segment_and_label", segment_and_label)
    graph.add_node("build_segment_metadata", build_segment_metadata)
    graph.set_entry_point("validate_urls")
    graph.add_edge("validate_urls", "crawl_audio")
    graph.add_edge("crawl_audio", "vocal_separation")
    graph.add_edge("vocal_separation", "normalize_audio")
    graph.add_edge("normalize_audio", "segment_and_label")
    graph.add_edge("segment_and_label", "build_segment_metadata")
    graph.add_edge("build_segment_metadata", END)
    return graph.compile()


# Compile graph một lần để worker chỉ việc invoke lại cho từng job.
audio_pipeline_graph = build_graph()
