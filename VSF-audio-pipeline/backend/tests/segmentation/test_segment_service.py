from app.modules.audio_pipeline.application.segmentation.segment_service import segment_video
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion


def _cfg():
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45,
        pad_sec=0.0, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
    )


class _FakeVad:
    def __init__(self, regions, duration):
        self._regions, self._duration = regions, duration

    def detect_regions(self, wav_path):
        return self._duration, list(self._regions)


class _FakeAsr:
    def transcribe(self, wav_path):
        return "loi asr"


VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
xin chao cac ban.
"""


def test_vtt_path_produces_segment(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["transcript_source"] == "vtt"
    assert rows[0]["text"] == "xin chao cac ban."
    assert rows[0]["segment_id"] == "yt_vid__sent000001"
    assert (tmp_path / "segments" / "b1" / "yt_vid" / "yt_vid__sent000001.wav").exists()
    assert (tmp_path / "segments" / "b1" / "yt_vid" / "yt_vid__sent000001.txt").read_text(encoding="utf-8") == "xin chao cac ban."


def test_asr_fallback_when_no_vtt(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["transcript_source"] == "asr"
    assert rows[0]["text"] == "loi asr"


# ---------------------------------------------------------------------------
# timing_sink integration
# ---------------------------------------------------------------------------


class _SpySink:
    """Sink that records all calls (no DB)."""
    from contextlib import contextmanager as _cm
    from typing import Iterator as _It

    def __init__(self):
        self.spans: list[str] = []
        self.adds: list[tuple[str, float]] = []
        self.flush_count = 0

    @_cm
    def span(self, sub_stage: str) -> _It[None]:
        self.spans.append(sub_stage)
        yield

    def add(self, sub_stage: str, duration_sec: float) -> None:
        self.adds.append((sub_stage, duration_sec))

    def flush(self) -> None:
        self.flush_count += 1


def test_timing_sink_vtt_path_calls_vad_span(make_wav, tmp_path):
    """VTT path: span("vad") called, cut accumulated, no asr."""
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    sink = _SpySink()
    segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
        timing_sink=sink,
    )
    assert "vad" in sink.spans
    cut_subs = [s for s, _ in sink.adds if s == "cut"]
    assert len(cut_subs) >= 1        # one cut per segment
    asr_subs = [s for s, _ in sink.adds if s == "asr"]
    assert len(asr_subs) == 0        # vtt path: no ASR
    assert sink.flush_count == 1


def test_timing_sink_asr_path_accumulates_asr(make_wav, tmp_path):
    """ASR fallback path: asr sub-stage accumulated."""
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    sink = _SpySink()
    segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
        timing_sink=sink,
    )
    asr_subs = [s for s, _ in sink.adds if s == "asr"]
    assert len(asr_subs) >= 1
    assert sink.flush_count == 1


def test_timing_sink_null_by_default(make_wav, tmp_path):
    """No timing_sink arg -> _NullSink, does not raise, result unchanged."""
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
