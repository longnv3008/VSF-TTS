from app.modules.audio_pipeline.application.segmentation.aligner import (
    align_units_to_vad,
    vad_only_segments,
)
from app.modules.audio_pipeline.application.segmentation.types import SentenceUnit, SpeechRegion


def test_align_refines_boundary_when_close():
    units = [SentenceUnit(1.0, 2.0, "xin chao")]
    regions = [SpeechRegion(0.9, 2.1)]
    segs = align_units_to_vad(units, regions, duration=10.0, pad_sec=0.0,
                              merge_gap_sec=0.5, min_segment_sec=0.3, boundary_slack_sec=0.5)
    assert len(segs) == 1
    assert segs[0].vad_status == "aligned"
    assert segs[0].start == 0.9 and segs[0].end == 2.1
    assert segs[0].text == "xin chao"


def test_align_extends_to_cover_speech_even_when_farther_than_unit():
    units = [SentenceUnit(1.0, 2.0, "xin chao")]
    regions = [SpeechRegion(0.3, 2.6)]
    segs = align_units_to_vad(
        units,
        regions,
        duration=10.0,
        pad_sec=0.0,
        merge_gap_sec=0.5,
        min_segment_sec=0.3,
        boundary_slack_sec=0.8,
    )
    assert len(segs) == 1
    assert segs[0].vad_status == "aligned"
    assert segs[0].start == 0.3
    assert segs[0].end == 2.6


def test_align_no_overlap_keeps_unit_bounds():
    units = [SentenceUnit(1.0, 2.0, "xin chao")]
    regions = [SpeechRegion(5.0, 6.0)]
    segs = align_units_to_vad(units, regions, duration=10.0, pad_sec=0.0,
                              merge_gap_sec=0.5, min_segment_sec=0.3, boundary_slack_sec=0.5)
    assert segs[0].vad_status == "no_overlap"
    assert segs[0].start == 1.0 and segs[0].end == 2.0


def test_vad_only_segments_chunks_long_region():
    regions = [SpeechRegion(0.0, 5.0)]
    segs = vad_only_segments(regions, duration=5.0, pad_sec=0.0,
                             min_segment_sec=0.3, max_segment_sec=2.0)
    assert len(segs) == 3
    assert all(s.text == "" and s.transcript_status == "missing" for s in segs)
    assert all(s.vad_status == "speech_region" for s in segs)


def test_vad_only_segments_merge_short_internal_gap():
    regions = [SpeechRegion(0.0, 1.2), SpeechRegion(1.35, 2.3)]
    segs = vad_only_segments(
        regions,
        duration=3.0,
        pad_sec=0.0,
        min_segment_sec=0.3,
        max_segment_sec=8.0,
        merge_gap_sec=0.2,
    )
    assert len(segs) == 1
    assert segs[0].start == 0.0
    assert segs[0].end == 2.3


def test_vad_only_segments_split_at_region_boundaries_before_hard_chunking():
    regions = [SpeechRegion(0.0, 1.8), SpeechRegion(2.0, 3.6), SpeechRegion(3.9, 5.2)]
    segs = vad_only_segments(
        regions,
        duration=6.0,
        pad_sec=0.0,
        min_segment_sec=0.3,
        max_segment_sec=4.0,
        merge_gap_sec=0.1,
    )
    assert len(segs) == 2
    assert (segs[0].start, segs[0].end) == (0.0, 3.6)
    assert (segs[1].start, segs[1].end) == (3.9, 5.2)
