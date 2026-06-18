# Job Progress Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface live pipeline progress in the jobs table — a progress % column, a 5-step timeline with per-step timing, and per-URL status — by extending the existing `JobRead` payload (REST + SSE).

**Architecture:** Pure helper functions compute progress % and step-history transitions (unit-testable, no DB). A new JSON column `step_history` on `pipeline_jobs` records per-step timestamps, written where `current_step` is already updated. `JobRead` is extended with derived fields and the per-URL list; the frontend adds a progress column and an expandable row (AntD `Steps` + URL list) that auto-updates via the existing SSE stream.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, PostgreSQL JSON; React 18 + AntD v5 (Vite). Backend tests: pytest. Frontend: no test runner — verify via `tsc --noEmit` + the running app.

**Conventions:**
- Backend runs in Docker container `audio-backend` (host API port 8001, repo mounted at `/app/backend`).
- Run backend pytest: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest <args>"`
- Run alembic: `docker exec audio-backend sh -lc "cd /app/backend && alembic upgrade head"`
- Run frontend typecheck: `docker exec audio-frontend sh -lc "npx tsc --noEmit"`
- Commit on the current branch `feat/segment-level-pipeline`. Stage only the files each task touches (the working tree has unrelated WIP — never use `git add -A`).
- End every commit message with the trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## File Structure

**Create:**
- `backend/app/modules/audio_pipeline/application/progress.py` — pure helpers: step order/labels, `compute_progress`, `append_step_event`, `_now_iso`.
- `backend/tests/test_progress.py` — unit tests for the pure helpers.
- `backend/alembic/versions/20260615_000008_add_step_history_to_pipeline_jobs.py` — migration.
- `frontend/src/features/jobs/components/JobDetailPanel.tsx` — expandable-row content (timeline + URL list).

**Modify:**
- `backend/app/modules/audio_pipeline/domain/models.py` — add `step_history` column.
- `backend/app/modules/audio_pipeline/application/job_progress.py` — record step history in `update_job_step`.
- `backend/app/modules/audio_pipeline/api/schemas.py` — `UrlRead`, `StepHistoryItem`, extended `JobRead`.
- `backend/app/modules/audio_pipeline/application/job_service.py` — `selectinload(urls)` in `list_jobs`.
- `backend/tests/test_progress.py` — (also holds a `JobRead` serialization test, Task 5).
- `frontend/src/entities/job/model.ts` — extend `Job` type.
- `frontend/src/features/jobs/components/JobsTable.tsx` — progress column, status colors, expandable.

---

## Task 1: Pure progress helpers (compute_progress + labels)

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/progress.py`
- Test: `backend/tests/test_progress.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_progress.py`:

```python
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
    # 1 URL, đang ở bước 3/5 -> 60%
    percent, _ = compute_progress("normalize_audio", "running", _summary(total=1))
    assert percent == 60


def test_progress_failed_keeps_step_percent():
    # fail ở bước 4/5 của 1 URL -> 80%, không về 0
    percent, label = compute_progress("segment_and_label", "failed", _summary(total=1))
    assert percent == 80
    assert label == "Lỗi ở: Cắt câu & gán nhãn"


def test_progress_multi_url_counts_finished():
    # 5 URL, 2 đã xong, URL thứ 3 ở bước 2/5 -> (2 + 0.4)/5 = 48%
    percent, _ = compute_progress("crawl_audio", "running", _summary(total=5, completed=2))
    assert percent == 48


def test_progress_saved_marker_label():
    _, label = compute_progress("saved:1/1", "running", _summary(total=1, completed=1))
    assert label == "Đã lưu 1/1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/test_progress.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named '...progress'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/modules/audio_pipeline/application/progress.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

# Thứ tự 5 bước graph; index 1..5 dùng để tính phần trăm.
STEP_ORDER = [
    "validate_urls",
    "crawl_audio",
    "normalize_audio",
    "segment_and_label",
    "build_segment_metadata",
]

STEP_LABELS = {
    "queued": "Chờ xử lý",
    "starting": "Đang khởi động",
    "validate_urls": "Kiểm tra URL",
    "crawl_audio": "Tải audio",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/test_progress.py -v"`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/progress.py backend/tests/test_progress.py
git commit -m "feat(progress): pure compute_progress + step labels

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Pure step-history transition (append_step_event)

**Files:**
- Modify: `backend/app/modules/audio_pipeline/application/progress.py`
- Test: `backend/tests/test_progress.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_progress.py`:

```python
from app.modules.audio_pipeline.application.progress import append_step_event


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/test_progress.py -k append -v"`
Expected: FAIL — `ImportError: cannot import name 'append_step_event'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/modules/audio_pipeline/application/progress.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/test_progress.py -v"`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/progress.py backend/tests/test_progress.py
git commit -m "feat(progress): pure append_step_event transition

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Migration + model column for step_history

**Files:**
- Create: `backend/alembic/versions/20260615_000008_add_step_history_to_pipeline_jobs.py`
- Modify: `backend/app/modules/audio_pipeline/domain/models.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/20260615_000008_add_step_history_to_pipeline_jobs.py`:

```python
"""add step_history to pipeline jobs

Revision ID: 20260615_000008
Revises: 20260602_000007
Create Date: 2026-06-15 00:00:08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260615_000008"
down_revision = "20260602_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("step_history", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "step_history")
```

- [ ] **Step 2: Add the model column**

In `backend/app/modules/audio_pipeline/domain/models.py`, add the import and the column. Add to the imports line (it currently imports `DateTime, ForeignKey, Integer, String, Text, func`):

```python
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
```

Add the column inside `class PipelineJob`, immediately after the `error_message` column (line ~42):

```python
    step_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 3: Run the migration**

Run: `docker exec audio-backend sh -lc "cd /app/backend && alembic upgrade head"`
Expected: output ends with `Running upgrade 20260602_000007 -> 20260615_000008, add step_history to pipeline jobs`

Verify column exists:
Run: `docker exec audio-postgres psql -U postgres -d audio_pipeline -c "\d pipeline_jobs" | grep step_history`
Expected: a line showing `step_history | json`

- [ ] **Step 4: Smoke-check the app still imports**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -c 'from app.modules.audio_pipeline.domain.models import PipelineJob; print(PipelineJob.step_history)'"`
Expected: prints a column attribute, no error.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260615_000008_add_step_history_to_pipeline_jobs.py backend/app/modules/audio_pipeline/domain/models.py
git commit -m "feat(db): add step_history JSON column to pipeline_jobs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Record step history in update_job_step

**Files:**
- Modify: `backend/app/modules/audio_pipeline/application/job_progress.py`

- [ ] **Step 1: Update update_job_step to append a timeline entry**

Replace the body of `update_job_step` in `backend/app/modules/audio_pipeline/application/job_progress.py`. The current `try` block sets `job.current_step` then saves; add the step-history write before saving:

```python
from __future__ import annotations

from app.db.session import SessionLocal
from app.modules.audio_pipeline.application.exceptions import format_function_error
from app.modules.audio_pipeline.application.job_events import publish_job_event
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.modules.audio_pipeline.application.progress import _now_iso, append_step_event
from app.utils import get_logger

logger = get_logger(__name__)


def update_job_step(job_id: int | None, step_name: str) -> None:
    if job_id is None:
        return

    db = SessionLocal()
    job_service = PipelineJobService(db)
    try:
        job = job_service.get_job_optional(job_id)
        if job is None:
            logger.warning("update_job_step skipped | job_id=%s | step=%s | reason=job_not_found", job_id, step_name)
            return
        job.current_step = step_name
        try:
            # Ghi timeline không được làm hỏng pipeline nếu lỗi.
            job.step_history = append_step_event(job.step_history, step_name, _now_iso())
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s | job_id=%s | step=%s", format_function_error("update_job_step.history", exc), job_id, step_name)
        job_service.save_job(job)
        publish_job_event("job_step_changed", job)
    except Exception as exc:
        logger.exception("%s | job_id=%s | step=%s", format_function_error("update_job_step", exc), job_id, step_name)
    finally:
        db.close()
```

- [ ] **Step 2: Verify the app imports cleanly**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -c 'import app.modules.audio_pipeline.application.job_progress as m; print(m.update_job_step)'"`
Expected: prints the function, no import error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/job_progress.py
git commit -m "feat(progress): record per-step timeline in update_job_step

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Extend JobRead schema (urls, summary, progress, timeline)

**Files:**
- Modify: `backend/app/modules/audio_pipeline/api/schemas.py`
- Modify: `backend/app/modules/audio_pipeline/application/job_service.py`
- Test: `backend/tests/test_progress.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_progress.py`:

```python
from datetime import datetime, timezone
from types import SimpleNamespace

from app.modules.audio_pipeline.api.schemas import JobRead


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
    # 3 URL, 1 xong, URL hiện tại ở bước 3/5 -> (1 + 0.6)/3 = 53%
    assert job.progress_percent == 53
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
    job = JobRead.model_validate(_fake_job(step_history=None, urls=[]))
    assert job.step_history == []
    assert job.url_summary["total"] == 0
    assert job.progress_percent == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/test_progress.py -k jobread -v"`
Expected: FAIL — `JobRead` has no `url_summary` / validation error.

- [ ] **Step 3: Implement schema changes**

In `backend/app/modules/audio_pipeline/api/schemas.py`, update the import line and add the new models. Change the pydantic import to:

```python
from pydantic import BaseModel, Field, field_validator, model_validator
```

Add the import for progress helpers near the top (after the existing `exceptions` import):

```python
from app.modules.audio_pipeline.application.progress import compute_progress
```

Add these classes above `class JobRead`:

```python
class UrlRead(BaseModel):
    url: str
    video_id: str
    status: str
    logs_fail: str | None = None

    model_config = {"from_attributes": True}


class StepHistoryItem(BaseModel):
    step: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_sec: float | None = None

    @model_validator(mode="after")
    def _compute_duration(self) -> "StepHistoryItem":
        if self.started_at and self.ended_at:
            self.duration_sec = round((self.ended_at - self.started_at).total_seconds(), 2)
        return self
```

Replace `class JobRead` with the extended version (keeps all existing fields, adds the new ones):

```python
class JobRead(BaseModel):
    # Schema trả về cho FE khi đọc thông tin job.
    id: int
    batch_id: int
    batch_status: str
    job_type: str
    status: str
    current_step: str
    batch_name: str
    manifest_path: str | None = None
    metadata_path: str | None = None
    translation_path: str | None = None
    output_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    # Theo dõi tiến trình (dẫn xuất + dữ liệu sẵn có).
    step_history: list[StepHistoryItem] = Field(default_factory=list)
    urls: list[UrlRead] = Field(default_factory=list)
    url_summary: dict[str, int] = Field(default_factory=dict)
    progress_percent: int = 0
    progress_label: str = ""

    model_config = {"from_attributes": True}

    @field_validator("step_history", mode="before")
    @classmethod
    def _default_step_history(cls, value: object) -> object:
        return value or []

    @model_validator(mode="after")
    def _compute_progress_fields(self) -> "JobRead":
        counts = {"total": len(self.urls), "completed": 0, "failed": 0, "skipped": 0, "running": 0, "queued": 0}
        for item in self.urls:
            if item.status in counts:
                counts[item.status] += 1
        self.url_summary = counts
        self.progress_percent, self.progress_label = compute_progress(self.current_step, self.status, counts)
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/test_progress.py -v"`
Expected: PASS (all green)

- [ ] **Step 5: Eager-load urls in list_jobs**

In `backend/app/modules/audio_pipeline/application/job_service.py`, in `list_jobs`, change the `.options(...)` call so urls are eager-loaded (avoids lazy-load when serializing list/SSE). Current line:

```python
                .options(selectinload(PipelineJob.batch))
```

Replace with:

```python
                .options(selectinload(PipelineJob.batch), selectinload(PipelineJob.urls))
```

- [ ] **Step 6: Verify the live endpoint returns new fields**

Run: `docker exec audio-backend sh -lc "cd /app/backend && python -m pytest tests/ -q"` (full suite, no regressions)
Then hit the API:
Run: `curl -s http://localhost:8001/api/v1/audio-pipeline/jobs/16 | python -c "import sys,json; d=json.load(sys.stdin); print('percent',d['progress_percent'],'label',d['progress_label'],'urls',len(d['urls']),'steps',len(d['step_history']))"`
Expected: prints `percent 100 label Hoàn tất urls 1 steps ...` (job 16 is completed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/audio_pipeline/api/schemas.py backend/app/modules/audio_pipeline/application/job_service.py backend/tests/test_progress.py
git commit -m "feat(api): expose progress, timeline and per-URL status in JobRead

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Frontend Job type

**Files:**
- Modify: `frontend/src/entities/job/model.ts`

- [ ] **Step 1: Extend the type**

Replace `frontend/src/entities/job/model.ts` with:

```typescript
export type StepHistoryItem = {
  step: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_sec?: number | null;
};

export type JobUrl = {
  url: string;
  video_id: string;
  status: string;
  logs_fail?: string | null;
};

export type UrlSummary = {
  total?: number;
  completed?: number;
  failed?: number;
  skipped?: number;
  running?: number;
  queued?: number;
};

export type Job = {
  id: number;
  batch_id: number;
  batch_status: string;
  job_type: string;
  status: string;
  current_step: string;
  batch_name: string;
  manifest_path?: string | null;
  metadata_path?: string | null;
  translation_path?: string | null;
  output_path?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
  step_history?: StepHistoryItem[];
  urls?: JobUrl[];
  url_summary?: UrlSummary;
  progress_percent?: number;
  progress_label?: string;
};
```

- [ ] **Step 2: Typecheck**

Run: `docker exec audio-frontend sh -lc "npx tsc --noEmit"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/entities/job/model.ts
git commit -m "feat(fe): extend Job type with progress/timeline/urls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Frontend JobDetailPanel (timeline + URL list)

**Files:**
- Create: `frontend/src/features/jobs/components/JobDetailPanel.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/features/jobs/components/JobDetailPanel.tsx`:

```tsx
import { Empty, Steps, Table, Tag } from "antd";
import type { Job, JobUrl } from "../../../entities/job/model";

const STEP_ORDER = [
  { key: "validate_urls", label: "Kiểm tra URL" },
  { key: "crawl_audio", label: "Tải audio" },
  { key: "normalize_audio", label: "Chuẩn hóa audio" },
  { key: "segment_and_label", label: "Cắt câu & gán nhãn" },
  { key: "build_segment_metadata", label: "Ghi metadata" },
];

const urlStatusColor: Record<string, string> = {
  queued: "default",
  running: "processing",
  completed: "success",
  skipped: "warning",
  failed: "error",
};

function formatDuration(sec?: number | null): string {
  if (sec == null) return "";
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m${s.toString().padStart(2, "0")}`;
}

export default function JobDetailPanel({ job }: { job: Job }) {
  const history = job.step_history ?? [];
  const byStep = new Map(history.map((item) => [item.step, item]));
  const isTerminal = job.status === "completed" || job.status === "failed" || job.status === "blocked";

  const items = STEP_ORDER.map(({ key, label }) => {
    const entry = byStep.get(key);
    let status: "wait" | "process" | "finish" | "error" = "wait";
    if (entry?.ended_at) {
      status = "finish";
    } else if (entry) {
      // bước đang mở: nếu job đã kết thúc thì coi như done/lỗi
      if (job.status === "failed" && job.current_step === key) status = "error";
      else if (isTerminal) status = "finish";
      else status = "process";
    }
    const dur = formatDuration(entry?.duration_sec);
    return { title: label, status, description: dur || undefined };
  });

  const urls: JobUrl[] = job.urls ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Steps size="small" items={items} />

      {urls.length > 0 ? (
        <Table<JobUrl>
          size="small"
          rowKey={(row) => row.url}
          dataSource={urls}
          pagination={false}
          columns={[
            {
              title: "URL",
              dataIndex: "url",
              ellipsis: true,
              render: (value: string) => (
                <a href={value} target="_blank" rel="noreferrer">{value}</a>
              ),
            },
            {
              title: "Trạng thái",
              dataIndex: "status",
              width: 120,
              render: (value: string) => <Tag color={urlStatusColor[value] || "default"}>{value}</Tag>,
            },
            { title: "Lý do (nếu lỗi/skip)", dataIndex: "logs_fail", ellipsis: true },
          ]}
        />
      ) : (
        <Empty description="Chưa có URL" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `docker exec audio-frontend sh -lc "npx tsc --noEmit"`
Expected: no errors. (The component is not yet wired in; this just confirms it compiles.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/jobs/components/JobDetailPanel.tsx
git commit -m "feat(fe): JobDetailPanel with step timeline and per-URL list

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Frontend JobsTable — progress column + expandable

**Files:**
- Modify: `frontend/src/features/jobs/components/JobsTable.tsx`

- [ ] **Step 1: Rewrite JobsTable**

Replace `frontend/src/features/jobs/components/JobsTable.tsx` with:

```tsx
import { Button, Card, Progress, Table, Tag } from "antd";
import type { Job } from "../../../entities/job/model";
import JobDetailPanel from "./JobDetailPanel";

const statusColors: Record<string, string> = {
  queued: "default",
  running: "processing",
  completed: "success",
  failed: "error",
  skipped: "warning",
  blocked: "warning",
};

function progressStatus(job: Job): "active" | "success" | "exception" | "normal" {
  if (job.status === "completed") return "success";
  if (job.status === "failed" || job.status === "blocked") return "exception";
  if (job.status === "running") return "active";
  return "normal";
}

type JobsTableProps = {
  jobs: Job[];
  loading: boolean;
  retryingJobId?: number | null;
  onRefresh: () => void;
  onRetry: (job: Job) => void;
};

export default function JobsTable({ jobs, loading, retryingJobId, onRefresh, onRetry }: JobsTableProps) {
  return (
    <Card
      title="Danh sach jobs"
      extra={
        <Button onClick={onRefresh} loading={loading}>
          Refresh
        </Button>
      }
    >
      <Table<Job>
        rowKey="id"
        loading={loading}
        dataSource={jobs}
        pagination={{ pageSize: 5 }}
        scroll={{ x: 900 }}
        expandable={{
          expandedRowRender: (job) => <JobDetailPanel job={job} />,
          rowExpandable: () => true,
        }}
        columns={[
          { title: "ID", dataIndex: "id", width: 70 },
          { title: "Batch", dataIndex: "batch_name" },
          {
            title: "Status",
            dataIndex: "status",
            render: (value: string) => <Tag color={statusColors[value] || "default"}>{value}</Tag>,
          },
          {
            title: "Tiến độ",
            key: "progress",
            width: 200,
            render: (_value: unknown, job: Job) => (
              <div>
                <Progress percent={job.progress_percent ?? 0} size="small" status={progressStatus(job)} />
                <div style={{ fontSize: 12, color: "#888" }}>{job.progress_label || job.current_step}</div>
              </div>
            ),
          },
          { title: "Metadata", dataIndex: "metadata_path", ellipsis: true },
          { title: "Error", dataIndex: "error_message", ellipsis: true },
          {
            title: "Action",
            key: "action",
            width: 140,
            render: (_value: unknown, job: Job) => (
              <Button onClick={() => onRetry(job)} loading={retryingJobId === job.id} disabled={job.status === "running"}>
                Chay lai
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `docker exec audio-frontend sh -lc "npx tsc --noEmit"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/jobs/components/JobsTable.tsx
git commit -m "feat(fe): progress column + expandable timeline/URL detail in JobsTable

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: End-to-end verification on the running app

**Files:** none (manual verification).

- [ ] **Step 1: Confirm services are up**

Run: `docker ps --format "{{.Names}}: {{.Status}}"`
Expected: `audio-backend`, `audio-frontend`, `audio-postgres`, `vad-server` all Up.

- [ ] **Step 2: Open the dashboard**

Open http://localhost:5174 in a browser. The jobs table should show a **Tiến độ** column with a progress bar + label for every job (completed jobs at 100% / "Hoàn tất").

- [ ] **Step 3: Expand a completed job**

Click the expand arrow on job 16. Expected: a 5-step timeline all marked finished (with durations like `Tải audio 36.0s`), and a URL list with one row `completed`.

- [ ] **Step 4: Watch a live run**

Create a new job with a short YouTube URL (Create form). Watch the progress bar advance through steps in real time (SSE), and expand the row to see the active step show as "process" and earlier steps as finished. If it fails, the failing step shows red and the URL row shows the reason.

- [ ] **Step 5: Final commit (docs)**

Mark this plan complete in your tracking; no code commit needed beyond Tasks 1–8.

---

## Self-Review Notes

- **Spec coverage:** §3.1 step_history → Tasks 2,3,4. §3.2 progress → Task 1. §3.3 per-URL → Task 5. §3.4 schema/API → Tasks 3,5. §4 frontend → Tasks 6,7,8. §6 testing → Tasks 1,2,5 (pytest) + Task 9 (manual). All covered.
- **Types consistent:** `compute_progress(current_step, status, url_summary)` and `append_step_event(history, step, now_iso)` used identically across tasks; `JobRead` fields match the frontend `Job` type (`progress_percent`, `progress_label`, `step_history`, `urls`, `url_summary`).
- **No placeholders:** every code step contains full code; every command has expected output.
