from __future__ import annotations

import sys
import wave
from pathlib import Path

import pytest

# Cho phép `import app...` khi chạy pytest từ thư mục backend.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def make_wav(tmp_path):
    """Tạo file WAV mono 16k s16 chứa toàn silence dài `seconds` giây."""

    def _make(seconds: float = 1.0, sample_rate: int = 16000, name: str = "sample.wav") -> Path:
        path = tmp_path / name
        frames = int(seconds * sample_rate)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(b"\x00\x00" * frames)
        return path

    return _make
