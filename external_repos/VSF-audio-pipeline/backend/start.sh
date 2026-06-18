#!/bin/sh
set -e

cd /app/backend
# Python cua base image (co torch+torchaudio+demucs+app deps da cai). PYTHONPATH cho 'app'
# import tu source mount (compose mount ./backend:/app/backend de uvicorn --reload).
export PYTHONPATH=/app/backend
alembic -c alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
