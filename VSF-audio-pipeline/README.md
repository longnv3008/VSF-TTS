# VinSmart Future Audio Pipeline

Monorepo cho he thong ingest YouTube, xu ly audio, trich xuat translate full video va tao metadata. Repo nay duoc to chuc theo mot khung co the tai su dung cho cac project sau: frontend tach rieng, backend theo module, workflow ro rang, data va logs co cho rieng.

## 1. Muc tieu cua khung project

- De doc, de grep, de mo rong
- Frontend va backend tach vai tro ro rang
- Pipeline co cac step ro, de log, de retry
- Data runtime tach khoi source code
- Co san cho local dev va Docker deploy

## 2. Stack hien tai

- Frontend: React + Vite + Ant Design + TypeScript
- Backend: FastAPI + uv
- Database: PostgreSQL
- Workflow: LangGraph
- Audio tools: `yt-dlp` + `ffmpeg`
- Observability: LangSmith
- Dev runner: `Makefile` + Docker Compose

## 3. Khung thu muc

```text
VinSmart Future/
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── core/
│   │   ├── db/
│   │   ├── modules/
│   │   ├── observability/
│   │   └── utils/
│   ├── pyproject.toml
│   └── start.sh
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── entities/
│   │   ├── features/
│   │   ├── pages/
│   │   └── shared/
│   └── package.json
├── data/
│   ├── raw/
│   ├── processed/
│   ├── metadata/
│   └── processed/
├── logs/
├── docker-compose.yml
├── Makefile
├── README.md
├── structure.md
└── prompt.md
```

## 4. Cach chia backend

Backend duoc chia theo `module` thay vi dồn tat ca file vao mot cho.

```text
backend/app/
├── core/                 Settings, logging, app-level config
├── db/                   SQLAlchemy base, engine, session
├── modules/
│   ├── health/           Health check API
│   └── audio_pipeline/   Domain chinh cua he thong
├── observability/        Tracing, telemetry bootstrap
└── utils/                File helpers, logger helpers
```

Ben trong `audio_pipeline`:

```text
audio_pipeline/
├── api/                  Route + schema
├── application/          Business logic, workflow, worker
└── domain/               Model va domain state
```

Nguyen tac:

- `api/` chi xu ly HTTP schema va route
- `application/` chua service, workflow, orchestration
- `domain/` chua state va model mang tinh nghiep vu
- `core/`, `db/`, `utils/` la dung chung toan app

## 5. Cach chia frontend

Frontend di theo huong feature-based de sau nay them man hinh va domain moi de hon.

```text
frontend/src/
├── app/                  App shell, providers, global wiring
├── entities/             Model/type dung chung
├── features/             Tung tinh nang theo domain
├── pages/                Man hinh cap trang
└── shared/               API client, helper, UI dung chung
```

Nguyen tac:

- `pages/` lap rap UI theo man hinh
- `features/` chua logic theo bai toan
- `shared/` chi chua phan dung lai nhieu noi

## 6. Workflow hien tai

Luong xu ly chinh:

1. User gui danh sach YouTube URL
2. Backend tao `job`
3. Worker chay workflow
4. Workflow xu ly theo step
5. Ket qua duoc ghi vao `data/`

Chuoi step hien tai:

```text
validate_urls
-> crawl_audio
-> normalize_audio
-> segment_and_label
-> build_segment_metadata
```

Output cua pipeline la cac segment WAV per cau + file transcript TXT tuong ung, va file tong hop `data/metadata/<batch>_segments.csv` / `.jsonl` chua toan bo thong tin segment (audio_id, segment_id, start, end, text, transcript_source, ...).

VAD chay truc tiep trong backend bang ONNX Runtime (cau hinh bang bien `VAD_MODEL_PATH`). Khi video thieu phu de (khong co file `.vtt`), pipeline tu dong fallback sang ASR dung `faster-whisper` (cau hinh bang `ASR_MODEL` va `ASR_DEVICE`).

Bien moi can cau hinh (chua co trong `.env.example`, can them thu cong):

```text
VAD_MODEL_PATH      Duong dan model ONNX VAD, vi du: ../VAD/models/vad/1/vad.onnx
VAD_THRESHOLD       Nguong xac suat noi (default: 0.7)
VAD_MIN_VOLUME      Nguong volume toi thieu (default: 0.6)
SEGMENTS_DIR        Thu muc luu segment WAV (default: data/processed/segments)
SENTENCE_MAX_SEC    Do dai toi da mot cau tinh bang giay (default: 12.0)
SENTENCE_MIN_SEC    Do dai toi thieu mot cau tinh bang giay (default: 0.3)
PHRASE_GAP_SEC      Khoang lang toi thieu de cat cau (default: 0.45)
ASR_MODEL           Ten model faster-whisper (default: large-v3)
ASR_DEVICE          Thiet bi chay ASR: cuda hoac cpu (default: cuda)
```

## 7. Quy uoc data va runtime

```text
data/raw/youtube/             File tai ve tu nguon
data/processed/audio/         WAV sau normalize
data/processed/translations/  Translate full video dang text
data/metadata/                CSV metadata cho wav + translation
logs/                         Log runtime
```

Khuyen nghi:

- Khong commit file runtime lon
- Commit file mau, metadata mau neu can demo
- Tach `source code` va `runtime data` ro rang

## 8. Moi truong va config

Tao `.env` tu `.env.example`:

```bash
cp .env.example .env
```

Bien quan trong:

- `DATABASE_URL`
- `POSTGRES_*`
- `RAW_YOUTUBE_DIR`
- `PROCESSED_AUDIO_DIR`
- `PROCESSED_TRANSLATION_DIR`
- `METADATA_DIR`
- `YT_DLP_COOKIE_FILE`
- `YT_DLP_PROXY_BACKUPS`
- `LANGSMITH_*`

Luu y:

- Neu co the, uu tien dung duong dan ro rang khi deploy
- Neu dung duong dan relative, phai start app dung root project

## 9. Lenh dev nhanh

Backend:

```bash
uv sync --project backend
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Cau hinh account YouTube cho `yt-dlp` bang `cookies.txt`:

```bash
mkdir -p cookies
# Dat file cookies.txt vao ./cookies/youtube.txt
export YT_DLP_COOKIE_FILE=/home/you/path/to/VinSmart\ Future/cookies/youtube.txt
# Neu co them 1 cookie backup
export YT_DLP_COOKIE_BACKUP_FILE=/home/you/path/to/VinSmart\ Future/cookies/youtube_backup.txt
```

Neu dung Docker Compose, co the dat trong `.env`:

```bash
YT_DLP_COOKIE_FILE=/app/cookies/youtube.txt
YT_DLP_COOKIE_BACKUP_FILE=/app/cookies/youtube_backup.txt
```

Backend se uu tien `YT_DLP_COOKIE_FILE`. Neu cookie chinh bi loi theo kieu invalid/expired, URL hien tai se duoc retry lai bang `YT_DLP_COOKIE_BACKUP_FILE` neu file backup ton tai. Neu khong co cookie hop le, crawl van chay theo guest session va ghi warning trong log.

Discovery agent co the doc topic tim kiem tu file `topic.txt` o root project:

```bash
DISCOVERY_ENABLED=true
DISCOVERY_BATCH_SIZE=20
DISCOVERY_CYCLE_LIMIT_PER_START=0
DISCOVERY_MIN_DELAY_SEC=5.0
DISCOVERY_MAX_DELAY_SEC=10.0
DISCOVERY_TOPIC_FILE=topic.txt
DISCOVERY_QUERY_WINDOW_SIZE=20
```

Neu `DISCOVERY_TOPIC_FILE` ton tai, backend se uu tien doc tung dong trong file nay de tim URL moi. Cac dong rong, header nhu `keyword` va topic bi trung lap se tu dong bi bo qua. `DISCOVERY_QUERY_WINDOW_SIZE` quy dinh moi vong discovery se quet bao nhieu topic lien tiep trong file truoc khi xoay sang nhom topic ke tiep. Neu file khong ton tai, discovery moi fallback sang `DISCOVERY_SEARCH_QUERIES`.

`DISCOVERY_CYCLE_LIMIT_PER_START` gioi han so lan discovery agent duoc phep chay trong moi lan start backend. Dat `10` nghia la server chi cho phep toi da 10 discovery cycle sau moi lan khoi dong. Dat `0` de khong gioi han va giu nguyen hanh vi cu.

Cau hinh proxy failover cho `yt-dlp` de giam nguy co rate limit:

```bash
YT_DLP_PROXY_BACKUPS=http://user:pass@5.6.7.8:8000,http://user:pass@9.10.11.12:8000,http://user:pass@13.14.15.16:8000
```

`YT_DLP_PROXY_BACKUPS` co the tach bang dau phay, dau `;` hoac xuong dong. Backend se uu tien ket noi `direct` bang IP mang cua may/server. Chi khi `direct` bi rate limit/block thi moi chuyen sang backup, va sau khi mot route bi block no se vao cooldown trong mot khoang thoi gian roi moi duoc dung lai.

Luu y:

- Proxy co the giam rate limit, nhung khong dam bao vuot duoc anti-bot cua YouTube.
- Moi batch se co xu huong giu mot proxy on dinh; khong doi IP lien tuc neu chua gap rate limit.
- Neu dang dung `cookies.txt`, van nen uu tien proxy sticky va giam toc do crawl de tranh session bi danh dau bat thuong.

Frontend:

```bash
cd frontend
yarn install
yarn dev
```

Docker:

```bash
docker compose up --build
```

Makefile:

```bash
make install
make backend-run
make frontend-run
make migrate
make up
make down
```

## 10. API chinh

- `GET /api/v1/health`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/ingest`

Body mau:

```json
{
  "batch_name": "batch_001",
  "urls": [
    "https://www.youtube.com/watch?v=xxxx"
  ]
}
```

## 11. Cach mo rong sau nay

- Thay subtitle source hoac them model translate rieng trong step `build_translations`
- Them upload TikTok/YouTube Shorts: tao module moi hoac step moi
- Them queue thuc thu: doi worker sang Celery, RQ hoac Dramatiq
- Them object storage: tao storage adapter cho MinIO/S3
- Them auth/admin: mo rong `api`, `application`, `domain`

## 12. Ly do khung nay de tai su dung

Khung nay hop voi cach lam viec theo huong:

- bat dau nhanh
- de doc tren terminal
- de tach frontend/backend
- co cho cho workflow AI, job, log, data
- de dua cho AI sinh project moi theo mot format on dinh

Neu dung repo nay lam mau cho project moi, hay doc them [structure.md](/home/hung/code/VinSmart Future/structure.md) va [prompt.md](/home/hung/code/VinSmart Future/prompt.md).
