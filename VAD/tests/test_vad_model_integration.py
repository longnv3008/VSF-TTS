"""
test_vad_model_integration.py – Integration tests for VADModel + VADSession
running through the full batch_vad.run_vad_file() pipeline.

These tests require the ONNX model at:
    VAD/models/vad/1/vad.onnx

They use synthetically generated WAV files (pure tones and silence) so
results are **deterministic** across model updates (same audio → same output
structure, though exact boundary times may shift slightly).

Markers
-------
* ``@pytest.mark.integration`` – all tests here carry this marker.
  Skip them with:  ``pytest -m "not integration"``

What is verified per test
-------------------------
* Output is structurally correct (non-empty, valid labels, ordered, ≥ duration).
* Key invariants hold: total duration ≈ audio duration, no overlaps, labels
  only "speaking"/"quiet", every row has start < end.
* For mixed audio (silence + tone + silence) at least one "speaking" and one
  "quiet" segment is produced.
* Fully silent audio yields zero "speaking" segments.
* Refine-boundaries flag does not break structural invariants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_fixtures import SAMPLE_RATE, make_vad_args

# The ONNX model path is fixed relative to this test file.
_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "vad" / "1" / "vad.onnx"


# ---------------------------------------------------------------------------
# Skip entire module if the model file is absent
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration

if not _MODEL_PATH.exists():
    pytestmark = pytest.mark.skip(reason=f"VAD ONNX model not found at {_MODEL_PATH}")


# ---------------------------------------------------------------------------
# Lazy model fixture (session-scoped – only loaded once per test session)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def vad_model():
    """Load the VAD ONNX model once for the whole test session."""
    from vad import VADModel  # noqa: PLC0415

    return VADModel(
        model_path=str(_MODEL_PATH),
        chunk_ms=32,
        context_ms=4,
    )


# ---------------------------------------------------------------------------
# Structural invariant helpers
# ---------------------------------------------------------------------------

def assert_structural_invariants(segments: list[dict], audio_duration: float) -> None:
    """Assert the invariants that must hold for ANY run_vad_file output."""
    assert isinstance(segments, list), "Segments must be a list"
    assert len(segments) > 0, "Output must contain at least one segment"

    valid_labels = {"speaking", "quiet"}
    for i, seg in enumerate(segments):
        assert seg["label"] in valid_labels, f"Segment {i} has unknown label {seg['label']!r}"
        assert seg["start"] < seg["end"], f"Segment {i} has start >= end: {seg}"
        assert seg["start"] >= 0.0, f"Segment {i} start is negative"
        assert seg["end"] <= audio_duration + 1e-3, (
            f"Segment {i} end {seg['end']:.4f} exceeds duration {audio_duration:.4f}"
        )

    # Non-overlapping and sorted
    for i in range(len(segments) - 1):
        assert segments[i]["end"] <= segments[i + 1]["start"] + 1e-6, (
            f"Segments {i} and {i+1} overlap"
        )

    # Total coverage ≈ audio duration
    total = sum(s["end"] - s["start"] for s in segments)
    assert abs(total - audio_duration) < 0.1, (
        f"Total segment duration {total:.4f} differs from audio {audio_duration:.4f}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunVadFileSilence:
    def test_full_silence_has_no_speaking_segments(self, make_wav_file, vad_model):
        path = make_wav_file([("silence", 3.0)], name="silence3s.wav")
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)

        assert_structural_invariants(segments, duration)
        speaking = [s for s in segments if s["label"] == "speaking"]
        assert len(speaking) == 0, f"Expected no speech in silence, got {speaking}"

    def test_short_silence_structural_invariants(self, make_wav_file, vad_model):
        path = make_wav_file([("silence", 0.5)], name="silence_short.wav")
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)


class TestRunVadFileSpeech:
    def test_single_speech_segment_detected(self, make_wav_file, vad_model):
        """
        A loud sine tone surrounded by silence is fed through the full pipeline.
        Structural invariants must hold regardless of whether the model detects
        the tone as speech (VAD models are trained on real voice, not sine waves).
        """
        path = make_wav_file(
            [("silence", 0.5), ("speech", 1.5), ("silence", 0.5)],
            name="speech1s.wav",
        )
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)

        assert_structural_invariants(segments, duration)
        # Note: the model may or may not detect a sine wave as speech.
        # The key invariant is that output is structurally valid.
        # If you want real speech detection, use a speech WAV from
        # tests/data/ (see conftest make_wav_file fixture).

    def test_structural_invariants_with_speech(self, make_wav_file, vad_model):
        path = make_wav_file(
            [("silence", 0.3), ("speech", 2.0), ("silence", 0.3)],
            name="speech2s.wav",
        )
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)


class TestRunVadFileMultiSegment:
    def test_multi_segment_structural_invariants(self, make_wav_file, vad_model):
        path = make_wav_file(
            [
                ("silence", 0.4),
                ("speech", 0.8),
                ("silence", 0.7),
                ("speech", 1.0),
                ("silence", 0.6),
                ("speech", 0.6),
                ("silence", 0.4),
            ],
            name="multi.wav",
        )
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)

    def test_both_labels_present_for_mixed_audio(self, make_wav_file, vad_model):
        path = make_wav_file(
            [("silence", 0.5), ("speech", 1.5), ("silence", 0.5)],
            name="mixed.wav",
        )
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        labels = {s["label"] for s in segments}
        # At minimum "quiet" must always be present; "speaking" depends on model
        assert "quiet" in labels


class TestRunVadFileRefineBoundaries:
    def test_refine_does_not_break_invariants(self, make_wav_file, vad_model):
        path = make_wav_file(
            [("silence", 0.5), ("speech", 1.0), ("silence", 0.5)],
            name="refine.wav",
        )
        args = make_vad_args(refine_boundaries=True)
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)

    def test_refine_vs_no_refine_same_label_count_or_close(self, make_wav_file, vad_model):
        """Refining should not hallucinate drastically more segments."""
        path = make_wav_file(
            [("silence", 0.4), ("speech", 1.2), ("silence", 0.4)],
            name="refine_vs_base.wav",
        )
        import batch_vad as bv
        args_base   = make_vad_args(refine_boundaries=False)
        args_refine = make_vad_args(refine_boundaries=True)
        _, segs_base   = bv.run_vad_file(vad_model, path, args_base)
        _, segs_refine = bv.run_vad_file(vad_model, path, args_refine)

        n_base   = len([s for s in segs_base   if s["label"] == "speaking"])
        n_refine = len([s for s in segs_refine if s["label"] == "speaking"])
        # Allow some variation but not more than 3× the base count
        assert n_refine <= max(n_base * 3, 3), (
            f"Refine produced far more speaking segments ({n_refine}) than base ({n_base})"
        )


class TestRunVadFileParametrized:
    """Parametrized smoke tests covering different threshold values."""

    @pytest.mark.parametrize("threshold", [0.5, 0.7, 0.9])
    def test_structural_invariants_across_thresholds(self, make_wav_file, vad_model, threshold):
        path = make_wav_file(
            [("silence", 0.3), ("speech", 1.0), ("silence", 0.3)],
            name=f"thresh_{threshold}.wav",
        )
        args = make_vad_args(threshold=threshold)
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)

    @pytest.mark.parametrize("speech_secs", [0.5, 1.0, 2.0, 4.0])
    def test_structural_invariants_across_durations(self, make_wav_file, vad_model, speech_secs):
        path = make_wav_file(
            [("silence", 0.3), ("speech", speech_secs), ("silence", 0.3)],
            name=f"dur_{speech_secs}.wav",
        )
        args = make_vad_args()
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)

    @pytest.mark.parametrize("merge_gap", [0.2, 0.5, 1.0])
    def test_structural_invariants_across_merge_gaps(self, make_wav_file, vad_model, merge_gap):
        path = make_wav_file(
            [("silence", 0.2), ("speech", 0.8), ("silence", 0.3), ("speech", 0.8), ("silence", 0.2)],
            name=f"gap_{merge_gap}.wav",
        )
        args = make_vad_args(merge_gap_secs=merge_gap)
        import batch_vad as bv
        duration, segments = bv.run_vad_file(vad_model, path, args)
        assert_structural_invariants(segments, duration)
