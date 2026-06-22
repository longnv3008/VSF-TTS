import json

from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService
from app.modules.audio_pipeline.application.segmentation.types import SpeechRegion


VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
cau mot.
"""


class _FakeVad:
    def detect_regions(self, wav_path):
        return 2.0, [SpeechRegion(0.0, 1.0)]


class _FakeAsr:
    def transcribe(self, wav_path):
        return "loi asr"


def test_segment_and_label_and_metadata(make_wav, tmp_path, monkeypatch):
    service = AudioPipelineService()
    monkeypatch.setattr(service, "segments_dir", tmp_path / "segments")
    monkeypatch.setattr(service, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(
        service, "_build_segment_dependencies",
        lambda: (_FakeVad(), _FakeAsr()),
    )

    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": str(vtt),
    }]
    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    assert len(seg_rows) == 1
    assert seg_rows[0]["transcript_source"] == "vtt"

    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")
    assert manifest.exists()
    jsonl = manifest.with_suffix(".jsonl")
    assert jsonl.exists()
    first = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert first["segment_id"] == "yt_vid__sent000001"
    assert "quality_label" in first
    assert "quality_score" in first


def test_rebuild_preserves_review_columns(make_wav, tmp_path, monkeypatch):
    from app.utils.filesystem import read_csv, write_csv
    from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
        SEGMENT_METADATA_FIELDS,
    )

    service = AudioPipelineService()
    monkeypatch.setattr(service, "segments_dir", tmp_path / "segments")
    monkeypatch.setattr(service, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(
        service, "_build_segment_dependencies", lambda: (_FakeVad(), _FakeAsr())
    )
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": str(vtt),
    }]
    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")

    # Simulate one review pass: write reference + manual_wer + review_status into CSV.
    rows = read_csv(manifest)
    rows[0]["reference"] = "cau mot"
    rows[0]["manual_wer"] = "0.25"
    rows[0]["review_status"] = "reviewed"
    write_csv(manifest, SEGMENT_METADATA_FIELDS, rows)

    # Re-run build with same segment_id -> review columns must survive.
    service.build_segment_metadata(seg_rows, batch_name="b1")
    after = read_csv(manifest)[0]
    assert after["reference"] == "cau mot"
    assert after["manual_wer"] == "0.25"
    assert after["review_status"] == "reviewed"
