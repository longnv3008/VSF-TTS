"""
audio_fixtures.py – Reusable audio-generation helpers shared across test modules.

Provides pure-Python utilities for creating synthetic audio (no real recordings
needed) and building argparse.Namespace values that mirror batch_vad.py defaults.
"""

from __future__ import annotations

import argparse
import math
import sys
import wave
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Path setup – lets other test files import batch_vad and vad.*
# ---------------------------------------------------------------------------
VAD_ROOT = Path(__file__).resolve().parents[1]        # …/VAD/
MODEL_DIR = VAD_ROOT / "models" / "vad" / "1"

for _p in (str(VAD_ROOT), str(MODEL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE: int = 16_000
SAMPLE_WIDTH: int = 2          # bytes – 16-bit PCM
CHANNELS: int = 1
DTYPE = np.int16
INT16_MAX: float = 32_767.0

MODEL_PATH = MODEL_DIR / "vad.onnx"

DEFAULT_VAD_ARGS: dict = dict(
    sample_rate=SAMPLE_RATE,
    chunk_ms=64,
    model_chunk_ms=32,
    context_ms=4,
    reset_duration=5.0,
    threshold=0.70,
    negative_threshold=None,
    min_volume=0.60,
    start_secs=0.10,
    stop_secs=0.45,
    merge_gap_secs=0.50,
    min_speech_secs=0.08,
    refine_boundaries=False,
    refine_energy_db_below_peak=35.0,
    refine_energy_min_rms=1e-4,
    refine_search_pad_ms=700.0,
    refine_pad_ms=0.0,
    refine_min_speech_ms=64.0,
    refine_max_gap_ms=160.0,
    model=MODEL_PATH,
)


# ---------------------------------------------------------------------------
# Audio generators
# ---------------------------------------------------------------------------

def make_silence(duration_secs: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return int16 array of pure digital silence."""
    return np.zeros(int(duration_secs * sample_rate), dtype=DTYPE)


def make_sine(
    duration_secs: float,
    freq_hz: float = 440.0,
    amplitude: float = 0.8,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Return int16 array of a sine tone loud enough to trigger volume gate."""
    t = np.arange(int(duration_secs * sample_rate)) / sample_rate
    return (np.sin(2.0 * math.pi * freq_hz * t) * amplitude * INT16_MAX).astype(DTYPE)


def make_noise(
    duration_secs: float,
    amplitude: float = 0.8,
    sample_rate: int = SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Return int16 array of Gaussian white noise."""
    if rng is None:
        rng = np.random.default_rng(42)
    n = int(duration_secs * sample_rate)
    raw = rng.standard_normal(n) * amplitude * INT16_MAX
    return raw.clip(-INT16_MAX - 1, INT16_MAX).astype(DTYPE)


def make_mixed(
    pattern: list[tuple[str, float]],
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Build a composite waveform from a pattern list.

    Parameters
    ----------
    pattern:
        List of (kind, duration_secs) where kind is one of:
        ``"silence"``, ``"speech"`` / ``"sine"``, ``"noise"``.

    Example
    -------
    >>> audio = make_mixed([("silence", 0.5), ("speech", 1.0), ("silence", 0.3)])
    """
    chunks: list[np.ndarray] = []
    for kind, duration in pattern:
        if kind == "silence":
            chunks.append(make_silence(duration, sample_rate))
        elif kind in ("speech", "sine"):
            chunks.append(make_sine(duration, sample_rate=sample_rate))
        elif kind == "noise":
            chunks.append(make_noise(duration, sample_rate=sample_rate))
        else:
            raise ValueError(f"Unknown audio kind: {kind!r}")
    return np.concatenate(chunks).astype(DTYPE)


# ---------------------------------------------------------------------------
# WAV helpers
# ---------------------------------------------------------------------------

def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    """Write a mono int16 numpy array to a WAV file. Returns the path."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return path


# ---------------------------------------------------------------------------
# argparse.Namespace factory
# ---------------------------------------------------------------------------

def make_vad_args(**overrides) -> argparse.Namespace:
    """
    Return an ``argparse.Namespace`` with the same defaults as
    ``batch_vad.parse_args()``.  Pass keyword overrides for specific params.

    Example
    -------
    >>> args = make_vad_args(threshold=0.5, refine_boundaries=True)
    """
    params = {**DEFAULT_VAD_ARGS, **overrides}
    return argparse.Namespace(**params)
