from app.modules.audio_pipeline.application.segmentation.segment_service import segment_video
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion
import wave


def _cfg():
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45, use_vtt_transcript=True,
        pad_sec=0.0, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
        vtt_overlap_sec=0.0,
        quality_gate_enabled=False,
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

VTT_TWO_LINES = """WEBVTT

00:00:00.000 --> 00:00:01.000
xin chao.

00:00:01.100 --> 00:00:02.000
cac ban.
"""

VTT_THREE_LINES = """WEBVTT

00:00:09.200 --> 00:00:11.000
phan mot.

00:00:11.100 --> 00:00:13.500
phan hai.

00:00:13.600 --> 00:00:15.800
phan ba.
"""

VTT_TIMED_BOUNDARY = """WEBVTT

00:00:33.480 --> 00:00:36.430
moi.<00:00:34.680><c> Theo</c><00:00:34.879><c> So</c><00:00:35.079><c> Xay</c><00:00:35.239><c> dung,</c>
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


def test_vtt_path_ignores_vad_boundary_and_keeps_subtitle_timing(make_wav, tmp_path):
    wav = make_wav(seconds=3.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(1.5, 2.5)], 3.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows == []


def test_vtt_segments_expand_to_outer_vtt_bounds_without_extra_overlap(make_wav, tmp_path):
    wav = make_wav(seconds=3.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT_TWO_LINES, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 2.0)], 3.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["start"] == 0.0
    assert rows[0]["end"] == 2.0
    assert rows[0]["text"] == "xin chao. cac ban."


def test_vtt_snap_uses_nearest_lower_start_and_nearest_upper_end(make_wav, tmp_path):
    wav = make_wav(seconds=20.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT_THREE_LINES, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(10.0, 15.0)], 20.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["start"] == 9.2
    assert rows[0]["end"] == 15.8
    assert rows[0]["text"] == "phan mot. phan hai. phan ba."


def test_vtt_text_is_rebuilt_from_exact_segment_interval(make_wav, tmp_path):
    cfg = SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45, use_vtt_transcript=True,
        pad_sec=0.0, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
        vtt_overlap_sec=0.0,
        quality_gate_enabled=False,
    )
    wav = make_wav(seconds=40.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT_TIMED_BOUNDARY, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row,
        vad_client=_FakeVad([SpeechRegion(34.68, 36.43)], 40.0),
        asr_adapter=_FakeAsr(),
        config=cfg,
        segments_root=tmp_path / "segments",
        batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["start"] == 33.48
    assert rows[0]["end"] == 36.43
    assert rows[0]["text"] == "moi. Theo So Xay dung,"


BLOCKLIST_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
Hãy đăng ký kênh
"""

PROMO_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn
"""

ACRONYM_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
khối n a t o họp
"""


def test_vtt_blocklisted_caption_dropped(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(BLOCKLIST_VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["transcript_source"] == "vtt"
    assert rows[0]["text"] == ""
    assert rows[0]["transcript_status"] == "missing"


def test_vtt_promo_caption_with_trailing_words_dropped(make_wav, tmp_path):
    # promo có chữ thừa quanh cụm -> exact-match cũ bỏ lọt, substring promo phải diệt
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(PROMO_VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["text"] == ""
    assert rows[0]["transcript_status"] == "missing"


def test_vtt_normalized_vlsp(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(ACRONYM_VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows[0]["text"] == "khối nato họp"


def test_no_vtt_skips_video(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows == []


def test_quality_gate_drops_silent_segment_before_write(make_wav, tmp_path):
    cfg = _cfg()
    cfg = SegmentationConfig(**{**cfg.__dict__, "quality_gate_enabled": True})
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=cfg, segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows[0]["text"] == ""
    assert rows[0]["transcript_status"] == "missing"
    assert rows[0]["quality_label"] == "low_quality"
    assert "low_rms" in rows[0]["quality_reasons"]


def test_quality_gate_keeps_loud_segment_with_reasonable_text(tmp_path):
    cfg = SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45, use_vtt_transcript=True,
        pad_sec=0.0, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
        quality_gate_enabled=True,
    )
    wav = tmp_path / "yt_vid.wav"
    sample_rate = 16000
    frames = int(2.0 * sample_rate)
    with wave.open(str(wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes((b"\x80\x0c" * frames))
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=cfg, segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows[0]["text"] == "xin chao cac ban."
    assert rows[0]["transcript_status"] == "ready"
    assert rows[0]["quality_label"] == "speech_clean"


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


def test_timing_sink_no_vtt_skips_without_asr(make_wav, tmp_path):
    """No VTT path: skip early, no asr sub-stage, still flushes once."""
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    sink = _SpySink()
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
        timing_sink=sink,
    )
    assert rows == []
    asr_subs = [s for s, _ in sink.adds if s == "asr"]
    assert len(asr_subs) == 0
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
    assert rows == []
