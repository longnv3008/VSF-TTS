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
