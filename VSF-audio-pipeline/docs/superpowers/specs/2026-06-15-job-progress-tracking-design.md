# Thiết kế: Cải thiện theo dõi tiến trình job (Job Progress Tracking)

- Ngày: 2026-06-15
- Phạm vi: Mức **A** (nâng cấp bảng job) + **1 phần B** (timeline 5 bước có thời gian, tiến độ theo từng URL). **Không** làm live-log realtime, **không** làm dashboard tổng hợp (để sau).

## 1. Mục tiêu & bối cảnh

Pipeline chạy nền (FastAPI background task → LangGraph 5 bước). Hiện người vận hành chỉ thấy `status` + `current_step` (một chuỗi) trên bảng job, không biết:
- tiến độ tổng thể bao nhiêu %,
- mỗi bước đã chạy/đang chạy/đợi, mất bao lâu,
- trong một job nhiều URL thì URL nào xong/đang chạy/lỗi và vì sao.

Sự cố thực tế: job fail ở bước `segment_and_label` (VAD chưa bật) nhưng nhìn lướt tưởng đã xong vì có file wav/vtt. Mục tiêu là làm trạng thái "ẩn" này hiện rõ, realtime, ngay trên màn hình.

**Tiêu chí thành công:**
- Bảng job có cột tiến độ (%) + nhãn bước thân thiện, badge ✓/✗ rõ cho mọi trạng thái (queued/running/completed/failed/skipped/blocked).
- Click một job → mở rộng hàng thấy: timeline 5 bước (trạng thái + thời gian từng bước) và danh sách URL (n/N, trạng thái + lý do lỗi/skip).
- Tất cả tự cập nhật realtime qua SSE đã có, không cần refresh.

## 2. Kiến trúc tổng thể

Tận dụng nguyên kiến trúc hiện có:
- Backend FastAPI + SQLAlchemy + Alembic; sự kiện realtime qua SSE `GET /api/v1/audio-pipeline/jobs/events` (`JobEventBroker` phát `JobRead`).
- Frontend React + AntD; `DashboardPage` đã `fetchJobs()` + subscribe SSE và `upsertJob` realtime; `JobsTable` render.

Nguyên tắc: **mở rộng dữ liệu trả về trong `JobRead`** (dùng chung cho cả REST list lẫn SSE) để frontend tự cập nhật mà không cần thêm endpoint/stream mới.

## 3. Backend

### 3.1 Lưu thời gian từng bước — `step_history` (JSON)

Quyết định: thêm cột JSON `step_history` (nullable) vào `pipeline_jobs`. (Đã cân nhắc bảng riêng `pipeline_job_step_events` — quá mức cho nhu cầu; và phương án "không lưu, suy ra từ current_step" — mất thông tin thời gian người dùng yêu cầu.)

Cấu trúc:
```json
[
  {"step": "validate_urls", "started_at": "...", "ended_at": "..."},
  {"step": "crawl_audio",   "started_at": "...", "ended_at": "..."},
  {"step": "segment_and_label", "started_at": "...", "ended_at": null}
]
```

Quy tắc ghi (trong `application/job_progress.py::update_job_step`, nơi `current_step` đã được cập nhật):
- Khi đổi sang bước mới: đóng `ended_at` của entry đang mở (nếu có) rồi thêm entry mới với `started_at = now`.
- **Reset theo URL**: khi bước mới là `validate_urls` (đầu mỗi lần `graph.invoke` cho một URL) → bắt đầu `step_history` mới. Timeline vì vậy phản ánh URL đang xử lý; tiến độ nhiều URL do mục per-URL (3.3) đảm nhiệm.
- Ghi lỗi không được làm hỏng job: bọc try/except, log cảnh báo (giống pattern hiện tại).

`duration_sec` mỗi bước **không lưu** — tính khi serialize (`ended_at - started_at`, hoặc `now - started_at` nếu đang chạy).

### 3.2 Tiến độ tổng thể — `progress_percent` + `progress_label`

Tính (không lưu DB) khi serialize `JobRead`. Công thức kết hợp **tiến độ URL** + **bước trong URL đang chạy** để đúng cho cả job 1 URL lẫn nhiều URL:

- Thứ tự bước cố định: `validate_urls(1) → crawl_audio(2) → normalize_audio(3) → segment_and_label(4) → build_segment_metadata(5)` (tổng 5 bước).
- `total = url_summary.total` (tối thiểu 1); `finished = completed + skipped + failed` (URL đã ở trạng thái cuối).
- Nếu `status == completed` → **100%**.
- Nếu `status in {queued, starting}` → **0%**.
- Ngược lại (đang chạy hoặc dừng do `failed`/`blocked`): `percent = round((finished + step_fraction) / total * 100)`, clamp `[0,100]`, **không** nhảy về 0 khi failed.
  - `step_fraction = step_index / 5` với `step_index` lấy từ một trong 5 bước graph trong `current_step` (URL đang xử lý).
  - Nếu `current_step` là mốc giữa-URL (`saved:i/N`, `skipped:i/N`) thì URL đó đã tính vào `finished`, `step_fraction = 0`.
- `progress_label`: nhãn tiếng Việt thân thiện cho `current_step` (vd `crawl_audio`→"Tải audio", `segment_and_label`→"Cắt câu & gán nhãn", `saved:i/N`→"Đã lưu i/N"). Map đặt ở backend để dùng lại được.
- **Giới hạn**: % nhảy theo BƯỚC/URL, không có đếm trong-bước (vd "320/540 câu") — cần instrument riêng bước segment, để sau.

### 3.3 Tiến độ theo URL — tận dụng dữ liệu có sẵn

`pipeline_job_urls` đã có `status` (queued/running/completed/skipped/failed) + `logs_fail`. Chỉ cần expose:
- `url_summary`: đếm `{total, completed, failed, skipped, running, queued}`.
- `urls`: danh sách `UrlRead {url, video_id, status, logs_fail}` cho hàng mở rộng.

### 3.4 Thay đổi API/schema

- `domain/models.py`: thêm `step_history: Mapped[list | None]` (kiểu `JSON`).
- `api/schemas.py`:
  - `UrlRead` (mới): `url, video_id, status, logs_fail`.
  - `StepHistoryItem` (mới): `step, started_at, ended_at, duration_sec`.
  - `JobRead` (mở rộng): `+ step_history: list[StepHistoryItem]`, `+ progress_percent: int`, `+ progress_label: str`, `+ url_summary: dict[str,int]`, `+ urls: list[UrlRead]`. Tính các trường dẫn xuất bằng `model_validator`/helper.
- `application/job_service.py::list_jobs`: thêm `selectinload(PipelineJob.urls)` để list + SSE kèm URL, tránh lazy-load.
- Migration Alembic mới: `add_step_history_to_pipeline_jobs` (theo mẫu các version hiện có).
- **Không** đổi cơ chế SSE; payload lớn hơn chút (≤50 URL/job) chấp nhận được.

## 4. Frontend

- `entities/job/model.ts`: mở rộng type `Job` với các trường mới (`step_history`, `progress_percent`, `progress_label`, `url_summary`, `urls`).
- `features/jobs/components/JobsTable.tsx`:
  - Thêm cột **"Tiến độ"**: `Progress` (AntD) theo `progress_percent` + dòng nhãn `progress_label`; màu theo trạng thái (running=active, completed=success, failed=exception).
  - Mở rộng `statusColors` cho `skipped`/`blocked`.
  - Bật `expandable` → render component mới.
- `features/jobs/components/JobDetailPanel.tsx` (mới): nội dung hàng mở rộng
  - **Timeline 5 bước**: AntD `Steps` (hoặc `Timeline`) — trạng thái done/process/wait/error + thời gian mỗi bước (từ `step_history` đã serialize `duration_sec`).
  - **Danh sách URL**: bảng/list nhỏ — mỗi URL icon ✓/▶/✗ + `logs_fail` khi lỗi/skip.
- Util map nhãn bước (nếu cần phía FE), nhưng ưu tiên dùng `progress_label` từ backend.
- Realtime: không đổi `DashboardPage`; SSE upsert sẵn có làm cột tiến độ + panel tự cập nhật.

## 5. Xử lý lỗi & biên

- `step_history` null (job cũ trước migration) → FE suy ra trạng thái bước từ `current_step` (trước = done không thời gian, hiện = running, sau = wait).
- Bước lỗi → timeline tô đỏ đúng bước (`current_step` khi failed), panel hiện `error_message`; URL lỗi hiện `logs_fail`.
- Ghi `step_history` bọc try/except — không bao giờ làm fail pipeline.
- Job nhiều URL → timeline là của URL đang chạy; `url_summary`/`urls` cho bức tranh toàn job.

## 6. Kiểm thử

- **Backend (pytest, đã có hạ tầng trong `backend/tests`)**:
  - `progress_percent`/`progress_label` đúng cho từng `current_step` (gồm `saved:*`, `skipped:*`, `failed`, `completed`).
  - `update_job_step` đóng entry cũ + mở entry mới; reset đúng khi gặp `validate_urls`.
  - `JobRead` serialize kèm `urls` + `url_summary` + `duration_sec` tính đúng.
- **Frontend**: verify trực tiếp trên app đang chạy (http://localhost:5174) — tạo job, xem cột tiến độ tăng dần và mở hàng xem timeline + URL. Thêm test component nếu repo có sẵn vitest.
- Migration: chạy/đảo (upgrade/downgrade) sạch qua alembic.

## 7. Ngoài phạm vi (để sau)

- Live-log realtime riêng từng job.
- Dashboard tổng hợp (tỉ lệ thành công/thất bại, throughput, sức khoẻ cookie/proxy).
- Đếm tiến độ trong-bước (vd số câu segment) — cần instrument bước segment.
