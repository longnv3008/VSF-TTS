from pathlib import Path

from app.core.config import settings
from app.modules.audio_pipeline.application import pipeline_service
from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService


def test_separate_vocals_disabled_returns_rows_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "demucs_enabled", False)
    service = AudioPipelineService()
    rows = [{"raw_file_path": "/x/raw.webm", "source_url": "u"}]

    out = service.separate_vocals(rows)

    assert out == rows  # identity passthrough, no torch needed


def test_separate_vocals_auto_skips_when_clean(make_wav, tmp_path, monkeypatch):
    # auto: noise floor thấp (sạch) -> bỏ Demucs, chỉ ffmpeg.
    monkeypatch.setattr(settings, "demucs_enabled", True)
    monkeypatch.setattr(settings, "demucs_mode", "auto")
    monkeypatch.setattr(settings, "demucs_noise_floor_db", -50.0)
    monkeypatch.setattr(pipeline_service, "measure_noise_floor_db", lambda *a, **k: -68.0)
    service = AudioPipelineService()
    events = []
    monkeypatch.setattr(service, "_notify_url_stage", lambda **kwargs: events.append(kwargs))

    raw = make_wav(seconds=0.5, name="raw.wav")
    rows = [{"raw_file_path": str(raw), "source_url": "u", "video_id": "v"}]

    out = service.separate_vocals(rows)

    assert out[0]["raw_file_path"] == str(raw)
    assert out[0]["audio_filter_backend"] == "ffmpeg"
    assert out[0]["audio_filter_reason"].startswith("auto_noise_low")
    assert [event["status"] for event in events] == ["completed"]


def test_separate_vocals_auto_uses_demucs_when_noisy(make_wav, tmp_path, monkeypatch):
    # auto: noise floor cao (nhiễu) -> route sang Demucs.
    monkeypatch.setattr(settings, "demucs_enabled", True)
    monkeypatch.setattr(settings, "demucs_mode", "auto")
    monkeypatch.setattr(settings, "demucs_noise_floor_db", -50.0)
    monkeypatch.setattr(pipeline_service, "measure_noise_floor_db", lambda *a, **k: -38.0)
    service = AudioPipelineService()
    events = []
    monkeypatch.setattr(service, "_notify_url_stage", lambda **kwargs: events.append(kwargs))

    raw = make_wav(seconds=0.5, name="raw.wav")
    vocal = tmp_path / "vocals.wav"
    vocal.write_bytes(raw.read_bytes())
    monkeypatch.setattr(
        pipeline_service, "demucs_separate_vocals",
        lambda input_path, out_dir, *, command, model, device: vocal,
    )

    rows = [{"raw_file_path": str(raw), "source_url": "u", "video_id": "v"}]
    out = service.separate_vocals(rows)

    assert out[0]["raw_file_path"] == str(vocal)
    assert out[0]["audio_filter_backend"] == "demucs"
    assert out[0]["audio_filter_reason"].startswith("auto_noise_high")


def test_separate_vocals_auto_unknown_falls_back_to_ffmpeg(make_wav, tmp_path, monkeypatch):
    # probe lỗi (vd ffmpeg thiếu) -> fallback an toàn: không Demucs.
    monkeypatch.setattr(settings, "demucs_enabled", True)
    monkeypatch.setattr(settings, "demucs_mode", "auto")

    def boom(*a, **k):
        raise RuntimeError("no ffmpeg")

    monkeypatch.setattr(pipeline_service, "measure_noise_floor_db", boom)
    service = AudioPipelineService()
    monkeypatch.setattr(service, "_notify_url_stage", lambda **kwargs: None)

    raw = make_wav(seconds=0.5, name="raw.wav")
    rows = [{"raw_file_path": str(raw), "source_url": "u", "video_id": "v"}]

    out = service.separate_vocals(rows)

    assert out[0]["audio_filter_backend"] == "ffmpeg"
    assert out[0]["audio_filter_reason"] == "auto_noise_unknown"


def test_separate_vocals_rewrites_raw_path_to_vocal(make_wav, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demucs_enabled", True)
    monkeypatch.setattr(settings, "demucs_mode", "on")
    service = AudioPipelineService()
    events = []
    monkeypatch.setattr(service, "_notify_url_stage", lambda **kwargs: events.append(kwargs))

    raw = make_wav(seconds=0.5, name="raw.wav")
    vocal = tmp_path / "vocals.wav"
    vocal.write_bytes(raw.read_bytes())

    # Thay Demucs thật bằng fake (không cần torch).
    def fake_separate(input_path, out_dir, *, command, model, device):
        assert Path(input_path) == raw
        return vocal

    monkeypatch.setattr(pipeline_service, "demucs_separate_vocals", fake_separate)

    rows = [{"raw_file_path": str(raw), "source_url": "u", "video_id": "v"}]
    out = service.separate_vocals(rows)

    assert out[0]["raw_file_path"] == str(vocal)        # normalize sẽ hạ 16k vocal
    assert out[0]["original_raw_file_path"] == str(raw)
    assert not raw.exists()                              # raw gốc bị xóa tiết kiệm disk
    assert [event["status"] for event in events] == ["started", "completed"]
    assert [event["step"] for event in events] == ["demucs", "demucs"]


def test_separate_vocals_falls_back_to_raw_on_failure(make_wav, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demucs_enabled", True)
    monkeypatch.setattr(settings, "demucs_mode", "on")
    service = AudioPipelineService()
    events = []
    monkeypatch.setattr(service, "_notify_url_stage", lambda **kwargs: events.append(kwargs))

    raw = make_wav(seconds=0.5, name="raw.wav")

    def boom(input_path, out_dir, *, command, model, device):
        raise RuntimeError("no torch")

    monkeypatch.setattr(pipeline_service, "demucs_separate_vocals", boom)

    rows = [{"raw_file_path": str(raw), "source_url": "u", "video_id": "v"}]
    out = service.separate_vocals(rows)

    assert out[0]["raw_file_path"] == str(raw)        # fell back to raw, not aborted
    assert "original_raw_file_path" not in out[0]
    assert raw.exists()                                # raw NOT deleted on failure
    assert [event["status"] for event in events] == ["started", "failed"]


def test_separate_vocals_continues_batch_after_one_failure(make_wav, tmp_path, monkeypatch):
    # "Never abort batch": a failing row falls back to raw, the next row still separates.
    monkeypatch.setattr(settings, "demucs_enabled", True)
    monkeypatch.setattr(settings, "demucs_mode", "on")
    service = AudioPipelineService()

    bad = make_wav(seconds=0.5, name="bad.wav")
    good = make_wav(seconds=0.5, name="good.wav")
    vocal = tmp_path / "good_vocals.wav"
    vocal.write_bytes(good.read_bytes())

    def fake_separate(input_path, out_dir, *, command, model, device):
        if Path(input_path) == bad:
            raise RuntimeError("no torch")
        return vocal

    monkeypatch.setattr(pipeline_service, "demucs_separate_vocals", fake_separate)

    rows = [
        {"raw_file_path": str(bad), "source_url": "u1", "video_id": "v1"},
        {"raw_file_path": str(good), "source_url": "u2", "video_id": "v2"},
    ]
    out = service.separate_vocals(rows)

    assert len(out) == 2                               # batch not aborted
    assert out[0]["raw_file_path"] == str(bad)         # failed row -> raw kept
    assert bad.exists()
    assert out[1]["raw_file_path"] == str(vocal)       # good row -> vocal stem
    assert not good.exists()                            # good raw deleted after success
