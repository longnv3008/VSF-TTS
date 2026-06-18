from __future__ import annotations

from datetime import datetime, timezone

# Thứ tự 6 bước graph; index 1..6 dùng để tính phần trăm.
STEP_ORDER = [
    "validate_urls",
    "crawl_audio",
    "vocal_separation",
    "normalize_audio",
    "segment_and_label",
    "build_segment_metadata",
]

STEP_LABELS = {
    "queued": "Chờ xử lý",
    "starting": "Đang khởi động",
    "validate_urls": "Kiểm tra URL",
    "crawl_audio": "Tải audio",
    "vocal_separation": "Tách giọng (Demucs)",
    "normalize_audio": "Chuẩn hóa audio",
    "segment_and_label": "Cắt câu & gán nhãn",
    "build_segment_metadata": "Ghi metadata",
    "completed": "Hoàn tất",
}

_TERMINAL_URL_KEYS = ("completed", "skipped", "failed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def step_index(current_step: str) -> int | None:
    # 1..5 cho bước graph, None cho mốc khác (queued, saved:i/N, ...).
    if current_step in STEP_ORDER:
        return STEP_ORDER.index(current_step) + 1
    return None


def progress_label(current_step: str, status: str) -> str:
    if status == "completed":
        return "Hoàn tất"
    if status == "failed":
        return f"Lỗi ở: {STEP_LABELS.get(current_step, current_step)}"
    if status == "blocked" or current_step.startswith("blocked"):
        return "Bị chặn"
    if current_step.startswith("saved:"):
        return "Đã lưu " + current_step.split(":", 1)[1]
    if current_step.startswith("skipped:"):
        return "Bỏ qua " + current_step.split(":", 1)[1]
    return STEP_LABELS.get(current_step, current_step)


def compute_progress(current_step: str, status: str, url_summary: dict[str, int]) -> tuple[int, str]:
    label = progress_label(current_step, status)
    if status == "completed":
        return 100, label
    if status == "queued" or current_step in ("queued", "starting"):
        return 0, label

    total = max(1, int(url_summary.get("total", 1)))
    finished = sum(int(url_summary.get(key, 0)) for key in _TERMINAL_URL_KEYS)
    idx = step_index(current_step)
    fraction = (idx / len(STEP_ORDER)) if idx else 0.0
    percent = round((finished + fraction) / total * 100)
    return max(0, min(100, percent)), label


def append_step_event(history: list[dict] | None, step: str, now_iso: str) -> list[dict]:
    # Trả về list MỚI (để SQLAlchemy phát hiện thay đổi cột JSON).
    # validate_urls = đầu một URL mới -> reset timeline về URL hiện tại.
    if step == "validate_urls":
        items: list[dict] = []
    else:
        items = [dict(item) for item in (history or [])]
        if items and items[-1].get("ended_at") is None:
            items[-1]["ended_at"] = now_iso
    items.append({"step": step, "started_at": now_iso, "ended_at": None})
    return items
