# Finetune Pipeline — Silero VAD v6 on Vietnamese TTS Data

## Mô tả

Pipeline finetune Silero VAD v6 trên dữ liệu TTS tiếng Việt, mục tiêu cải thiện
detection rate khi dùng `threshold=0.7`, `min_volume=0.6` trong môi trường production.

## Cấu trúc

```
finetune/
├── prepare_dataset.py        # Bước 1: Tạo dataset từ audio + timestamps
├── dataset.py                # PyTorch Dataset (weighted sampling + augmentation)
├── convert_onnx_to_torch.py  # Bước 2a: Convert vad.onnx → trainable PyTorch
├── train.py                  # Bước 2b: Training loop
├── export_onnx.py            # Bước 3: Export model finetuned → ONNX
├── evaluate.py               # Bước 4: So sánh model cũ vs mới
├── requirements-finetune.txt # Dependencies
├── data/                     # Generated: train.npz, val.npz
└── checkpoints/              # Generated: best_model.pth, vad_finetuned.onnx
```

## Quickstart

> Status note: the current pipeline is verified end-to-end with a smoke run.
> Direct `onnx2torch` conversion of the production ONNX is not exact because
> Silero's graph contains nested `If` ops. The training code falls back to the
> official trainable Silero JIT model. The generated smoke model is for pipeline
> verification only and must not replace production until full training and
> evaluation pass the deploy gate.

### 0. Cài dependencies

```bash
pip install -r requirements-finetune.txt
```

### 1. Chuẩn bị dataset

```bash
python prepare_dataset.py \
  --tts-dir ../tmp \
  --youtube-dir ../../data/processed/audio \
  --exp-dir ../../data/experiments/vad_asr_compare/youtube_all_cuda_debug_limit1 \
  --out-dir data
```

Output: `data/train.npz` và `data/val.npz`

### 2. Verify ONNX → PyTorch conversion

```bash
python convert_onnx_to_torch.py \
  --onnx-path ../VAD/models/vad/1/vad.onnx \
  --verify --print-arch
```

### 3. Finetune

```bash
# Với GPU (khuyên dùng)
python train.py --device cuda --amp --epochs 50

# CPU only (chậm hơn ~10x)
python train.py --device cpu --epochs 30 --batch-size 128

# Chỉ finetune layers cuối (an toàn hơn, nhanh hơn)
python train.py --device cuda --freeze-layers 10 --lr 5e-5
```

### 4. Export ONNX

```bash
python export_onnx.py \
  --checkpoint checkpoints/best_model.pth \
  --output checkpoints/vad_finetuned.onnx \
  --verify
```

### 5. Evaluate so sánh

```bash
python evaluate.py \
  --old-model ../VAD/models/vad/1/vad.onnx \
  --new-model checkpoints/vad_finetuned.onnx \
  --tts-dir ../tmp \
  --threshold 0.7 --min-volume 0.6
```

Smoke evaluation from the project root:

```bash
python finetune\evaluate.py ^
  --new-model finetune\checkpoints\vad_finetuned.onnx ^
  --tts-dir tmp ^
  --threshold 0.7 --min-volume 0.6 ^
  --max-samples 2000 --max-tts-files 10 ^
  --output-csv finetune\evaluation_report_smoke.csv
```

### 6. Deploy (nếu model mới tốt hơn)

```bash
# Backup model cũ
cp ../VAD/models/vad/1/vad.onnx ../VAD/models/vad/1/vad_backup.onnx

# Deploy model mới
cp checkpoints/vad_finetuned.onnx ../VAD/models/vad/1/vad.onnx

# Restart Triton server
docker restart vad-server
```

## Hyperparameters quan trọng

| Param | Default | Mô tả |
|---|---|---|
| `--lr` | `1e-4` | Learning rate (giảm xuống `5e-5` nếu train không ổn định) |
| `--pos-weight` | `1.5` | Weight cho speech trong BCE loss (tăng nếu miss speech nhiều) |
| `--freeze-layers` | `0` | Số param groups freeze (0 = full finetune) |
| `--epochs` | `50` | Số epochs (early stopping tự dừng nếu không cải thiện) |
| `--batch-size` | `256` | Batch size (giảm nếu OOM) |

## Metrics đánh giá

- **Detection Rate @ threshold=0.7**: Tỷ lệ speech chunks được detect đúng ở ngưỡng production
- **False Alarm Rate @ threshold=0.7**: Tỷ lệ silence bị nhận nhầm thành speech
- **AUC-ROC**: Metric tổng quát, không phụ thuộc threshold

**Mục tiêu**: Detection Rate tăng ≥ 5% so với baseline mà không tăng False Alarm Rate.
