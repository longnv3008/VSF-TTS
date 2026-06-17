"""
test_vad_session.py – Unit tests for VADSession state-machine logic.

These tests exercise VADSession.process() WITHOUT the ONNX model by
injecting hand-crafted probability arrays.  They verify the state
transitions (QUIET → STARTING → SPEAKING → STOPPING → QUIET) and the
resulting SPEAKING / QUIET signals.

Strategy
--------
- Use probabilities of 1.0 to simulate confident speech.
- Use probabilities of 0.0 to simulate confident silence.
- Construct audio chunks whose volume exceeds min_volume so the volume
  gate does not block detection.
"""

from __future__ import annotations

import numpy as np
import pytest

from audio_fixtures import SAMPLE_RATE, make_sine, make_silence

# Import VAD internals via the path added by conftest.py
from vad import VADParams, VADSession, VoiceState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
CHUNK_MS = 32
SAMPLE_RATE_16K = SAMPLE_RATE


def _make_session(
    threshold: float = 0.70,
    start_secs: float = 0.10,
    stop_secs: float = 0.45,
    min_volume: float = 0.60,
    chunk_ms: int = CHUNK_MS,
    context_ms: int = 4,
) -> VADSession:
    params = VADParams(
        confidence=threshold,
        start_secs=start_secs,
        stop_secs=stop_secs,
        min_volume=min_volume,
    )
    return VADSession(
        param=params,
        context_ms=context_ms,
        chunk_ms=chunk_ms,
        sample_rate=SAMPLE_RATE_16K,
    )


def _loud_chunk(chunk_ms: int = CHUNK_MS, sample_rate: int = SAMPLE_RATE_16K) -> np.ndarray:
    """Return a loud sine chunk guaranteed to pass the volume gate."""
    return make_sine(chunk_ms / 1000.0, amplitude=0.85, sample_rate=sample_rate)


def _silent_chunk(chunk_ms: int = CHUNK_MS, sample_rate: int = SAMPLE_RATE_16K) -> np.ndarray:
    """Return a near-silent chunk that fails the volume gate."""
    return make_silence(chunk_ms / 1000.0, sample_rate=sample_rate)


def _process_n_frames(
    session: VADSession,
    n_frames: int,
    probability: float,
    chunk_fn,
) -> list[dict]:
    """Feed n_frames identical frames through session.process()."""
    chunk_ms = session._chunk_ms
    signals = []
    for _ in range(n_frames):
        chunk = chunk_fn(chunk_ms)
        probs = np.array([probability], dtype=np.float32)
        signals.extend(session.process(chunk, probs))
    return signals


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------
class TestVADSessionInit:
    def test_starts_quiet(self):
        session = _make_session()
        assert session._voice_state == VoiceState.QUIET

    def test_context_and_state_zeros(self):
        session = _make_session()
        state, context = session.get_state()
        assert not state.any()
        assert not context.any()

    def test_reset_state_clears_processed(self):
        session = _make_session()
        chunk = _loud_chunk()
        probs = np.array([1.0])
        session.process(chunk, probs)
        session.reset_state()
        assert session._current_processed == 0.0


# ---------------------------------------------------------------------------
# STARTING → SPEAKING transition
# ---------------------------------------------------------------------------
class TestStartSpeaking:
    def test_not_speaking_after_insufficient_frames(self):
        """Below start_secs threshold – no SPEAKING signal should be emitted."""
        session = _make_session(start_secs=0.10, chunk_ms=CHUNK_MS)
        # start_frames = round(0.10 * 1000 / 32) = 3
        # Send only 2 high-confidence loud frames
        signals = _process_n_frames(session, 2, 1.0, _loud_chunk)
        speech_signals = [s for s in signals if s["signal_type"] == "SPEAKING"]
        assert not speech_signals

    def test_speaking_after_sufficient_frames(self):
        """Once enough consecutive high-volume speech frames arrive, SPEAKING fires."""
        session = _make_session(start_secs=0.10, chunk_ms=CHUNK_MS)
        # Volume smoothing needs a few frames to ramp up; send 8 to be safe.
        signals = _process_n_frames(session, 8, 1.0, _loud_chunk)
        speech_signals = [s for s in signals if s["signal_type"] == "SPEAKING"]
        assert len(speech_signals) >= 1

    def test_speaking_signal_at_is_non_negative(self):
        session = _make_session(start_secs=0.10)
        signals = _process_n_frames(session, 10, 1.0, _loud_chunk)
        for sig in signals:
            assert sig["signal_at"] >= 0.0


# ---------------------------------------------------------------------------
# SPEAKING → STOPPING → QUIET transition
# ---------------------------------------------------------------------------
class TestStopSpeaking:
    def test_quiet_signal_emitted_after_stop_secs(self):
        session = _make_session(start_secs=0.10, stop_secs=0.45, chunk_ms=CHUNK_MS)
        # First: speak until SPEAKING fires
        _process_n_frames(session, 10, 1.0, _loud_chunk)
        assert session._voice_state == VoiceState.SPEAKING

        # Then: go silent long enough to trigger STOPPING → QUIET
        # stop_frames = round(0.45 * 1000 / 32) = 14
        signals = _process_n_frames(session, 20, 0.0, _silent_chunk)
        quiet_signals = [s for s in signals if s["signal_type"] == "QUIET"]
        assert len(quiet_signals) >= 1

    def test_state_returns_to_quiet(self):
        session = _make_session(start_secs=0.10, stop_secs=0.45, chunk_ms=CHUNK_MS)
        _process_n_frames(session, 10, 1.0, _loud_chunk)
        _process_n_frames(session, 20, 0.0, _silent_chunk)
        assert session._voice_state == VoiceState.QUIET

    def test_brief_silence_does_not_trigger_quiet(self):
        """A silence shorter than stop_secs should not emit QUIET."""
        session = _make_session(start_secs=0.10, stop_secs=0.45, chunk_ms=CHUNK_MS)
        _process_n_frames(session, 10, 1.0, _loud_chunk)
        # stop_frames = 14; send only 5 silent frames
        signals = _process_n_frames(session, 5, 0.0, _silent_chunk)
        quiet_signals = [s for s in signals if s["signal_type"] == "QUIET"]
        assert not quiet_signals


# ---------------------------------------------------------------------------
# Volume gating
# ---------------------------------------------------------------------------
class TestVolumeGating:
    def test_silent_audio_never_triggers_speaking(self):
        """Even with high model probability, silent audio must not fire SPEAKING."""
        session = _make_session(min_volume=0.60)
        # _silent_chunk has volume ≈ 0.0, far below 0.60
        signals = _process_n_frames(session, 20, 1.0, _silent_chunk)
        speech_signals = [s for s in signals if s["signal_type"] == "SPEAKING"]
        assert not speech_signals


# ---------------------------------------------------------------------------
# is_reset
# ---------------------------------------------------------------------------
class TestIsReset:
    def test_not_reset_before_threshold(self):
        session = _make_session()
        assert not session.is_reset(threshold=5.0)

    def test_reset_after_threshold(self):
        session = _make_session()
        # Feed enough audio to exceed 5 seconds
        for _ in range(200):   # 200 × 32 ms = 6.4 s
            chunk = _loud_chunk()
            session.process(chunk, np.array([0.0]))
        assert session.is_reset(threshold=5.0)


# ---------------------------------------------------------------------------
# get_state / set_state round-trip
# ---------------------------------------------------------------------------
class TestGetSetState:
    def test_state_round_trips(self):
        session = _make_session()
        state_before, ctx_before = session.get_state()
        session.set_state(state_before, ctx_before)
        state_after, ctx_after = session.get_state()
        np.testing.assert_array_equal(state_before, state_after)
        np.testing.assert_array_equal(ctx_before, ctx_after)

    def test_get_state_returns_copies(self):
        session = _make_session()
        state, ctx = session.get_state()
        state[:] = 99.0
        state2, _ = session.get_state()
        assert not np.all(state2 == 99.0)
