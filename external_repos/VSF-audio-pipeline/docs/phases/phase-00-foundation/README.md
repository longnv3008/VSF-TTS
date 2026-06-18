# Phase 00 - Foundation

## Scope

Tang nay gom cac quyet dinh nen cua repo va ha tang phat trien.

## Current State

- Monorepo tach `backend/` va `frontend/`
- Docker Compose dung cho local stack `postgres`, `backend`, `frontend`
- Backend quan ly dependency bang `uv`
- Frontend quan ly dependency bang Yarn 1
- DB migration dung Alembic

## Key Files

- `README.md`
- `docker-compose.yml`
- `Makefile`
- `backend/pyproject.toml`
- `frontend/package.json`
- `backend/alembic/`

## Next Docs To Add Sau Nay

- Setup local environment checklist
- Deployment guide
- Backup/restore Postgres note
