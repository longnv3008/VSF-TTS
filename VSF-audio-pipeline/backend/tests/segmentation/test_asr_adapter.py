from app.modules.audio_pipeline.application.segmentation.asr_adapter import FasterWhisperAdapter


class _FakeSegment:
    def __init__(self, text, no_speech_prob=0.0, avg_logprob=0.0):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob


class _FakeModel:
    def __init__(self, segments=None):
        self.calls = []
        self.last_kwargs = {}
        self._segments = (
            segments if segments is not None else [_FakeSegment(" xin "), _FakeSegment("chao ")]
        )

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append((audio, language))
        self.last_kwargs = kwargs
        return list(self._segments), {"language": language}


def _adapter(model):
    return FasterWhisperAdapter(model_name="tiny", device="cpu", model=model)


def test_transcribe_joins_and_forces_vietnamese(tmp_path):
    fake = _FakeModel()
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")  # nội dung không quan trọng vì model bị fake
    text = adapter.transcribe(wav)
    assert text == "xin chao"
    assert fake.calls[0][1] == "vi"


def test_decode_params_hardened(tmp_path):
    fake = _FakeModel()
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    adapter.transcribe(wav)
    kw = fake.last_kwargs
    assert kw["beam_size"] == 1
    assert kw["temperature"] == 0.0
    assert kw["condition_on_previous_text"] is False
    assert kw["no_speech_threshold"] == 0.6
    assert kw["vad_filter"] is True


def test_blocklisted_hallucination_dropped(tmp_path):
    fake = _FakeModel(segments=[_FakeSegment("Thank you for watching")])
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    assert adapter.transcribe(wav) == ""


def test_low_confidence_segment_rejected(tmp_path):
    fake = _FakeModel(segments=[_FakeSegment("nội dung mờ", no_speech_prob=0.9, avg_logprob=-2.0)])
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    assert adapter.transcribe(wav) == ""


def test_confident_speech_kept_despite_high_no_speech(tmp_path):
    # no_speech cao nhưng logprob ổn -> không loại
    fake = _FakeModel(segments=[_FakeSegment("nội dung thật", no_speech_prob=0.9, avg_logprob=-0.2)])
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    assert adapter.transcribe(wav) == "nội dung thật"


def test_repetition_loop_dropped(tmp_path):
    fake = _FakeModel(segments=[_FakeSegment(("loop " * 12).strip())])
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    assert adapter.transcribe(wav) == ""


def test_empty_segments_returns_empty(tmp_path):
    fake = _FakeModel(segments=[])
    adapter = _adapter(fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    assert adapter.transcribe(wav) == ""


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
