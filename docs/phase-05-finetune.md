# Phase 5 — Finetune VAD Model

## Role trong pipeline

```
[TTS data / YouTube WAV + timestamps]
  → prepare_dataset.py → train.npz, val.npz
  → train.py → checkpoints/best_model.pth
  → export_onnx.py → checkpoints/vad_finetuned.onnx
  → evaluate.py → so sánh với VAD/models/vad/1/vad.onnx
  → (nếu pass gate) → deploy: copy sang VAD/models/vad/1/vad.onnx
```

## Mục tiêu

Train lại Silero VAD trên data TTS tiếng Việt → cải thiện detection rate ở ngưỡng production (`threshold=0.7`, `min_volume=0.6`) mà không tăng false alarm.

**Lý do cần finetune:** Silero pretrain đa ngôn ngữ, chưa tối ưu cho giọng TTS tổng hợp tiếng Việt (giọng đều, ít noise tự nhiên).

## Trạng thái hiện tại (2026-06-18)

> [!WARNING]
> **Chưa deploy.** Smoke run (Phase 1–4) đã verify pipeline chạy được, nhưng model finetuned chưa đạt gate deploy:
> - `Detection@0.7` trên val set **giảm** so với baseline
> - `finetune/checkpoints/vad_finetuned.onnx` là smoke model, KHÔNG dùng production
> - Direct `onnx2torch` conversion bị block bởi Silero `If` op trong ONNX graph → dùng JIT fallback model
> - JIT fallback max diff ~0.032 so với production ONNX

## Deploy gate

Model mới được deploy khi:
- Detection Rate @ threshold=0.7 **tăng ≥ 5%** so với baseline
- False Alarm Rate **không tăng**
- Chạy được full eval trên `tmp/` (67 files) + validation set

## Data sources

```
tmp/                                          67 WAV TTS files (label = 100% speech)
e:/VSF/data/processed/audio/                  28 YouTube WAV dài (noise/silence tự nhiên)
e:/VSF/data/experiments/vad_asr_compare/      sentences.jsonl (timestamps đã label)
```

## Quickstart

### 0. Cài env

```powershell
python -m venv .venv-finetune
.venv-finetune\Scripts\pip install -r finetune\requirements-finetune.txt
# Cần CUDA torch để train nhanh — xem finetune/requirements-finetune.txt
```

### 1. Prepare dataset

```powershell
python finetune\prepare_dataset.py `
  --tts-dir tmp `
  --youtube-dir e:\VSF\data\processed\audio `
  --exp-dir e:\VSF\data\experiments\vad_asr_compare\youtube_all_cuda_debug_limit1 `
  --out-dir finetune\data
# Output: finetune/data/train.npz (1.2M chunks), finetune/data/val.npz (217K chunks)
```

### 2. Finetune

```powershell
# GPU (khuyên dùng)
python finetune\train.py --device cuda --amp --epochs 50 --batch-size 256

# CPU
python finetune\train.py --device cpu --epochs 30 --batch-size 128

# Conservative (chỉ finetune layers cuối)
python finetune\train.py --device cuda --freeze-layers 10 --lr 5e-5
```

### 3. Export ONNX

```powershell
python finetune\export_onnx.py `
  --checkpoint finetune\checkpoints\best_model.pth `
  --output finetune\checkpoints\vad_finetuned.onnx `
  --verify
```

### 4. Evaluate

```powershell
python finetune\evaluate.py `
  --old-model VAD\models\vad\1\vad.onnx `
  --new-model finetune\checkpoints\vad_finetuned.onnx `
  --tts-dir tmp `
  --threshold 0.7 --min-volume 0.6
```

### 5. Deploy (nếu pass gate)

```powershell
# Backup
Copy-Item VAD\models\vad\1\vad.onnx VAD\models\vad\1\vad_backup.onnx

# Deploy
Copy-Item finetune\checkpoints\vad_finetuned.onnx VAD\models\vad\1\vad.onnx

# Restart Triton
docker restart vad-server
```

## Hyperparameters quan trọng

| Param | Default | Ghi chú |
|---|---|---|
| `--lr` | `1e-4` | Giảm `5e-5` nếu train không ổn định |
| `--pos-weight` | `1.5` | Weight speech trong BCE loss — tăng nếu miss speech |
| `--freeze-layers` | `0` | Full finetune. Tăng nếu muốn conservative |
| `--epochs` | `50` | Early stopping tự dừng |
| `--batch-size` | `256` | Giảm nếu OOM |

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân | Chỗ fix |
|---|---|---|
| Detection Rate giảm sau finetune | Overfitting hoặc data imbalance | Điều chỉnh `--pos-weight`, `--freeze-layers` |
| OOM khi train | Batch quá lớn | Giảm `--batch-size` |
| Export ONNX fail | JIT model không compatible | Xem `convert_onnx_to_torch.py` — đã có fallback |
| Max diff cao (~0.032) | JIT ≠ ONNX exact | Known issue, chưa fix. Deploy gate vẫn valid |

## Cấu trúc finetune/

```
finetune/
  prepare_dataset.py       Bước 1: extract frames + labels
  dataset.py               PyTorch Dataset (weighted sampling)
  convert_onnx_to_torch.py Bước 2a: ONNX → PyTorch (+ JIT fallback)
  train.py                 Bước 2b: training loop
  export_onnx.py           Bước 3: export sang ONNX
  evaluate.py              Bước 4: so sánh baseline vs finetuned
  requirements-finetune.txt
  data/                    train.npz, val.npz (gitignored)
  checkpoints/             best_model.pth, vad_finetuned.onnx (gitignored)
  training_log.json        Kết quả training runs đã chạy
```
