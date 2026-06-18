# Repo Map

## Top Level

```text
backend/      FastAPI app, modules, migrations
frontend/     React dashboard
data/         Runtime input/output
logs/         Runtime logs
docs/         Human + AI documentation
```

## Backend Map

```text
backend/app/
├── core/            App config, logging
├── db/              DB base, engine, session
├── modules/
│   ├── health/      Health endpoints
│   └── audio_pipeline/
│       ├── api/         HTTP schemas and routes
│       ├── application/ Services, worker, workflow, events
│       └── domain/      Domain models
├── observability/   Tracing bootstrap
└── utils/           Filesystem and logger helpers
```

## Frontend Map

```text
frontend/src/
├── app/             App shell
├── entities/        Shared domain types
├── features/        Feature slices
├── pages/           Route/page level UI
└── shared/          API client and shared helpers
```

## Runtime Data Map

```text
data/raw/youtube/            Downloaded source files
data/processed/audio/        Normalized audio outputs
data/processed/translations/ Generated translation text files
data/metadata/               Exported CSV metadata
data/labeling/               Labeling-related uploads/data
logs/                        App and pipeline logs
```

## Files AI Nen Mo Dau Tien Theo Tinh Huong

- Neu sua API/job state: `backend/app/modules/audio_pipeline/api/routes.py`
- Neu sua pipeline flow: `backend/app/modules/audio_pipeline/application/workflow.py`
- Neu sua pipeline business logic: `backend/app/modules/audio_pipeline/application/pipeline_service.py`
- Neu sua UI dashboard: `frontend/src/pages/dashboard/DashboardPage.tsx`
- Neu sua call API tu frontend: `frontend/src/features/jobs/api/jobs.ts`
- Neu sua config/env: `backend/app/core/config.py`, `docker-compose.yml`
