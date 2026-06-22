#!/bin/sh
set -e

cd /app/backend
# Python cua base image (co torch+torchaudio+app deps da cai). PYTHONPATH cho 'app'
# import tu source mount (compose mount ./backend:/app/backend de uvicorn --reload).
export PYTHONPATH=/app/backend

resolve_device() {
  requested="$1"
  if [ "$requested" != "auto" ]; then
    printf '%s' "$requested"
    return
  fi

  python -c "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')"
}

export DEMUCS_DEVICE="$(resolve_device "${DEMUCS_DEVICE:-auto}")"
export ASR_DEVICE="$(resolve_device "${ASR_DEVICE:-auto}")"

echo "Resolved runtime devices: DEMUCS_DEVICE=${DEMUCS_DEVICE}, ASR_DEVICE=${ASR_DEVICE}"

alembic -c alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
