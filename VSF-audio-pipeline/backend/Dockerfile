# Base mang san torch/torchaudio 2.8.0 + CUDA 12.8 (cu128) duoi dang layer dung san:
# `docker pull` tai layer nen (~4.3GB) thay vi unpack wheel torch ~3GB luc build ->
# tranh spike RAM gay WSL2 OOM crash. Demucs + app deps cai them ben tren.
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    gcc \
    libsndfile1 \
    libgomp1 \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Deno giup yt-dlp xu ly YouTube JS challenge thong qua yt-dlp-ejs.
# --retry: deno.land thinh thoang dut TLS (curl 56 SSL eof) -> retry tu dong.
RUN curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 https://deno.land/install.sh | sh

ENV PATH="/root/.deno/bin:${PATH}"

# Cai app + extra demucs vao python cua base image (da co torch 2.8.0+cu128 + torchaudio).
# torch==2.8.0/torchaudio==2.8.0 trong [demucs] da thoa man -> pip BO QUA (khong tai lai ~3GB).
# Dung python he thong cua base (KHONG /opt/venv): compose mount ./backend khong che
# site-packages (nam o /opt/conda), nen khong can venv ngoai mount nhu truoc.
COPY backend /app/backend
RUN pip install --no-cache-dir "/app/backend[demucs]"
RUN sed -i 's/\r$//' /app/backend/start.sh

CMD ["sh", "/app/backend/start.sh"]
