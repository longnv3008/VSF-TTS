"""Tests for stage_timing.py — no real DB or SSE needed."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.modules.audio_pipeline.application import stage_timing as st
from app.modules.audio_pipeline.application.stage_timing import (
    SegmentTimingSink,
    TimingHandle,
    close_timing,
    open_timing,
    record_completed,
    record_stage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_row():
    """Minimal PipelineStageTiming mock with an auto-increment id."""
    row = MagicMock()
    row.id = 42
    return row


@pytest.fixture()
def mock_db(fake_row):
    """Patch SessionLocal to return a mock session that yields fake_row on refresh."""
    db = MagicMock()
    db.get.return_value = fake_row

    def _refresh(obj):
        # simulate db.refresh setting obj.id when it's a new row
        obj.id = fake_row.id

    db.refresh.side_effect = _refresh

    with patch.object(st, "SessionLocal", return_value=db):
        yield db, fake_row


@pytest.fixture()
def mock_publish():
    with patch.object(st, "publish_timing_event") as mock:
        yield mock


# ---------------------------------------------------------------------------
# open_timing
# ---------------------------------------------------------------------------


def test_open_timing_returns_none_when_job_id_is_none():
    handle = open_timing(None, None, "crawl_audio")
    assert handle is None


def test_open_timing_creates_row_and_returns_handle(mock_db, mock_publish):
    db, fake_row = mock_db
    handle = open_timing(1, 2, "crawl_audio", sub_stage="sub", video_id="v1")
    assert isinstance(handle, TimingHandle)
    assert handle.timing_id == 42
    db.add.assert_called_once()
    db.commit.assert_called_once()
    mock_publish.assert_called_once()


def test_open_timing_returns_none_on_db_error(mock_publish):
    """DB failure → return None without propagating exception."""
    db = MagicMock()
    db.add.side_effect = RuntimeError("db down")
    with patch.object(st, "SessionLocal", return_value=db):
        handle = open_timing(1, 2, "crawl_audio")
    assert handle is None
    mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# close_timing
# ---------------------------------------------------------------------------


def test_close_timing_noop_on_none_handle(mock_db, mock_publish):
    close_timing(None)
    db, _ = mock_db
    db.commit.assert_not_called()
    mock_publish.assert_not_called()


def test_close_timing_updates_row_to_completed(mock_db, mock_publish):
    db, fake_row = mock_db
    handle = TimingHandle(timing_id=42, started_perf=0.0)
    close_timing(handle, status="completed")
    assert fake_row.status == "completed"
    assert fake_row.ended_at is not None
    assert fake_row.duration_sec >= 0
    db.commit.assert_called_once()
    mock_publish.assert_called_once()


def test_close_timing_sets_failed_status(mock_db, mock_publish):
    db, fake_row = mock_db
    handle = TimingHandle(timing_id=42, started_perf=0.0)
    close_timing(handle, status="failed")
    assert fake_row.status == "failed"


def test_close_timing_noop_when_row_not_found(mock_publish):
    db = MagicMock()
    db.get.return_value = None
    with patch.object(st, "SessionLocal", return_value=db):
        close_timing(TimingHandle(timing_id=99, started_perf=0.0))
    mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# record_completed
# ---------------------------------------------------------------------------


def test_record_completed_noop_on_none_job_id(mock_publish):
    record_completed(None, None, "segment_and_label", sub_stage="vad", duration_sec=1.5)
    mock_publish.assert_not_called()


def test_record_completed_writes_row(mock_db, mock_publish):
    db, fake_row = mock_db
    record_completed(1, 2, "segment_and_label", sub_stage="vad",
                     video_id="v1", duration_sec=2.5)
    db.add.assert_called_once()
    db.commit.assert_called_once()
    mock_publish.assert_called_once()


# ---------------------------------------------------------------------------
# record_stage context manager
# ---------------------------------------------------------------------------


def test_record_stage_opens_and_closes_on_success(mock_db, mock_publish):
    db, _ = mock_db
    with record_stage(1, 2, "crawl_audio"):
        pass
    # open + close = 2 commits
    assert db.commit.call_count == 2
    assert mock_publish.call_count == 2


def test_record_stage_sets_failed_on_exception(mock_db, mock_publish):
    db, fake_row = mock_db
    with pytest.raises(ValueError, match="boom"):
        with record_stage(1, 2, "crawl_audio"):
            raise ValueError("boom")
    # close_timing called with status=failed
    assert fake_row.status == "failed"


def test_record_stage_reraises_original_exception(mock_db, mock_publish):
    db, _ = mock_db

    class _MyError(Exception):
        pass

    with pytest.raises(_MyError):
        with record_stage(1, 2, "segment_and_label"):
            raise _MyError("original")


# ---------------------------------------------------------------------------
# SegmentTimingSink
# ---------------------------------------------------------------------------


def test_sink_add_accumulates_durations(mock_db, mock_publish):
    sink = SegmentTimingSink(job_id=1, batch_id=2, video_id="v1")
    sink.add("cut", 0.5)
    sink.add("cut", 0.3)
    sink.add("asr", 1.2)
    assert sink._acc["cut"] == pytest.approx(0.8)
    assert sink._acc["asr"] == pytest.approx(1.2)


def test_sink_flush_calls_record_completed_per_substage(mock_db, mock_publish):
    db, _ = mock_db
    sink = SegmentTimingSink(job_id=1, batch_id=2, video_id="v1")
    sink.add("cut", 0.5)
    sink.add("asr", 1.0)
    sink.flush()
    # record_completed calls db once per sub-stage
    assert db.commit.call_count == 2
    # acc cleared after flush
    assert sink._acc == {}


def test_sink_flush_noop_when_job_id_none():
    sink = SegmentTimingSink(job_id=None, batch_id=None)
    sink.add("cut", 0.5)
    sink.flush()  # must not raise


def test_sink_span_wraps_record_stage(mock_db, mock_publish):
    db, _ = mock_db
    sink = SegmentTimingSink(job_id=1, batch_id=2, video_id="v1")
    with sink.span("vad"):
        pass
    # open + close
    assert db.commit.call_count == 2


def test_sink_negative_duration_clamped_to_zero(mock_db, mock_publish):
    db, _ = mock_db
    sink = SegmentTimingSink(job_id=1, batch_id=2)
    sink.add("cut", -1.0)  # negative clamped to 0
    assert sink._acc["cut"] == pytest.approx(0.0)
