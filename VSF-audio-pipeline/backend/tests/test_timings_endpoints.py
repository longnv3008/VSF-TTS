"""Tests for the 4 timings REST endpoints.

Strategy: build a minimal FastAPI app from the same router (no lifespan DB init),
override get_job_service with a mock, and hit routes with TestClient.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audio_pipeline.api.routes import get_job_service, router
from app.modules.audio_pipeline.api.schemas import (
    BatchTimingSummary,
    StageAggregate,
    StageTimingItem,
    VideoStageBreakdown,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _timing_item(**kwargs) -> dict:
    base = dict(
        id=1, job_id=1, batch_id=2, video_id="v1", url="https://y/v",
        stage="crawl_audio", sub_stage=None,
        started_at=_NOW, ended_at=_NOW, duration_sec=5.0, status="completed",
    )
    base.update(kwargs)
    return base


@pytest.fixture()
def mock_svc():
    svc = MagicMock()
    return svc


@pytest.fixture()
def client(mock_svc):
    """TestClient with lifespan disabled + mocked job_service."""
    mini = FastAPI()
    mini.include_router(router)

    mini.dependency_overrides[get_job_service] = lambda: mock_svc
    with TestClient(mini, raise_server_exceptions=True) as tc:
        yield tc, mock_svc


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/timings
# ---------------------------------------------------------------------------


def test_list_job_timings_returns_items(client):
    tc, svc = client
    item = StageTimingItem(**_timing_item())
    svc.list_job_timings.return_value = [item]

    resp = tc.get("/jobs/1/timings")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["stage"] == "crawl_audio"
    assert data[0]["status"] == "completed"
    assert data[0]["duration_sec"] == pytest.approx(5.0)
    svc.list_job_timings.assert_called_once_with(1)


def test_list_job_timings_returns_empty(client):
    tc, svc = client
    svc.list_job_timings.return_value = []
    resp = tc.get("/jobs/99/timings")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /batches/{batch_id}/timings/aggregate
# ---------------------------------------------------------------------------


def test_aggregate_batch_timings(client):
    tc, svc = client
    agg = StageAggregate(stage="crawl_audio", sub_stage=None,
                         total_duration_sec=12.5, count=3, avg_duration_sec=4.17)
    svc.aggregate_batch_timings.return_value = [agg]

    resp = tc.get("/batches/2/timings/aggregate")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["stage"] == "crawl_audio"
    assert data[0]["count"] == 3
    assert data[0]["total_duration_sec"] == pytest.approx(12.5)
    svc.aggregate_batch_timings.assert_called_once_with(2)


def test_aggregate_batch_timings_empty(client):
    tc, svc = client
    svc.aggregate_batch_timings.return_value = []
    resp = tc.get("/batches/2/timings/aggregate")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /batches/{batch_id}/timings/by-video
# ---------------------------------------------------------------------------


def test_batch_timings_by_video(client):
    tc, svc = client
    item = StageTimingItem(**_timing_item())
    breakdown = VideoStageBreakdown(video_id="v1", url="https://y/v", stages=[item])
    svc.batch_timings_by_video.return_value = [breakdown]

    resp = tc.get("/batches/2/timings/by-video")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["video_id"] == "v1"
    assert len(data[0]["stages"]) == 1
    assert data[0]["stages"][0]["stage"] == "crawl_audio"
    svc.batch_timings_by_video.assert_called_once_with(2)


def test_batch_timings_by_video_empty(client):
    tc, svc = client
    svc.batch_timings_by_video.return_value = []
    resp = tc.get("/batches/2/timings/by-video")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /timings/history
# ---------------------------------------------------------------------------


def test_list_timing_history_default_limit(client):
    tc, svc = client
    summary = BatchTimingSummary(
        batch_id=2, batch_name="b1", created_at=_NOW,
        per_stage=[], total_duration_sec=30.0, params={"threshold": 0.7},
    )
    svc.list_timing_history.return_value = [summary]

    resp = tc.get("/timings/history")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["batch_name"] == "b1"
    assert data[0]["total_duration_sec"] == pytest.approx(30.0)
    assert data[0]["params"]["threshold"] == pytest.approx(0.7)
    svc.list_timing_history.assert_called_once_with(20)  # default limit=20


def test_list_timing_history_custom_limit(client):
    tc, svc = client
    svc.list_timing_history.return_value = []
    resp = tc.get("/timings/history?limit=5")
    assert resp.status_code == 200
    svc.list_timing_history.assert_called_once_with(5)
