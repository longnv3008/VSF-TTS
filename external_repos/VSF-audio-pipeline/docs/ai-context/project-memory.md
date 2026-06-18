# Project Memory

## Project Snapshot

- Project: `VinSmart Future Audio Pipeline`
- Kieu repo: monorepo fullstack
- Muc tieu: ingest YouTube URL, xu ly audio, tao translation full video, sinh metadata, theo doi job tren dashboard
- Ngay cap nhat memory: `2026-05-29`

## Current Stack

- Frontend: React 18 + Vite + TypeScript + Ant Design
- Backend: FastAPI + SQLAlchemy + Alembic
- Workflow engine: LangGraph
- Database: PostgreSQL
- Runtime tools: `yt-dlp`, `ffmpeg`
- YouTube extraction environment: `yt-dlp[default,curl-cffi]` + `Deno`
- Observability: LangSmith
- Dev infra: Docker Compose, Makefile, `uv`, Yarn

## Current Product Shape

- Frontend hien co 1 dashboard de tao job, xem danh sach job, retry job, nhan update realtime qua SSE.
- Backend expose API cho health check va pipeline jobs.
- Audio pipeline dang chay theo workflow tuan tu.
- Subtitle crawl hien chi lay tieng Viet de phuc vu data preparation.
- Batch processing da co bang `pipeline_batches` rieng; job con group theo `batch_id`, khong group theo `batch_name` nua.

## Current Workflow

Luong xu ly chinh hien tai:

1. `validate_urls`
2. `crawl_audio`
3. `normalize_audio`
4. `build_translations`
5. `build_metadata`

Output runtime duoc ghi vao:

- `data/raw/youtube`
- `data/processed/audio`
- `data/processed/translations`
- `data/metadata`
- `logs/`

## Core Backend Areas

- `backend/app/main.py`: bootstrap FastAPI, middleware, exception handlers
- `backend/app/core/config.py`: tap trung toan bo env config
- `backend/app/modules/router.py`: mount router theo module
- `backend/app/modules/audio_pipeline/api/routes.py`: jobs API + SSE + retry
- `backend/app/modules/audio_pipeline/application/workflow.py`: LangGraph workflow
- `backend/app/modules/audio_pipeline/application/worker.py`: chay background pipeline job
- `backend/app/modules/audio_pipeline/application/job_service.py`: CRUD/job state
- `backend/app/modules/audio_pipeline/application/pipeline_service.py`: xu ly audio, translation, metadata
- `backend/alembic/versions/`: lich su schema

## Core Frontend Areas

- `frontend/src/pages/dashboard/DashboardPage.tsx`: man hinh chinh
- `frontend/src/features/jobs/api/jobs.ts`: goi API jobs + event source
- `frontend/src/features/jobs/components/`: form, table, summary cards
- `frontend/src/entities/job/model.ts`: types cua job
- `frontend/src/shared/api/client.ts`: API client

## Existing API Surface

- `GET /api/v1/health`
- `GET /api/v1/jobs`
- `GET /api/v1/batches`
- `GET /api/v1/batches/{batch_id}`
- `GET /api/v1/jobs/events`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/ingest`
- `POST /api/v1/jobs/{job_id}/retry`
- `POST /api/v1/jobs/{job_id}/resume-batch`

## Important Environment Variables

- `DATABASE_URL`
- `POSTGRES_*`
- `STORAGE_ROOT`
- `RAW_YOUTUBE_DIR`
- `PROCESSED_AUDIO_DIR`
- `PROCESSED_TRANSLATION_DIR`
- `METADATA_DIR`
- `LOG_DIR`
- `LANGSMITH_*`
- `TELEGRAM_*`

## Assumptions AI Nen Giu

- Repo dang theo huong module-based backend va feature-based frontend.
- Job processing dang duoc trigger qua FastAPI `BackgroundTasks`, chua thay queue system rieng.
- Dashboard la giao dien van hanh chinh, khong phai public product UI.
- `data/` va `logs/` la runtime area, khong nen coi la source of truth cho architecture.
- Crawl YouTube da co guard rail o service layer: global lock, random delay, retry/backoff, cache theo `video_id`.

## Khi Co Thay Doi, Can Update File Nay Neu

- Them/bot step trong workflow
- Them module backend hoac page frontend moi
- Doi API surface
- Doi stack hoac runtime path
