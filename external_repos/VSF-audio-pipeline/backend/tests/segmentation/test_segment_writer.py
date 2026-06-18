import wave

from app.modules.audio_pipeline.application.segmentation.segment_writer import (
    cut_wav_segment,
    write_text,
)


def test_cut_wav_segment_length(make_wav, tmp_path):
    src = make_wav(seconds=2.0)
    dst = tmp_path / "out" / "seg.wav"
    cut_wav_segment(src, dst, start_sec=0.5, end_sec=1.5)
    assert dst.exists()
    with wave.open(str(dst), "rb") as r:
        assert r.getframerate() == 16000
        # ~1.0s @ 16k = ~16000 frames
        assert abs(r.getnframes() - 16000) <= 2


def test_write_text(tmp_path):
    p = tmp_path / "a" / "b.txt"
    write_text(p, "xin chao")
    assert p.read_text(encoding="utf-8") == "xin chao"
