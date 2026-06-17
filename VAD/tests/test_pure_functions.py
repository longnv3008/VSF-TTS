"""
test_pure_functions.py – Unit tests for the pure (side-effect-free) helper
functions in batch_vad.py.

These tests do NOT require the ONNX model file or any audio I/O and are
therefore extremely fast.  They validate the algorithmic correctness of:

* events_to_speech_segments
* merge_speech_segments
* _fill_short_mask_gaps
* _remove_short_mask_runs
* _pad_mask_runs
* mask_to_segments
* overlap_secs
* build_labeled_segments
"""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Import functions under test (works because conftest.py adds VAD_ROOT to path)
# ---------------------------------------------------------------------------
import batch_vad as bv


# ===========================================================================
# events_to_speech_segments
# ===========================================================================
class TestEventsToSpeechSegments:
    def test_empty_events_returns_empty(self):
        assert bv.events_to_speech_segments([], duration=5.0) == []

    def test_single_speaking_quiet_pair(self):
        events = [
            {"signal_type": "SPEAKING", "signal_at": "1.0"},
            {"signal_type": "QUIET",    "signal_at": "3.0"},
        ]
        segments = bv.events_to_speech_segments(events, duration=5.0)
        assert len(segments) == 1
        assert segments[0] == {"start": 1.0, "end": 3.0}

    def test_unterminated_speaking_clips_to_duration(self):
        events = [{"signal_type": "SPEAKING", "signal_at": "2.0"}]
        segments = bv.events_to_speech_segments(events, duration=4.0)
        assert len(segments) == 1
        assert segments[0]["start"] == 2.0
        assert segments[0]["end"] == 4.0

    def test_multiple_pairs(self):
        events = [
            {"signal_type": "SPEAKING", "signal_at": "0.5"},
            {"signal_type": "QUIET",    "signal_at": "1.5"},
            {"signal_type": "SPEAKING", "signal_at": "3.0"},
            {"signal_type": "QUIET",    "signal_at": "4.5"},
        ]
        segments = bv.events_to_speech_segments(events, duration=6.0)
        assert len(segments) == 2
        assert segments[0] == {"start": 0.5, "end": 1.5}
        assert segments[1] == {"start": 3.0, "end": 4.5}

    def test_quiet_without_prior_speaking_is_ignored(self):
        events = [
            {"signal_type": "QUIET",    "signal_at": "0.5"},
            {"signal_type": "SPEAKING", "signal_at": "1.0"},
            {"signal_type": "QUIET",    "signal_at": "2.0"},
        ]
        segments = bv.events_to_speech_segments(events, duration=5.0)
        assert len(segments) == 1
        assert segments[0]["start"] == 1.0

    def test_quiet_at_clips_to_duration(self):
        events = [
            {"signal_type": "SPEAKING", "signal_at": "3.0"},
            {"signal_type": "QUIET",    "signal_at": "10.0"},   # beyond duration
        ]
        segments = bv.events_to_speech_segments(events, duration=5.0)
        assert segments[0]["end"] == 5.0

    def test_duplicate_speaking_events_take_earliest(self):
        events = [
            {"signal_type": "SPEAKING", "signal_at": "2.0"},
            {"signal_type": "SPEAKING", "signal_at": "1.0"},   # earlier
            {"signal_type": "QUIET",    "signal_at": "3.0"},
        ]
        segments = bv.events_to_speech_segments(events, duration=5.0)
        assert segments[0]["start"] == 1.0


# ===========================================================================
# merge_speech_segments
# ===========================================================================
class TestMergeSpeechSegments:
    def test_empty_returns_empty(self):
        assert bv.merge_speech_segments([], 0.5, 0.08) == []

    def test_segments_below_min_speech_secs_are_dropped(self):
        segments = [{"start": 0.0, "end": 0.05}]  # 50 ms < 80 ms
        assert bv.merge_speech_segments(segments, merge_gap_secs=0.5, min_speech_secs=0.08) == []

    def test_close_segments_are_merged(self):
        segments = [
            {"start": 0.0, "end": 1.0},
            {"start": 1.3, "end": 2.0},   # gap = 0.3 s < 0.5 s
        ]
        result = bv.merge_speech_segments(segments, merge_gap_secs=0.5, min_speech_secs=0.0)
        assert len(result) == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0

    def test_distant_segments_kept_separate(self):
        segments = [
            {"start": 0.0, "end": 1.0},
            {"start": 2.0, "end": 3.0},   # gap = 1.0 s > 0.5 s
        ]
        result = bv.merge_speech_segments(segments, merge_gap_secs=0.5, min_speech_secs=0.0)
        assert len(result) == 2

    def test_three_segments_merge_into_one(self):
        segments = [
            {"start": 0.0, "end": 1.0},
            {"start": 1.2, "end": 2.0},
            {"start": 2.3, "end": 3.0},
        ]
        result = bv.merge_speech_segments(segments, merge_gap_secs=0.5, min_speech_secs=0.0)
        assert len(result) == 1
        assert result[0]["end"] == 3.0

    def test_min_speech_secs_applied_before_merge(self):
        """Short segment that would pass after merging must be filtered first."""
        segments = [
            {"start": 0.0, "end": 0.04},   # only 40 ms – below min
            {"start": 0.1, "end": 1.0},
        ]
        result = bv.merge_speech_segments(segments, merge_gap_secs=0.5, min_speech_secs=0.08)
        # The 40 ms segment is dropped; gap between nothing and 0.1 s segment is irrelevant.
        assert len(result) == 1
        assert result[0]["start"] == 0.1


# ===========================================================================
# _fill_short_mask_gaps
# ===========================================================================
class TestFillShortMaskGaps:
    def test_no_speech_returns_unchanged(self):
        mask = np.zeros(10, dtype=bool)
        result = bv._fill_short_mask_gaps(mask, max_gap_frames=3)
        assert not result.any()

    def test_gap_shorter_than_max_is_filled(self):
        # Speech at 0-2, gap at 3-4, speech at 5-7
        mask = np.array([True, True, True, False, False, True, True, True], dtype=bool)
        result = bv._fill_short_mask_gaps(mask, max_gap_frames=2)
        assert result.all()

    def test_gap_longer_than_max_is_not_filled(self):
        mask = np.array([True, True, False, False, False, True, True], dtype=bool)
        result = bv._fill_short_mask_gaps(mask, max_gap_frames=2)
        assert not result[2:5].any()   # gap still present

    def test_zero_max_gap_returns_unchanged(self):
        mask = np.array([True, False, True], dtype=bool)
        result = bv._fill_short_mask_gaps(mask, max_gap_frames=0)
        np.testing.assert_array_equal(result, mask)


# ===========================================================================
# _remove_short_mask_runs
# ===========================================================================
class TestRemoveShortMaskRuns:
    def test_all_false_unchanged(self):
        mask = np.zeros(10, dtype=bool)
        result = bv._remove_short_mask_runs(mask, min_run_frames=3)
        assert not result.any()

    def test_short_run_removed(self):
        mask = np.array([True, True, False, False, False, True, True, True, True, True], dtype=bool)
        result = bv._remove_short_mask_runs(mask, min_run_frames=3)
        assert not result[:2].any()       # 2-frame run removed
        assert result[5:].all()           # 5-frame run kept

    def test_exact_min_run_kept(self):
        mask = np.array([False, True, True, True, False], dtype=bool)
        result = bv._remove_short_mask_runs(mask, min_run_frames=3)
        assert result[1:4].all()

    def test_min_run_1_changes_nothing(self):
        mask = np.array([True, False, True, True], dtype=bool)
        result = bv._remove_short_mask_runs(mask, min_run_frames=1)
        np.testing.assert_array_equal(result, mask)


# ===========================================================================
# _pad_mask_runs
# ===========================================================================
class TestPadMaskRuns:
    def test_no_speech_unchanged(self):
        mask = np.zeros(10, dtype=bool)
        result = bv._pad_mask_runs(mask, pad_frames=3)
        assert not result.any()

    def test_pad_extends_boundaries(self):
        mask = np.zeros(10, dtype=bool)
        mask[4:6] = True   # speech at frames 4 and 5
        result = bv._pad_mask_runs(mask, pad_frames=2)
        # Should now be True from 2 to 7 (at minimum)
        assert result[2:8].all()

    def test_pad_zero_unchanged(self):
        mask = np.array([False, True, True, False], dtype=bool)
        result = bv._pad_mask_runs(mask, pad_frames=0)
        np.testing.assert_array_equal(result, mask)

    def test_pad_clips_to_array_bounds(self):
        mask = np.zeros(5, dtype=bool)
        mask[4] = True   # last frame only
        result = bv._pad_mask_runs(mask, pad_frames=10)
        assert len(result) == 5
        assert result.all()   # padded to fill the whole array


# ===========================================================================
# mask_to_segments
# ===========================================================================
class TestMaskToSegments:
    def _make_frames(self, n: int, frame_dur: float = 0.032) -> list[dict]:
        return [
            {"start": i * frame_dur, "end": (i + 1) * frame_dur}
            for i in range(n)
        ]

    def test_all_false_returns_empty(self):
        frames = self._make_frames(5)
        mask = np.zeros(5, dtype=bool)
        assert bv.mask_to_segments(frames, mask) == []

    def test_all_true_returns_single_segment(self):
        frames = self._make_frames(4)
        mask = np.ones(4, dtype=bool)
        segments = bv.mask_to_segments(frames, mask)
        assert len(segments) == 1
        assert segments[0]["start"] == frames[0]["start"]
        assert segments[0]["end"] == frames[-1]["end"]

    def test_two_runs_returns_two_segments(self):
        frames = self._make_frames(8)
        mask = np.array([True, True, False, False, True, True, True, False], dtype=bool)
        segments = bv.mask_to_segments(frames, mask)
        assert len(segments) == 2
        assert segments[0]["start"] == frames[0]["start"]
        assert segments[1]["start"] == frames[4]["start"]


# ===========================================================================
# overlap_secs
# ===========================================================================
class TestOverlapSecs:
    def test_full_overlap(self):
        assert bv.overlap_secs({"start": 1.0, "end": 3.0}, {"start": 1.0, "end": 3.0}) == pytest.approx(2.0)

    def test_no_overlap(self):
        assert bv.overlap_secs({"start": 1.0, "end": 2.0}, {"start": 3.0, "end": 4.0}) == 0.0

    def test_partial_overlap(self):
        assert bv.overlap_secs({"start": 0.0, "end": 2.0}, {"start": 1.0, "end": 3.0}) == pytest.approx(1.0)

    def test_adjacent_no_overlap(self):
        assert bv.overlap_secs({"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}) == 0.0


# ===========================================================================
# build_labeled_segments
# ===========================================================================
class TestBuildLabeledSegments:
    def test_empty_speech_gives_full_quiet(self):
        rows = bv.build_labeled_segments([], duration=3.0)
        assert len(rows) == 1
        assert rows[0]["label"] == "quiet"
        assert rows[0]["start"] == 0.0
        assert rows[0]["end"] == 3.0

    def test_speech_at_start(self):
        speech = [{"start": 0.0, "end": 1.5}]
        rows = bv.build_labeled_segments(speech, duration=3.0)
        labels = [r["label"] for r in rows]
        assert labels == ["speaking", "quiet"]
        assert rows[0]["end"] == 1.5
        assert rows[1]["start"] == 1.5
        assert rows[1]["end"] == 3.0

    def test_speech_in_middle(self):
        speech = [{"start": 1.0, "end": 2.0}]
        rows = bv.build_labeled_segments(speech, duration=3.0)
        assert rows[0]["label"] == "quiet"
        assert rows[1]["label"] == "speaking"
        assert rows[2]["label"] == "quiet"

    def test_speech_covers_full_duration(self):
        speech = [{"start": 0.0, "end": 3.0}]
        rows = bv.build_labeled_segments(speech, duration=3.0)
        assert len(rows) == 1
        assert rows[0]["label"] == "speaking"

    def test_multiple_speech_segments(self):
        speech = [{"start": 0.5, "end": 1.0}, {"start": 2.0, "end": 2.5}]
        rows = bv.build_labeled_segments(speech, duration=3.0)
        labels = [r["label"] for r in rows]
        # quiet, speech, quiet, speech, quiet
        assert labels == ["quiet", "speaking", "quiet", "speaking", "quiet"]

    def test_total_duration_preserved(self):
        speech = [{"start": 0.5, "end": 1.5}, {"start": 2.0, "end": 2.7}]
        duration = 3.0
        rows = bv.build_labeled_segments(speech, duration=duration)
        total = sum(r["end"] - r["start"] for r in rows)
        assert total == pytest.approx(duration, abs=1e-9)

    def test_segments_are_non_overlapping_and_sorted(self):
        speech = [{"start": 0.3, "end": 1.2}, {"start": 1.8, "end": 2.5}]
        rows = bv.build_labeled_segments(speech, duration=3.0)
        for i in range(len(rows) - 1):
            assert rows[i]["end"] == pytest.approx(rows[i + 1]["start"])
