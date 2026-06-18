# Phase 02 - Audio Processing

## Scope

Tai audio tu nguon va chuan hoa thanh output co the dung cho xu ly tiep.

## Current State

- Workflow dang goi `crawl_audio` roi `normalize_audio`
- Runtime tool co khai bao: `yt-dlp`, `ffmpeg`, `soundfile`
- Ket qua audio sau xu ly duoc dua vao `data/processed/audio`

## Key Files

- `backend/app/modules/audio_pipeline/application/workflow.py`
- `backend/app/modules/audio_pipeline/application/pipeline_service.py`
- `backend/app/utils/filesystem.py`
- `backend/app/core/config.py`

## Data Outputs

- Input source: `data/raw/youtube`
- Output processed: `data/processed/audio`

## Open Notes

- Nen ghi ro naming convention cua file audio neu sau nay pipeline phuc tap hon
- Neu them retry per-step, cap nhat lai docs phase nay
