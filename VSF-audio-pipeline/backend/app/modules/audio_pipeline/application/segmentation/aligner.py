from __future__ import annotations

from app.modules.audio_pipeline.application.segmentation.types import (
    AlignedSegment,
    SentenceUnit,
    SpeechRegion,
)


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge_regions(regions: list[SpeechRegion], max_gap_sec: float) -> list[SpeechRegion]:
    if not regions:
        return []
    ordered = sorted(regions, key=lambda r: r.start)
    merged = [ordered[0]]
    for region in ordered[1:]:
        previous = merged[-1]
        if region.start - previous.end <= max_gap_sec:
            merged[-1] = SpeechRegion(previous.start, max(previous.end, region.end))
        else:
            merged.append(region)
    return merged


def align_units_to_vad(
    units: list[SentenceUnit],
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    merge_gap_sec: float,
    min_segment_sec: float,
    boundary_slack_sec: float,
) -> list[AlignedSegment]:
    segments: list[AlignedSegment] = []
    for unit in units:
        overlapping = [
            region for region in vad_regions
            if overlap_seconds(unit.start, unit.end, region.start, region.end) > 0.0
        ]
        overlapping = merge_regions(overlapping, merge_gap_sec)
        if overlapping:
            vad_start = min(r.start for r in overlapping)
            vad_end = max(r.end for r in overlapping)
            # Khi đã có overlap thật, ưu tiên ôm TRỌN phần speech để tránh cụt đầu/cuối.
            # boundary_slack chỉ còn vai trò giới hạn việc nới quá xa khỏi câu gốc.
            start = min(unit.start, vad_start)
            end = max(unit.end, vad_end)
            if unit.start - start > boundary_slack_sec:
                start = unit.start - boundary_slack_sec
            if end - unit.end > boundary_slack_sec:
                end = unit.end + boundary_slack_sec
            vad_status = "aligned"
        else:
            start, end, vad_status = unit.start, unit.end, "no_overlap"

        start = max(0.0, start - pad_sec)
        end = min(duration, end + pad_sec)
        if end - start < min_segment_sec:
            continue
        segments.append(AlignedSegment(start, end, unit.text, "ready", vad_status))
    return segments


def vad_only_segments(
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    min_segment_sec: float,
    max_segment_sec: float,
) -> list[AlignedSegment]:
    segments: list[AlignedSegment] = []
    for region in vad_regions:
        start = max(0.0, region.start - pad_sec)
        end = min(duration, region.end + pad_sec)
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + max_segment_sec) if max_segment_sec > 0 else end
            if chunk_end - cursor >= min_segment_sec:
                segments.append(AlignedSegment(cursor, chunk_end, "", "missing", "speech_region"))
            cursor = chunk_end
    return segments
