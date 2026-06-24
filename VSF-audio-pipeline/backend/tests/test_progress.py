from __future__ import annotations

from app.modules.audio_pipeline.application.progress import compute_progress


def _summary(total=1, completed=0, failed=0, skipped=0, running=0, queued=0):
    return {
        "total": total, "completed": completed, "failed": failed,
        "skipped": skipped, "running": running, "queued": queued,
    }


def test_progress_queued_is_zero():
    percent, label = compute_progress("queued", "queued", _summary())
    assert percent == 0
    assert label == "Chờ xử lý"


def test_progress_completed_is_full():
    percent, label = compute_progress("completed", "completed", _summary(completed=1))
    assert percent == 100
    assert label == "Hoàn tất"


def test_progress_single_url_midway():
    # 1 URL, đang ở bước 4/6 -> 67%
    percent, _ = compute_progress("normalize_audio", "running", _summary(total=1))
    assert percent == 67


def test_progress_failed_keeps_step_percent():
    # fail ở bước 5/6 của 1 URL -> 83%, không về 0
    percent, label = compute_progress("segment_and_label", "failed", _summary(total=1))
    assert percent == 83
    assert label == "Lỗi ở: Cắt câu & gán nhãn"


def test_progress_multi_url_counts_finished():
    # 5 URL, 2 đã xong, URL thứ 3 ở bước 2/6 -> (2 + 0.333)/5 = 47%
    percent, _ = compute_progress("crawl_audio", "running", _summary(total=5, completed=2))
    assert percent == 47


def test_progress_saved_marker_label():
    _, label = compute_progress("saved:1/1", "running", _summary(total=1, completed=1))
    assert label == "Đã lưu 1/1"


from app.modules.audio_pipeline.application.progress import append_step_event  # noqa: E402


def test_append_first_step_opens_entry():
    history = append_step_event([], "validate_urls", "T0")
    assert history == [{"step": "validate_urls", "started_at": "T0", "ended_at": None}]


def test_append_next_step_closes_previous():
    history = append_step_event([], "validate_urls", "T0")
    history = append_step_event(history, "crawl_audio", "T1")
    assert history[0]["ended_at"] == "T1"
    assert history[1] == {"step": "crawl_audio", "started_at": "T1", "ended_at": None}


def test_validate_urls_resets_history_for_next_url():
    history = append_step_event([], "validate_urls", "T0")
    history = append_step_event(history, "crawl_audio", "T1")
    # URL kế tiếp bắt đầu lại từ validate_urls -> timeline chỉ giữ URL hiện tại
    history = append_step_event(history, "validate_urls", "T2")
    assert history == [{"step": "validate_urls", "started_at": "T2", "ended_at": None}]


def test_append_handles_none_history():
    history = append_step_event(None, "crawl_audio", "T0")
    assert history == [{"step": "crawl_audio", "started_at": "T0", "ended_at": None}]


from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.modules.audio_pipeline.api.schemas import JobRead  # noqa: E402


def _fake_url(status, video_id="v1", url="https://y/v", logs_fail=None):
    return SimpleNamespace(url=url, video_id=video_id, status=status, logs_fail=logs_fail)


def _fake_job(**over):
    base = dict(
        id=1, batch_id=1, batch_status="running", job_type="youtube_ingest",
        status="running", current_step="normalize_audio", batch_name="batch_001",
        manifest_path=None, metadata_path=None, translation_path=None, output_path=None,
        error_message=None, created_at=datetime.now(timezone.utc), updated_at=None,
        step_history=[
            {"step": "validate_urls", "started_at": "2026-06-15T00:00:00+00:00", "ended_at": "2026-06-15T00:00:01+00:00"},
            {"step": "crawl_audio", "started_at": "2026-06-15T00:00:01+00:00", "ended_at": "2026-06-15T00:00:11+00:00"},
            {"step": "normalize_audio", "started_at": "2026-06-15T00:00:11+00:00", "ended_at": None},
        ],
        urls=[_fake_url("completed"), _fake_url("running"), _fake_url("queued")],
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_jobread_builds_url_summary_and_progress():
    job = JobRead.model_validate(_fake_job())
    assert job.url_summary["total"] == 3
    assert job.url_summary["completed"] == 1
    # 3 URL, 1 xong, URL hiện tại ở bước 4/6 -> (1 + 0.667)/3 = 56%
    assert job.progress_percent == 56
    assert job.progress_label == "Chuẩn hóa audio"
    assert len(job.urls) == 3
    assert job.urls[0].status == "completed"


def test_jobread_step_history_duration():
    job = JobRead.model_validate(_fake_job())
    crawl = next(item for item in job.step_history if item.step == "crawl_audio")
    assert crawl.duration_sec == 10.0
    open_item = next(item for item in job.step_history if item.step == "normalize_audio")
    assert open_item.duration_sec is None


def test_jobread_handles_null_step_history():
    # Job vừa tạo: step_history null, chưa có URL -> không crash, tiến độ 0%.
    job = JobRead.model_validate(
        _fake_job(step_history=None, urls=[], status="queued", current_step="queued")
    )
    assert job.step_history == []
    assert job.url_summary["total"] == 0
    assert job.progress_percent == 0
