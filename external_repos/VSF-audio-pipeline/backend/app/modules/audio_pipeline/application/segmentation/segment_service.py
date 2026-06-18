from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Iterator

from app.modules.audio_pipeline.application.segmentation.aligner import (
    align_units_to_vad,
    vad_only_segments,
)
from app.modules.audio_pipeline.application.segmentation.asr_adapter import AsrAdapter
from app.modules.audio_pipeline.application.segmentation.segment_writer import (
    cut_wav_segment,
    write_text,
)
from app.modules.audio_pipeline.application.segmentation.sentence_grouper import cues_to_sentence_units
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
) -> list[dict]:
    audio_id = processed_row["audio_id"]
    video_id = processed_row.get("video_id", "")
    wav_path = Path(processed_row["audio_file_path"])
    subtitle_path = processed_row.get("subtitle_file_path", "")

    sink = timing_sink or _NULL_SINK

    with sink.span("vad"):
        duration, regions = vad_client.detect_regions(wav_path)

    use_vtt = _has_usable_vtt(subtitle_path)
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
        if not aligned:  # có VTT nhưng không ráp được -> rơi về VAD-only + ASR
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

        text = seg.text
        transcript_status = seg.transcript_status
        if transcript_source == "asr":
            _t = perf_counter()
            text = asr_adapter.transcribe(seg_wav).strip()
            sink.add("asr", perf_counter() - _t)
            transcript_status = "ready" if text else "missing"
        write_text(seg_txt, text)

        rows.append({
            "audio_id": audio_id,
            "video_id": video_id,
            "segment_id": segment_id,
            "segment_file": str(seg_wav.resolve()),
            "transcript_file": str(seg_txt.resolve()),
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "duration": round(seg.end - seg.start, 3),
            "text": text,
            "transcript_source": transcript_source,
            "transcript_status": transcript_status,
            "vad_status": seg.vad_status,
            "source_url": processed_row.get("source_url", ""),
            "title": processed_row.get("title", ""),
        })
    sink.flush()
    return rows
