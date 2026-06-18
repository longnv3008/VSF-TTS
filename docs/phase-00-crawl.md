# Phase 0 — Crawl (YouTube → Raw Audio)

## Role trong pipeline

```
[YouTube URLs] → crawl → raw audio files (.wav/.webm/.mp4) → Phase 1 (Demucs)
```

## Entry point

Script: `scripts/run_vsf_github_to_labels.py` (full crawl + VAD labels)  
Script: `scripts/run_vsf_github_crawl.py` (crawl only, không chạy VAD)

## Repo crawler

Crawler nằm trong repo: folder `VSF-audio-pipeline/` (trước là submodule, nay là folder thường trong dự án).

Backend crawler cần setup env riêng (FastAPI + Postgres). Script `run_vsf_github_crawl.py` bypass FastAPI, gọi trực tiếp vào backend service. Setup env: `uv sync --project VSF-audio-pipeline/backend` (xem `setup_new_machine.ps1`).

## Cách chạy crawl + full pipeline

```powershell
# Tạo file URL
Set-Content urls.txt "https://www.youtube.com/watch?v=VIDEO_ID"

# Full crawl → VAD → labels
python scripts\run_vsf_github_to_labels.py `
  --urls-file urls.txt `
  --batch-name batch_001 `
  --work-dir pipeline_runs\batch_001 `
  --refine-boundaries

# Với cookies (video age/region-gated)
python scripts\run_vsf_github_to_labels.py `
  --urls-file urls.txt `
  --batch-name batch_001 `
  --cookie-file VSF-audio-pipeline\cookies\youtube.txt `
  --work-dir pipeline_runs\batch_001
```

## Output của phase này

```
pipeline_runs/<batch>/github_runtime/
  raw/youtube/          downloaded source files (.webm, .wav...)
  processed/audio/      WAV normalized bởi crawler repo
  processed/translations/  subtitle-derived text (.vtt)
```

→ Output `processed/audio/*.wav` được feed vào Phase 1 (Demucs) hoặc Phase 2 (Clean) nếu bỏ Demucs.

## Bỏ qua crawl (audio đã có sẵn)

Nếu audio đã download hoặc tự có:
```powershell
# Dùng --skip-crawl + chỉ đường dẫn tới WAV đã có
python scripts\run_vsf_github_to_labels.py `
  --skip-crawl `
  --processed-audio-dir VSF-audio-pipeline\data\processed\audio `
  --work-dir pipeline_runs\existing_audio
```

Hoặc dùng pipeline local (không cần crawler repo):
```powershell
python scripts\end_to_end_pipeline.py `
  --raw-dir tmp `
  --work-dir pipeline_runs\my_run
```

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân thường gặp | Chỗ fix |
|---|---|---|
| `ModuleNotFoundError` crawler | Chưa setup `VSF-audio-pipeline` | `uv sync --project VSF-audio-pipeline/backend` |
| Download fail / 403 | Video gated hoặc cookies hết hạn | Cập nhật `cookies/youtube.txt` |
| `processed/audio/` rỗng | Crawler chạy nhưng không output | Xem logs trong `github_summary.json` |
| Subtitle thiếu `.vtt` | Video không có auto-caption | Chạy với `--no-vtt`, dùng ASR fallback |

## Tham số quan trọng

- `--urls-file`: file chứa danh sách YouTube URL (1 URL/dòng)
- `--batch-name`: tên batch, dùng làm prefix segment ID
- `--cookie-file`: file Netscape cookies cho video gated
- `--skip-crawl`: bỏ qua crawl, dùng audio đã có
- `--processed-audio-dir`: path tới WAV đã có khi `--skip-crawl`
