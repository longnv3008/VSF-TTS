# Phase 01 - Ingest

## Scope

Nhan URL, validate input, tao job, bat dau qua trinh crawl audio.

## Current State

- Frontend gui `batch_name` va danh sach `urls`
- Backend tao job qua `POST /api/v1/jobs/ingest`
- Job duoc day vao background task de xu ly
- Workflow step dau tien la `validate_urls`, sau do `crawl_audio`

## Key Files

- `backend/app/modules/audio_pipeline/api/routes.py`
- `backend/app/modules/audio_pipeline/api/schemas.py`
- `backend/app/modules/audio_pipeline/application/job_service.py`
- `backend/app/modules/audio_pipeline/application/worker.py`
- `backend/app/modules/audio_pipeline/application/workflow.py`
- `frontend/src/features/jobs/components/CreateJobForm.tsx`

## Open Notes

- Hien tai chua thay queue system rieng ngoai `BackgroundTasks`
- Can giu format step name on dinh de khop job tracking va UI
