# Phase 04 - Metadata

## Scope

Tong hop translation rows va sinh file metadata CSV cuoi cung.

## Current State

- Workflow step cuoi: `build_metadata`
- Output file mac dinh theo pattern: `{batch_name}_processed_metadata.csv`
- Metadata duoc ghi vao `data/metadata`

## Key Files

- `backend/app/modules/audio_pipeline/application/workflow.py`
- `backend/app/modules/audio_pipeline/application/pipeline_service.py`
- `data/metadata/`

## Open Notes

- Nen bo sung metadata schema doc sau khi format on dinh
- Neu doi ten cot CSV, cap nhat docs nay va `project-memory.md`
