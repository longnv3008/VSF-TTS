from app.modules.audio_pipeline.application.segmentation.asr_adapter import FasterWhisperAdapter


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append((audio, language))
        return [_FakeSegment(" xin "), _FakeSegment("chao ")], {"language": language}


def test_transcribe_joins_and_forces_vietnamese(tmp_path):
    fake = _FakeModel()
    adapter = FasterWhisperAdapter(model_name="tiny", device="cpu", model=fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")  # nội dung không quan trọng vì model bị fake
    text = adapter.transcribe(wav)
    assert text == "xin chao"
    assert fake.calls[0][1] == "vi"


def test_model_lazy_built_once(tmp_path, monkeypatch):
    built = {"count": 0}

    def fake_builder(self):
        built["count"] += 1
        return _FakeModel()

    monkeypatch.setattr(FasterWhisperAdapter, "_build_model", fake_builder)
    adapter = FasterWhisperAdapter(model_name="tiny", device="cpu")
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    adapter.transcribe(wav)
    adapter.transcribe(wav)
    assert built["count"] == 1
