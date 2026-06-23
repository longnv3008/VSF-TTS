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
        segments.append(
            AlignedSegment(
                start,
                end,
                unit.text,
                "ready",
                vad_status,
                text_start=unit.start,
                text_end=unit.end,
            )
        )
    return segments


def vad_only_segments(
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    min_segment_sec: float,
    max_segment_sec: float,
    merge_gap_sec: float = 0.0,
) -> list[AlignedSegment]:
    merged_regions = merge_regions(vad_regions, merge_gap_sec)
    segments: list[AlignedSegment] = []
    current_start: float | None = None
    current_end: float | None = None

    def flush() -> None:
        nonlocal current_start, current_end
        if current_start is None or current_end is None:
            current_start, current_end = None, None
            return
        start = max(0.0, current_start - pad_sec)
        end = min(duration, current_end + pad_sec)
        if end - start < min_segment_sec:
            current_start, current_end = None, None
            return

        if max_segment_sec > 0 and end - start > max_segment_sec:
            cursor = start
            while cursor < end:
                chunk_end = min(end, cursor + max_segment_sec)
                if chunk_end - cursor >= min_segment_sec:
                    segments.append(
                        AlignedSegment(
                            cursor,
                            chunk_end,
                            "",
                            "missing",
                            "speech_region",
                            text_start=cursor,
                            text_end=chunk_end,
                        )
                    )
                cursor = chunk_end
        else:
            segments.append(
                AlignedSegment(
                    start,
                    end,
                    "",
                    "missing",
                    "speech_region",
                    text_start=start,
                    text_end=end,
                )
            )
        current_start, current_end = None, None

    for region in merged_regions:
        if current_start is None or current_end is None:
            current_start, current_end = region.start, region.end
            continue

        proposed_start = max(0.0, current_start - pad_sec)
        proposed_end = min(duration, region.end + pad_sec)
        proposed_duration = proposed_end - proposed_start
        if max_segment_sec > 0 and proposed_duration > max_segment_sec:
            flush()
            current_start, current_end = region.start, region.end
            continue

        current_end = max(current_end, region.end)

    flush()
    return segments
