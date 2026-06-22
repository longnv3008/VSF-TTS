.PHONY: help install backend-install frontend-install backend-run frontend-run migrate migrate-down migrate-current migrate-history migrate-create up down backend-recreate

MIGRATION_MSG ?= update schema

help:
	@echo "Available commands:"
	@echo "  make install                         Install frontend and backend dependencies"
	@echo "  make backend-install                 Install backend dependencies with uv"
	@echo "  make frontend-install                Install frontend dependencies with yarn"
	@echo "  make backend-run                     Run FastAPI backend locally with uv"
	@echo "  make frontend-run                    Run Vite frontend locally with yarn"
	@echo "  make migrate                         Apply all Alembic migrations with uv"
	@echo "  make migrate-down                    Roll back one Alembic revision"
	@echo "  make migrate-current                 Show current Alembic revision"
	@echo "  make migrate-history                 Show Alembic migration history"
	@echo "  make migrate-create MIGRATION_MSG='add new column'"
	@echo "  make up                              Start Docker Compose stack"
	@echo "  make down                            Stop Docker Compose stack"
	@echo "  make backend-recreate                Recreate backend container to reload .env changes"

install: backend-install frontend-install

backend-install:
	uv sync --project backend

frontend-install:
	cd frontend && yarn install

backend-run:
	uv run --project backend uvicorn app.main:app --reload

frontend-run:
	cd frontend && yarn dev

migrate:
	uv run --project backend alembic -c backend/alembic.ini upgrade head

migrate-down:
	uv run --project backend alembic -c backend/alembic.ini downgrade -1

migrate-current:
	uv run --project backend alembic -c backend/alembic.ini current

migrate-history:
	uv run --project backend alembic -c backend/alembic.ini history

migrate-create:
	uv run --project backend alembic -c backend/alembic.ini revision --autogenerate -m "$(MIGRATION_MSG)"

up:
	docker compose up --build

down:
	docker compose down

backend-recreate:
	docker compose up -d --force-recreate backend
