from app.modules.audio_pipeline.application.segmentation.types import (
    AlignedSegment,
    SegmentationConfig,
    SentenceUnit,
    SpeechRegion,
    TranscriptCue,
)


def test_dataclasses_construct():
    cue = TranscriptCue(start=1.0, end=2.0, text="xin chao")
    unit = SentenceUnit(start=1.0, end=2.0, text="xin chao")
    region = SpeechRegion(start=1.0, end=2.0)
    seg = AlignedSegment(start=1.0, end=2.0, text="xin chao", transcript_status="ready", vad_status="aligned")
    assert cue.text == unit.text == seg.text == "xin chao"
    assert region.end == 2.0


def test_segmentation_config_from_mapping():
    cfg = SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45, use_vtt_transcript=True,
        pad_sec=0.1, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
        quality_gate_enabled=False,
    )
    assert cfg.threshold == 0.7
    assert cfg.sentence_max_sec == 12.0
