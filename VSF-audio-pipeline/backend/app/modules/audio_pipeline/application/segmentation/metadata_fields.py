"""Fieldnames của segment metadata — dùng chung giữa pipeline_service (ghi) và
segment_review_service (đọc/ghi). Tách riêng để không phải import pipeline_service
(kéo audio libs) từ tầng review."""

from __future__ import annotations

REVIEW_FIELDS: tuple[str, str, str] = ("reference", "manual_wer", "review_status")

SEGMENT_METADATA_FIELDS: list[str] = [
    "audio_id", "video_id", "segment_id", "segment_file", "transcript_file",
    "start", "end", "duration", "text", "transcript_source",
    "transcript_status", "vad_status", "quality_label", "quality_score",
    "quality_reasons", "source_url", "title",
    *REVIEW_FIELDS,
]
