import csv

from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService
from app.modules.audio_pipeline.application.segmentation.types import SpeechRegion

VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
cau mot.

00:00:01.200 --> 00:00:02.000
cau hai.
"""


class _FakeVad:
    def detect_regions(self, wav_path):
        return 2.0, [SpeechRegion(0.0, 1.0), SpeechRegion(1.2, 2.0)]


class _FakeAsr:
    def transcribe(self, wav_path):
        return "khong dung"


def test_end_to_end_vtt_path(make_wav, tmp_path, monkeypatch):
    service = AudioPipelineService()
    monkeypatch.setattr(service, "segments_dir", tmp_path / "segments")
    monkeypatch.setattr(service, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(service, "_build_segment_dependencies", lambda: (_FakeVad(), _FakeAsr()))

    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": str(vtt),
    }]

    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")

    with manifest.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {r["text"] for r in rows} == {"cau mot.", "cau hai."}
    assert all(r["transcript_source"] == "vtt" for r in rows)
    for r in rows:
        assert (tmp_path / "segments" / "b1" / "yt_vid" / f"{r['segment_id']}.wav").exists()
