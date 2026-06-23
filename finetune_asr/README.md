# finetune_asr — LoRA fine-tune Whisper (ASR cho WER gate)

> **Vai trò:** offline, optional. Fine-tune Whisper trên VN ASR sạch → ASR tốt hơn cho WER
> gate (gate so ASR vs VTT). KHÔNG đụng label VTT. v1 minimal: 1 LoRA run, chưa Optuna/aug.
> **Spec:** [`docs/superpowers/specs/2026-06-23-finetune-asr-lora-design.md`](../docs/superpowers/specs/2026-06-23-finetune-asr-lora-design.md)

## Gotcha quan trọng

`faster-whisper` (CTranslate2) **không load được LoRA adapter (PEFT)**. Deploy =
merge adapter → HF model → `ct2-transformers-converter` → thư mục CT2 → trỏ `ASR_MODEL`.

## Cấu trúc

```
finetune_asr/
├── text_norm.py        # normalize_target (pure)
├── wer_eval.py         # score_wer micro (pure)
├── lora_config.py      # lora_params (pure) + build_lora_config (peft)
├── export_ct2.py       # build_ct2_convert_cmd (pure)
├── prepare_dataset.py  # B1: VIVOS -> 16kHz + target chuẩn hóa
├── train_lora.py       # B2: LoRA train (whisper-small)
├── evaluate.py         # B3: WER baseline vs fine-tuned (+ domain refs)
├── requirements-finetune-asr.txt
└── tests/test_pure.py  # unit thuần (stdlib, không torch)
```

## Quickstart

```bash
python -m venv .venv-finetune-asr
.venv-finetune-asr\Scripts\activate          # Windows
pip install -r finetune_asr/requirements-finetune-asr.txt

# B1: data
python finetune_asr/prepare_dataset.py --dataset AILAB-VNUHCM/vivos --out-dir data/vivos

# Smoke (verify stack, CPU 1 step)
python finetune_asr/train_lora.py --data-dir data/vivos --smoke

# B2: train thật (GPU)
python finetune_asr/train_lora.py --data-dir data/vivos --base openai/whisper-small \
  --out-dir checkpoints/whisper_lora --epochs 3

# B3: eval baseline vs fine-tuned
python finetune_asr/evaluate.py --data-dir data/vivos --base openai/whisper-small        # baseline
python finetune_asr/evaluate.py --data-dir data/vivos --adapter checkpoints/whisper_lora \
  --domain-csv refs_94.csv                                                               # fine-tuned

# Export CT2 (sau khi merge adapter -> HF model_dir)
ct2-transformers-converter --model merged_hf_dir --output_dir ct2_whisper_vi --quantization float16
```

## Deploy gate

Chỉ trỏ `ASR_MODEL` vào CT2 mới **NẾU** WER fine-tuned < baseline trên **domain eval**
(94 human refs từ manual review), không chỉ trên VIVOS test. VIVOS là read-speech; crawl
YouTube có giọng hát → cải thiện VIVOS chưa chắc transfer. Rollback = trỏ lại model cũ.

## Test

```bash
# Pure units (không cần torch):
uv run --with pytest --no-project python -m pytest finetune_asr/tests/test_pure.py -q
```
