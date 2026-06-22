"""Tests cho 4 route review. Build mini FastAPI từ cùng router, override
get_review_service bằng mock."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audio_pipeline.api.routes import get_review_service, router


def _seg(**kw):
    base = dict(
        segment_id="yt_v__sent000001", text="chợt nhận ra", reference="",
        manual_wer=None, review_status="pending", start=0.0, end=1.0,
        duration=1.0, quality_reasons="wer_gate>0.3", spurious=False,
    )
    base.update(kw)
    return base


@pytest.fixture()
def client():
    svc = MagicMock()
    mini = FastAPI()
    mini.include_router(router)
    mini.dependency_overrides[get_review_service] = lambda: svc
    with TestClient(mini, raise_server_exceptions=True) as tc:
        yield tc, svc


def test_list_segments(client):
    tc, svc = client
    svc.list_segments.return_value = [_seg()]
    resp = tc.get("/batches/b1/segments?status=needs_review")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["segment_id"] == "yt_v__sent000001"
    assert data[0]["manual_wer"] is None
    svc.list_segments.assert_called_once_with("b1", status="needs_review")


def test_list_segments_missing_batch_404(client):
    tc, svc = client
    svc.list_segments.side_effect = FileNotFoundError("nope")
    resp = tc.get("/batches/zzz/segments")
    assert resp.status_code == 404


def test_submit_review(client):
    tc, svc = client
    svc.submit_review.return_value = _seg(reference="chợt nhận biết",
                                          manual_wer=0.3333, review_status="reviewed")
    resp = tc.post("/batches/b1/segments/yt_v__sent000001/review",
                   json={"reference": "chợt nhận biết"})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "reviewed"
    assert resp.json()["manual_wer"] == pytest.approx(0.3333)
    svc.submit_review.assert_called_once_with("b1", "yt_v__sent000001", "chợt nhận biết")


def test_submit_review_unknown_segment_404(client):
    tc, svc = client
    svc.submit_review.side_effect = FileNotFoundError("no seg")
    resp = tc.post("/batches/b1/segments/x/review", json={"reference": "y"})
    assert resp.status_code == 404


def test_wer_summary(client):
    tc, svc = client
    svc.wer_summary.return_value = dict(
        batch_name="b1", micro_wer=0.83, reviewed=2,
        total_needs_review=5, spurious=1, pending=2,
    )
    resp = tc.get("/batches/b1/wer-summary")
    assert resp.status_code == 200
    assert resp.json()["micro_wer"] == pytest.approx(0.83)
    assert resp.json()["total_needs_review"] == 5


def test_audio_traversal_400(client):
    tc, svc = client
    svc.resolve_audio_path.side_effect = ValueError("outside")
    resp = tc.get("/batches/b1/segments/x/audio")
    assert resp.status_code == 400


def test_audio_missing_404(client):
    tc, svc = client
    svc.resolve_audio_path.side_effect = FileNotFoundError("missing")
    resp = tc.get("/batches/b1/segments/x/audio")
    assert resp.status_code == 404


def test_audio_ok(client, tmp_path):
    tc, svc = client
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFFfake")
    svc.resolve_audio_path.return_value = wav
    resp = tc.get("/batches/b1/segments/yt_v__sent000001/audio")
    assert resp.status_code == 200
    assert resp.content == b"RIFFfake"
