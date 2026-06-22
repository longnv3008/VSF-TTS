import json

import pytest

from app.modules.audio_pipeline.application.segment_review_service import (
    SegmentReviewService,
)
from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
    SEGMENT_METADATA_FIELDS,
)


def _row(**kw):
    base = {k: "" for k in SEGMENT_METADATA_FIELDS}
    base.update(kw)
    return base


def _write_batch(metadata_dir, segments_dir, batch, rows):
    metadata_dir.mkdir(parents=True, exist_ok=True)
    path = metadata_dir / f"{batch}_segments.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    # csv để submit_review rewrite được cả hai
    import csv
    with (metadata_dir / f"{batch}_segments.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SEGMENT_METADATA_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


@pytest.fixture()
def service(tmp_path):
    meta = tmp_path / "metadata"
    segs = tmp_path / "segments"
    segs.mkdir(parents=True, exist_ok=True)
    seg_file = segs / "yt_v__sent000001.wav"
    seg_file.write_bytes(b"RIFFfake")
    rows = [
        _row(segment_id="yt_v__sent000001", text="chợt nhận ra", quality_label="needs_review",
             review_status="pending", quality_reasons="wer_gate>0.3",
             start="0.0", end="1.0", duration="1.0", segment_file=str(seg_file)),
        _row(segment_id="yt_v__sent000002", text="ổn", quality_label="speech_clean",
             review_status="", start="1.0", end="2.0", duration="1.0"),
    ]
    _write_batch(meta, segs, "b1", rows)
    return SegmentReviewService(metadata_dir=meta, segments_dir=segs)


def test_list_only_needs_review(service):
    items = service.list_segments("b1")
    assert len(items) == 1
    assert items[0]["segment_id"] == "yt_v__sent000001"
    assert items[0]["review_status"] == "pending"
    assert items[0]["manual_wer"] is None


def test_list_missing_batch_raises(service):
    with pytest.raises(FileNotFoundError):
        service.list_segments("nope")


def test_submit_review_computes_and_persists(service):
    # hyp="chợt nhận ra" (3 token). ref="chợt nhận biết" -> 1 sub / 3 = 0.333
    out = service.submit_review("b1", "yt_v__sent000001", "chợt nhận biết")
    assert out["review_status"] == "reviewed"
    assert out["manual_wer"] == pytest.approx(1 / 3, abs=1e-3)
    # persisted: đọc lại list thấy reference + wer.
    again = service.list_segments("b1")[0]
    assert again["reference"] == "chợt nhận biết"
    assert again["manual_wer"] == pytest.approx(1 / 3, abs=1e-3)


def test_submit_empty_reference_is_skipped(service):
    out = service.submit_review("b1", "yt_v__sent000001", "   ")
    assert out["review_status"] == "skipped"
    assert out["manual_wer"] is None
    assert out["spurious"] is True  # hyp có token, ref rỗng


def test_submit_unknown_segment_raises(service):
    with pytest.raises(FileNotFoundError):
        service.submit_review("b1", "no_such", "x")


def test_wer_summary_micro_average(service):
    service.submit_review("b1", "yt_v__sent000001", "chợt nhận biết")  # 1/3
    s = service.wer_summary("b1")
    assert s["total_needs_review"] == 1
    assert s["reviewed"] == 1
    assert s["pending"] == 0
    assert s["micro_wer"] == pytest.approx(1 / 3, abs=1e-3)


def test_wer_summary_empty_when_none_reviewed(service):
    s = service.wer_summary("b1")
    assert s["reviewed"] == 0
    assert s["micro_wer"] is None


def test_resolve_audio_ok(service):
    p = service.resolve_audio_path("b1", "yt_v__sent000001")
    assert p.exists()


def test_resolve_audio_traversal_blocked(service, tmp_path):
    # Trỏ segment_file ra ngoài segments_dir -> ValueError.
    outside = tmp_path / "evil.wav"
    outside.write_bytes(b"x")
    meta = service.metadata_dir
    path = meta / "b1_segments.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["segment_file"] = str(outside)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        service.resolve_audio_path("b1", "yt_v__sent000001")
