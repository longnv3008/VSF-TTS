# Task: Finetune Silero VAD Pipeline

## Phase 1 - Data Preparation
- [x] Khao sat cau truc data hien co (`tmp/`, `processed/audio/`, `experiments/`)
- [x] Hieu format `vad_chunks.jsonl` va `sentences.jsonl`
- [x] Tao `finetune/prepare_dataset.py` - extract frames + labels tu audio + timestamps
- [x] Tao `finetune/dataset.py` - PyTorch Dataset class
- [x] Chay full prepare dataset
  - `train.npz`: 1,231,820 chunks
  - `val.npz`: 217,379 chunks

## Phase 2 - Model Conversion & Training
- [x] Tao `finetune/convert_onnx_to_torch.py`
- [!] Direct `onnx2torch` conversion bi chan boi ONNX `If` op trong Silero graph
- [x] Them fallback trainable Silero JIT model
- [x] Tao `finetune/train.py` - training loop voi weighted BCE probability loss
- [x] Tao `finetune/requirements-finetune.txt`
- [x] Chay smoke train tren CUDA
  - command: `python finetune\train.py --device cuda --amp --epochs 1 --batch-size 256 --max-train-batches 10 --max-val-batches 5`
  - output: `finetune/checkpoints/best_model.pth`

## Phase 3 - Export & Evaluation
- [x] Tao `finetune/export_onnx.py` - export model sang ONNX same Triton input names
- [x] Tao `finetune/evaluate.py` - so sanh model cu vs moi
- [x] Export smoke ONNX: `finetune/checkpoints/vad_finetuned.onnx`
- [x] Chay smoke evaluation
  - output: `finetune/evaluation_report_smoke.csv`
  - result: smoke model chua dat gate deploy vi Detection@0.7 tren val giam

## Phase 4 - Verify
- [x] `python -m py_compile ...`
- [x] Verify data pipeline
- [!] Verify convert exact voi production ONNX chua dat; fallback JIT max diff observed ~0.032
- [x] Verify train/export/evaluate smoke pipeline

## Project Review Quick Wins
- [x] Fix `model.py` guard missing session / empty ready batch
- [x] Fix `client.py` WAV file close
- [x] Fix `microphone.py` cleanup on Ctrl+C
