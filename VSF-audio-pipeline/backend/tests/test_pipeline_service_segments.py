import json

from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService
from app.modules.audio_pipeline.application.segmentation.types import SpeechRegion


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
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": "",
    }]
    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    assert len(seg_rows) == 1
    assert seg_rows[0]["transcript_source"] == "asr"

    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")
    assert manifest.exists()
    jsonl = manifest.with_suffix(".jsonl")
    assert jsonl.exists()
    first = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert first["segment_id"] == "yt_vid__sent000001"
    assert "quality_label" in first
    assert "quality_score" in first
