"""
conftest.py – Pytest fixtures for the VAD generic test suite.

All reusable helpers (audio generators, wav writers, arg factories) live in
``audio_fixtures.py``.  This file only declares pytest fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pytest

# Add the tests/ directory itself so `audio_fixtures` is importable
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from audio_fixtures import (  # noqa: F401 – re-export for convenience
    SAMPLE_RATE,
    make_mixed,
    make_silence,
    make_sine,
    make_vad_args,
    write_wav,
)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def tmp_wav_dir(tmp_path: Path) -> Path:
    """Temporary directory for tests to write WAV files into."""
    return tmp_path


@pytest.fixture(scope="function")
def make_wav_file(tmp_path: Path) -> Callable[..., Path]:
    """
    Factory fixture – create a WAV file in tmp_path.

    Usage::
        def test_foo(make_wav_file):
            # from a pattern list:
            path = make_wav_file([("silence", 0.5), ("speech", 1.0)])
            # from a raw int16 array:
            path = make_wav_file(audio_array, name="custom.wav")
    """
    def _factory(
        source: list[tuple[str, float]] | np.ndarray,
        name: str = "test.wav",
        sample_rate: int = SAMPLE_RATE,
    ) -> Path:
        if isinstance(source, list):
            audio = make_mixed(source, sample_rate)
        else:
            audio = np.asarray(source, dtype=np.int16)
        return write_wav(tmp_path / name, audio, sample_rate)

    return _factory


@pytest.fixture(scope="function")
def silence_wav(tmp_path: Path) -> Path:
    """A 2-second silence WAV file."""
    return write_wav(tmp_path / "silence.wav", make_silence(2.0))


@pytest.fixture(scope="function")
def speech_wav(tmp_path: Path) -> Path:
    """A WAV: 0.5 s silence → 1.5 s sine tone (speech proxy) → 0.5 s silence."""
    audio = make_mixed([("silence", 0.5), ("speech", 1.5), ("silence", 0.5)])
    return write_wav(tmp_path / "speech.wav", audio)


@pytest.fixture(scope="function")
def multi_segment_wav(tmp_path: Path) -> Path:
    """A WAV with three speech segments separated by silences."""
    audio = make_mixed([
        ("silence", 0.3),
        ("speech",  0.8),
        ("silence", 0.6),
        ("speech",  1.0),
        ("silence", 0.5),
        ("speech",  0.5),
        ("silence", 0.4),
    ])
    return write_wav(tmp_path / "multi_segment.wav", audio)


@pytest.fixture(scope="function")
def vad_args():
    """Default VAD argparse Namespace – mirrors CLI parse_args() defaults."""
    return make_vad_args()
