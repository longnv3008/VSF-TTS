from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterator

from app.modules.audio_pipeline.application.segmentation.aligner import (
    align_units_to_vad,
    vad_only_segments,
)
from app.modules.audio_pipeline.application.segmentation.asr_adapter import AsrAdapter
from app.modules.audio_pipeline.application.segmentation.quality_gate import (
    SegmentQualityDecision,
    gate_audio,
    gate_text,
)
from app.modules.audio_pipeline.application.segmentation.segment_writer import (
    cut_wav_segment,
    write_text,
)
from app.modules.audio_pipeline.application.segmentation.sentence_grouper import cues_to_sentence_units
from app.modules.audio_pipeline.application.segmentation.text_quality import (
    has_promo_marker,
    is_blocklisted,
    normalize_vlsp,
)
from app.modules.audio_pipeline.application.segmentation.types import AlignedSegment, SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vtt_parser import parse_youtube_vtt


class VadClient:  # giao diện tối thiểu để type-hint
    def detect_regions(self, wav_path: Path): ...


class _NullSink:
    # Sink mặc định: không làm gì -> segment_video thuần, unit test không cần DB.
    @contextmanager
    def span(self, sub_stage: str) -> Iterator[None]:
        yield

    def add(self, sub_stage: str, duration_sec: float) -> None: ...

    def flush(self) -> None: ...


_NULL_SINK = _NullSink()


def _merge_quality(
    audio_decision: SegmentQualityDecision,
    text_decision: SegmentQualityDecision | None = None,
) -> SegmentQualityDecision:
    if text_decision is None:
        return audio_decision
    keep = audio_decision.keep and text_decision.keep
    score = round(min(audio_decision.score, text_decision.score), 3)
    reasons = tuple(dict.fromkeys(audio_decision.reasons + text_decision.reasons))
    label = "speech_clean" if keep and not reasons else ("needs_review" if keep else "low_quality")
    return SegmentQualityDecision(keep=keep, label=label, score=score, reasons=reasons)


def _apply_vtt_overlap(
    segments: list[AlignedSegment],
    *,
    duration: float,
    overlap_sec: float,
    min_segment_sec: float,
) -> list[AlignedSegment]:
    if overlap_sec <= 0 or len(segments) < 2:
        return segments
    adjusted: list[AlignedSegment] = []
    for index, seg in enumerate(segments):
        start = seg.start
        end = seg.end
        if index > 0:
            start = max(0.0, start - overlap_sec)
        if index < len(segments) - 1:
            end = min(duration, end + overlap_sec)
        if end - start < min_segment_sec:
            continue
        adjusted.append(
            AlignedSegment(start, end, seg.text, seg.transcript_status, seg.vad_status)
        )
    return adjusted


def _has_usable_vtt(subtitle_path: str) -> bool:
    if not subtitle_path:
        return False
    path = Path(subtitle_path)
    return path.exists() and path.is_file() and path.suffix.lower() == ".vtt"


def segment_video(
    processed_row: dict,
    *,
    vad_client: VadClient,
    asr_adapter: AsrAdapter,
    config: SegmentationConfig,
    segments_root: Path,
    batch_name: str,
    timing_sink: object | None = None,
    stage_notifier: Callable[..., None] | None = None,
) -> list[dict]:
    audio_id = processed_row["audio_id"]
    video_id = processed_row.get("video_id", "")
    wav_path = Path(processed_row["audio_file_path"])
    subtitle_path = processed_row.get("subtitle_file_path", "")

    sink = timing_sink or _NULL_SINK

    if stage_notifier:
        stage_notifier(stage="vad", status="started")
    with sink.span("vad"):
        duration, regions = vad_client.detect_regions(wav_path)
    if stage_notifier:
        stage_notifier(
            stage="vad",
            status="completed",
            region_count=len(regions),
            duration_sec=round(duration, 3),
        )

    use_vtt = config.use_vtt_transcript and _has_usable_vtt(subtitle_path)
    transcript_source = "vtt"
    if use_vtt:
        cues = parse_youtube_vtt(Path(subtitle_path))
        units = cues_to_sentence_units(
            cues, config.phrase_gap_sec, config.sentence_max_sec, config.sentence_min_sec
        )
        aligned: list[AlignedSegment] = align_units_to_vad(
            units, regions, duration, config.pad_sec, config.merge_gap_sec,
            config.min_segment_sec, config.boundary_slack_sec,
        )
        aligned = _apply_vtt_overlap(
            aligned,
            duration=duration,
            overlap_sec=config.vtt_overlap_sec,
            min_segment_sec=config.min_segment_sec,
        )
        if not aligned:  # có VTT nhưng không tạo được unit hợp lệ -> rơi về VAD-only + ASR
            use_vtt = False

    if not use_vtt:
        transcript_source = "asr"
        aligned = vad_only_segments(
            regions, duration, config.pad_sec, config.min_segment_sec, config.sentence_max_sec
        )

    out_dir = segments_root / batch_name / audio_id
    rows: list[dict] = []
    for index, seg in enumerate(aligned, start=1):
        segment_id = f"{audio_id}__sent{index:06d}"
        seg_wav = out_dir / f"{segment_id}.wav"
        seg_txt = out_dir / f"{segment_id}.txt"
        _t = perf_counter()
        cut_wav_segment(wav_path, seg_wav, seg.start, seg.end)
        sink.add("cut", perf_counter() - _t)

        duration_sec = round(seg.end - seg.start, 3)
        quality = SegmentQualityDecision(keep=True, label="speech_clean", score=1.0, reasons=())
        if config.quality_gate_enabled:
            quality = gate_audio(
                seg_wav,
                min_rms=config.quality_gate_min_rms,
                min_peak=config.quality_gate_min_peak,
                min_active_ratio=config.quality_gate_min_active_ratio,
                chunk_ms=config.quality_gate_chunk_ms,
            )

        text = seg.text
        transcript_status = seg.transcript_status
        if transcript_source == "asr" and quality.keep:
            _t = perf_counter()
            # Adapter đã hardening + clean_transcript + chuẩn hóa VLSP nội bộ.
            text = asr_adapter.transcribe(seg_wav).strip()
            sink.add("asr", perf_counter() - _t)
            transcript_status = "ready" if text else "missing"
        elif transcript_source == "vtt":
            # VTT path: loại caption ảo giác phổ biến (exact + promo substring) + chuẩn hóa VLSP.
            text = "" if (is_blocklisted(text) or has_promo_marker(text)) else normalize_vlsp(text)
            transcript_status = seg.transcript_status if text else "missing"
        else:
            text = ""
            transcript_status = "missing"

        if config.quality_gate_enabled:
            text_quality = gate_text(
                text,
                duration_sec=duration_sec,
                min_tokens_per_sec=config.quality_gate_min_tokens_per_sec,
                max_tokens_per_sec=config.quality_gate_max_tokens_per_sec,
                min_tokens_for_long_segment=config.quality_gate_min_tokens_for_long_segment,
                long_segment_sec=config.quality_gate_long_segment_sec,
            )
            quality = _merge_quality(quality, text_quality)
            if not quality.keep:
                text = ""
                transcript_status = "missing"
        write_text(seg_txt, text)

        rows.append({
            "audio_id": audio_id,
            "video_id": video_id,
            "segment_id": segment_id,
            "segment_file": str(seg_wav.resolve()),
            "transcript_file": str(seg_txt.resolve()),
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "duration": duration_sec,
            "text": text,
            "transcript_source": transcript_source,
            "transcript_status": transcript_status,
            "vad_status": seg.vad_status,
            "quality_label": quality.label,
            "quality_score": quality.score,
            "quality_reasons": ",".join(quality.reasons),
            "source_url": processed_row.get("source_url", ""),
            "title": processed_row.get("title", ""),
        })
    sink.flush()
    return rows
