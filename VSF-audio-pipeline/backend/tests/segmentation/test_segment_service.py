from app.modules.audio_pipeline.application.segmentation.segment_service import segment_video
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion
import wave


def _cfg():
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45, use_vtt_transcript=True,
        pad_sec=0.0, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
        vtt_overlap_sec=0.2,
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


class _CountingAsr:
    def __init__(self, text="loi asr"):
        self.calls = 0
        self._text = text

    def transcribe(self, wav_path):
        self.calls += 1
        return self._text


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
    assert len(rows) == 1
    assert rows[0]["transcript_source"] == "vtt"
    assert rows[0]["start"] == 0.0
    assert rows[0]["end"] == 1.0
    assert rows[0]["vad_status"] == "no_overlap"


def test_vtt_segments_get_small_overlap_to_protect_boundaries(make_wav, tmp_path):
    wav = make_wav(seconds=3.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT_TWO_LINES, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 2.0)], 3.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 2
    assert rows[0]["end"] > 1.0
    assert rows[1]["start"] < 1.1


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
    # Không subtitle hợp lệ -> skip (bỏ hẳn ASR fallback sinh nhãn).
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows == []


def test_quality_gate_drops_silent_segment(make_wav, tmp_path):
    cfg = SegmentationConfig(**{**_cfg().__dict__, "quality_gate_enabled": True})
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


def test_quality_gate_keeps_loud_segment_with_vtt_text(tmp_path):
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


def test_wer_gate_off_does_not_call_asr(make_wav, tmp_path):
    # Mặc định gate tắt -> không gọi ASR, transcript VTT giữ nguyên ready.
    asr = _CountingAsr()
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=asr,
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert asr.calls == 0
    assert rows[0]["transcript_status"] == "ready"


def test_wer_gate_flags_divergent_asr(make_wav, tmp_path):
    # Gate bật + ASR lệch hẳn VTT -> flag needs_review, vẫn giữ text để review.
    cfg = SegmentationConfig(**{**_cfg().__dict__, "wer_gate_enabled": True, "wer_gate_max": 0.05})
    asr = _CountingAsr(text="hoan toan khac han")
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=asr,
        config=cfg, segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert asr.calls == 1
    assert rows[0]["transcript_status"] == "needs_review"
    assert rows[0]["quality_label"] == "needs_review"
    assert rows[0]["text"] == "xin chao cac ban."


def test_wer_gate_keeps_matching_asr(make_wav, tmp_path):
    # Gate bật + ASR khớp VTT -> WER 0 -> không flag.
    cfg = SegmentationConfig(**{**_cfg().__dict__, "wer_gate_enabled": True, "wer_gate_max": 0.05})
    asr = _CountingAsr(text="xin chao cac ban")
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=asr,
        config=cfg, segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert rows[0]["transcript_status"] == "ready"
    assert rows[0]["text"] == "xin chao cac ban."


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


def test_timing_sink_no_vtt_skips_and_flushes(make_wav, tmp_path):
    """No VTT -> skip video, no asr sub-stage, still flushes once."""
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
    """No timing_sink arg -> _NullSink, does not raise, VTT path returns a row."""
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
