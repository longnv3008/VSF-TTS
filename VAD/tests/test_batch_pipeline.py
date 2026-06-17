"""
test_batch_pipeline.py – End-to-end pipeline tests for batch_vad.py helpers
that sit above the model layer: collect_wav_files, read_wav, and the
segment-merging/refinement pipeline driven by argparse.Namespace.

These tests are model-free (no ONNX inference) and verify:
* read_wav handles valid mono 16-bit PCM correctly.
* read_wav raises on invalid audio specs.
* collect_wav_files discovers files from a directory or single file.
* The refine_speech_segments function preserves invariants given synthetic
  frame data.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from audio_fixtures import SAMPLE_RATE, make_silence, make_sine, make_vad_args, write_wav

import batch_vad as bv


# ===========================================================================
# read_wav
# ===========================================================================
class TestReadWav:
    def test_reads_valid_mono_16bit(self, tmp_path: Path):
        audio = make_sine(1.0)
        path = write_wav(tmp_path / "valid.wav", audio)
        sr, data = bv.read_wav(path)
        assert sr == SAMPLE_RATE
        assert data.dtype == np.int16
        assert len(data) == int(1.0 * SAMPLE_RATE)

    def test_raises_on_stereo(self, tmp_path: Path):
        path = tmp_path / "stereo.wav"
        n = SAMPLE_RATE
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(np.zeros(n * 2, dtype=np.int16).tobytes())
        with pytest.raises(ValueError, match="mono"):
            bv.read_wav(path)

    def test_raises_on_8bit(self, tmp_path: Path):
        path = tmp_path / "8bit.wav"
        n = SAMPLE_RATE
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)   # 8-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(np.zeros(n, dtype=np.uint8).tobytes())
        with pytest.raises(ValueError):
            bv.read_wav(path)

    def test_sample_rate_returned(self, tmp_path: Path):
        audio = make_silence(0.5)
        path = write_wav(tmp_path / "sr_test.wav", audio, sample_rate=SAMPLE_RATE)
        sr, _ = bv.read_wav(path)
        assert sr == SAMPLE_RATE


# ===========================================================================
# collect_wav_files
# ===========================================================================
class TestCollectWavFiles:
    def test_collect_from_directory(self, tmp_path: Path):
        for name in ("a.wav", "b.wav", "c.wav"):
            write_wav(tmp_path / name, make_silence(0.1))
        files = bv.collect_wav_files(tmp_path, [])
        assert len(files) == 3
        assert all(f.suffix == ".wav" for f in files)

    def test_collect_from_single_file(self, tmp_path: Path):
        path = write_wav(tmp_path / "solo.wav", make_silence(0.1))
        files = bv.collect_wav_files(path, [])
        assert files == [path.resolve()]

    def test_extra_paths_are_appended(self, tmp_path: Path):
        dir_wav = write_wav(tmp_path / "dir.wav", make_silence(0.1))
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        extra_wav = write_wav(extra_dir / "extra.wav", make_silence(0.1))
        files = bv.collect_wav_files(tmp_path, [extra_wav])
        resolved = [f.resolve() for f in files]
        assert extra_wav.resolve() in resolved

    def test_deduplicates_files(self, tmp_path: Path):
        path = write_wav(tmp_path / "dup.wav", make_silence(0.1))
        files = bv.collect_wav_files(path, [path])
        # Same file listed twice must appear only once
        assert len(files) == 1

    def test_raises_if_not_found(self, tmp_path: Path):
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError):
            bv.collect_wav_files(missing, [])

    def test_directory_contains_only_wav_not_others(self, tmp_path: Path):
        write_wav(tmp_path / "real.wav", make_silence(0.1))
        (tmp_path / "notes.txt").write_text("ignored")
        (tmp_path / "image.png").write_bytes(b"\x00" * 10)
        files = bv.collect_wav_files(tmp_path, [])
        assert all(f.suffix == ".wav" for f in files)


# ===========================================================================
# refine_speech_segments (model-free, uses synthetic frame data)
# ===========================================================================
class TestRefineSpeechSegments:
    """Test refine_speech_segments() with hand-crafted frame dicts."""

    def _make_frames(
        self,
        n: int,
        rms_values: np.ndarray | None = None,
        frame_dur: float = 0.032,
    ) -> list[dict]:
        if rms_values is None:
            rms_values = np.ones(n, dtype=np.float32) * 0.5
        return [
            {
                "start": i * frame_dur,
                "end": (i + 1) * frame_dur,
                "probability": 0.9,
                "rms": float(rms_values[i]),
            }
            for i in range(n)
        ]

    def test_empty_speech_segments_returns_empty(self):
        args = make_vad_args(refine_boundaries=True)
        frames = self._make_frames(10)
        result = bv.refine_speech_segments([], frames, duration=0.32, args=args)
        assert result == []

    def test_empty_frames_returns_original(self):
        args = make_vad_args(refine_boundaries=True)
        speech = [{"start": 0.0, "end": 1.0}]
        result = bv.refine_speech_segments(speech, [], duration=1.0, args=args)
        assert result == speech

    def test_zero_peak_rms_returns_empty(self):
        args = make_vad_args(refine_boundaries=True)
        # All frames have RMS = 0 → peak = 0 → returns []
        frames = self._make_frames(10, rms_values=np.zeros(10))
        speech = [{"start": 0.0, "end": 0.32}]
        result = bv.refine_speech_segments(speech, frames, duration=0.32, args=args)
        assert result == []

    def test_refinement_does_not_exceed_duration(self):
        args = make_vad_args(
            refine_boundaries=True,
            refine_energy_db_below_peak=60.0,
            refine_search_pad_ms=200.0,
        )
        n = 30
        rms = np.ones(n) * 0.5
        frames = self._make_frames(n, rms)
        duration = n * 0.032
        speech = [{"start": 0.0, "end": duration}]
        result = bv.refine_speech_segments(speech, frames, duration=duration, args=args)
        for seg in result:
            assert seg["start"] >= 0.0
            assert seg["end"] <= duration + 1e-6

    def test_refinement_high_rms_keeps_segment(self):
        """When all frames have high RMS, the refined segment should survive."""
        args = make_vad_args(
            refine_boundaries=True,
            refine_energy_db_below_peak=60.0,  # very loose gate
            refine_min_speech_ms=0.0,
            min_speech_secs=0.0,
        )
        n = 20
        rms = np.ones(n, dtype=np.float32) * 0.8
        frames = self._make_frames(n, rms)
        duration = n * 0.032
        speech = [{"start": 0.0, "end": duration}]
        result = bv.refine_speech_segments(speech, frames, duration=duration, args=args)
        assert len(result) >= 1


# ===========================================================================
# Segment ordering and no-overlap invariant after full pipeline helpers
# ===========================================================================
class TestSegmentInvariants:
    """
    Run just the post-processing helpers (events → segments → build_labeled)
    and verify global invariants.
    """

    def _make_events(self, pairs: list[tuple[float, float]]) -> list[dict]:
        events = []
        for start, end in pairs:
            events.append({"signal_type": "SPEAKING", "signal_at": str(start)})
            events.append({"signal_type": "QUIET",    "signal_at": str(end)})
        return events

    def test_full_pipeline_order_and_coverage(self):
        pairs = [(0.5, 1.5), (2.0, 3.0), (3.8, 5.0)]
        duration = 6.0
        args = make_vad_args()
        events = self._make_events(pairs)
        speech = bv.events_to_speech_segments(events, duration)
        speech = bv.merge_speech_segments(speech, args.merge_gap_secs, args.min_speech_secs)
        labeled = bv.build_labeled_segments(speech, duration)

        # Sorted
        for i in range(len(labeled) - 1):
            assert labeled[i]["end"] <= labeled[i + 1]["start"] + 1e-9

        # Coverage
        total = sum(s["end"] - s["start"] for s in labeled)
        assert abs(total - duration) < 1e-6

    def test_no_overlaps_after_merge(self):
        pairs = [(0.0, 1.0), (0.8, 2.0)]   # overlapping in events
        duration = 3.0
        args = make_vad_args()
        events = self._make_events(pairs)
        speech = bv.events_to_speech_segments(events, duration)
        speech = bv.merge_speech_segments(speech, args.merge_gap_secs, args.min_speech_secs)
        for i in range(len(speech) - 1):
            assert speech[i]["end"] <= speech[i + 1]["start"]
