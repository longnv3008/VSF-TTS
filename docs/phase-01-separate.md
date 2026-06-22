# Phase 1 — Vocal Separation (Demucs)

## Role trong pipeline

```
raw audio (mixed: voice + music/noise)
  → Demucs (htdemucs model)
  → vocals.wav (clean voice stem, native SR)
  → Phase 2 (Clean/normalize)
```

Demucs chạy trên full-quality raw audio, **không** downsample trước. Chỉ stem vocals được đưa vào VAD, giúp speech detection chính xác hơn khi audio có nhạc nền.

## Venv riêng (bắt buộc)

Demucs cần `torch` — **không** cài vào `.venv-vad` (VAD env không có torch, giữ nhẹ).

```powershell
# CPU (torch 2.2.2 pinned — KHÔNG nâng lên 2.9+ vì torchaudio breakage)
python -m venv .venv-demucs
.venv-demucs\Scripts\pip install -r requirements-demucs.txt

# GPU — CUDA 12.8 (torch 2.8 cu128)
python -m venv .venv-demucs-cu128
.venv-demucs-cu128\Scripts\pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv-demucs-cu128\Scripts\pip install demucs>=4.0
```

> [!WARNING]
> `torchaudio >= 2.9` routes through torchcodec → breaks Demucs.
> `numpy >= 2.x` breaks `torch==2.2.x`.
> Giữ `numpy<2`, `torch==2.2.2` cho CPU env.

## Auto-resolve

Pipeline tự tìm Demucs theo thứ tự ưu tiên (logic trong `scripts/demucs_env.py`):
1. `.venv-demucs-cu128\Scripts\python.exe` (GPU env)
2. `.venv-demucs\Scripts\python.exe` (CPU env)
3. `python -m demucs` (system python)
4. Nếu không có → fallback về raw audio (log warning, không crash)

## Crawl path: auto routing theo noise floor

Trên crawl path (backend `pipeline_service._should_use_demucs_for_row`),
`DEMUCS_MODE=auto` (mặc định) **không** tách mọi file. Thay vào đó đo noise floor
của raw file bằng `ffmpeg astats` (`separation/noise_probe.py`):

- noise floor ≥ `DEMUCS_NOISE_FLOOR_DB` (mặc định `-50` dB) → file nhiễu → Demucs
  (reason `auto_noise_high`).
- thấp hơn → file sạch → bỏ Demucs, chỉ ffmpeg (reason `auto_noise_low`).
- probe lỗi (vd thiếu ffmpeg) → fallback an toàn không Demucs (`auto_noise_unknown`).

`DEMUCS_MODE=on` ép Demucs mọi file; `off` tắt hẳn. Raw crawl là webm/m4a/opus nên
dùng astats (đọc mọi format) thay vì đọc PCM trực tiếp. Ngưỡng `-50` dB là điểm
khởi đầu — tune để ~20% file rơi vào Demucs trên data thực.

## Local path: Demucs ON by default

Trên `end_to_end_pipeline.py` (local), Demucs tự chạy nếu venv tìm thấy (flag
`--demucs/--no-demucs`); local path chưa có auto routing theo noise.

```powershell
# Chạy bình thường (Demucs auto)
python scripts\end_to_end_pipeline.py --raw-dir tmp --work-dir pipeline_runs\test

# Tắt Demucs
python scripts\end_to_end_pipeline.py --raw-dir tmp --work-dir pipeline_runs\test --no-demucs

# Chỉ định env cụ thể + GPU
python scripts\end_to_end_pipeline.py `
  --raw-dir tmp `
  --work-dir pipeline_runs\test `
  --demucs-cmd '".venv-demucs-cu128\Scripts\python.exe" -m demucs' `
  --demucs-device cuda
```

## Output

```
<work-dir>/vocals/
  <stable_name>/htdemucs/<source_stem>/vocals.wav   ← vocal stem (native SR)
```

→ `vocals.wav` được feed vào Phase 2 (Clean) để downsample xuống 16kHz mono.

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân | Chỗ fix |
|---|---|---|
| `demucs did not produce vocals` | Demucs crash mid-run | Xem stderr, thường do OOM hoặc corrupt audio |
| Fallback về raw cho toàn bộ run | Venv không tìm thấy / torch import fail | Check `scripts/demucs_env.py:demucs_available()` |
| Per-file fallback, file còn lại OK | File đó corrupt hoặc format lạ | Preprocess file đó với ffmpeg |
| Demucs chậm trên CPU | Đúng — CPU Demucs rất chậm với audio dài | Dùng `--demucs-device cuda` hoặc `--no-demucs` |
| `numpy` version error | numpy 2.x + torch 2.2.x không tương thích | `pip install "numpy<2"` trong `.venv-demucs` |

## Files liên quan

- `scripts/demucs_env.py` — auto-resolve + probe logic
- `scripts/end_to_end_pipeline.py:separate_vocals()` — local orchestration
- `.../application/separation/noise_probe.py` — crawl-path noise-floor routing
- `.../application/pipeline_service.py:_should_use_demucs_for_row()` — auto/on/off
- `requirements-demucs.txt` — pinned deps CPU env
