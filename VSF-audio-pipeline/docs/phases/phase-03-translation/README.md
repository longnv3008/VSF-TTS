# Phase 03 - Translation

## Scope

Sinh translation full video tu audio da chuan hoa.

## Current State

- Workflow step: `build_translations`
- Translation path moi nhat duoc day vao state de phuc vu cac step sau
- Output duoc ghi vao `data/processed/translations`

## Key Files

- `backend/app/modules/audio_pipeline/application/workflow.py`
- `backend/app/modules/audio_pipeline/application/pipeline_service.py`
- `backend/app/modules/audio_pipeline/application/job_progress.py`

## Open Notes

- Chua co doc rieng mo ta format translation output
- Neu sau nay them subtitle/chunk-level outputs, cap nhat phase nay truoc
