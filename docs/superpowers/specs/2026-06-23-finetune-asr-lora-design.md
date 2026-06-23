# LoRA fine-tune Whisper (ASR) — v1 minimal — design

**Date:** 2026-06-23
**Status:** approved
**Scope:** Sub-project #5 (v1 minimal) of the WER-reduction effort. #4 (GFD) skipped —
CTranslate2 does not expose per-step logits, real GFD needs replacing the ASR backend (multi-
week research, low ROI). #6 (audio augmentation) and Optuna HPO deferred to later slices.

## Goal

Fine-tune Whisper with LoRA on a clean Vietnamese ASR dataset so the gate's ASR is more
accurate (fewer false WER flags). New **offline** module, independent of the backend. The
backend is unchanged until an operator deploys a converted model via `ASR_MODEL`.

ROI is honestly modest: ASR feeds only the gate (off by default), and VIVOS is read-speech
whereas crawl audio includes singing — the domain eval (94 human refs from manual review)
will show whether it transfers.

## Integration gotcha (key constraint)

The backend ASR runs on `faster-whisper` (CTranslate2). CTranslate2 **cannot load a PEFT
LoRA adapter**. Deploy path: merge the LoRA adapter into the base HF model →
`ct2-transformers-converter` → CTranslate2 dir → point `ASR_MODEL` at it. `export_ct2.py`
owns this.

## New module `finetune_asr/` (sibling of `finetune/` which is VAD-only)

Own venv (like the demucs envs); own `requirements-finetune-asr.txt`
(`transformers`, `peft`, `datasets`, `accelerate`, `evaluate`, `ctranslate2`).

- `prepare_dataset.py` — load VIVOS (~15h, HF `datasets`), resample to 16 kHz, normalize the
  transcript target (NFC, lowercase, strip punctuation; reuse the approach in
  `eval/wer/vsf_wer/normalize.py`, diacritics kept — phonemic). Save processed splits to disk.
- `train_lora.py` — `WhisperForConditionalGeneration` + `peft` LoRA (target `q_proj`,
  `v_proj`; rank/alpha/lr defaults), `Seq2SeqTrainer`. Base default `openai/whisper-small`
  (VRAM-friendly; large-v3 too heavy for a v1 LoRA run). Save the adapter.
- `evaluate.py` — WER on the VIVOS test split + the domain eval (94 human refs), scored with
  `vsf_wer`. Reports baseline vs fine-tuned.
- `export_ct2.py` — merge adapter into base, convert to CTranslate2 for faster-whisper.
- `README.md` — quickstart + **deploy gate**: only swap `ASR_MODEL` if fine-tuned WER beats
  baseline on the domain eval.

## Units that get TDD (pure, fast)

1. `normalize_target(text)` — training-target text normalization (own small function in the
   module; do not import the backend/eval package across project boundaries).
2. `build_lora_config(rank, alpha, dropout)` — returns a `peft.LoraConfig` with the right
   target modules; test the field values without loading a model.
3. `score_wer(refs, hyps)` — WER aggregation wrapper over `vsf_wer` for the eval report.
4. `build_ct2_convert_cmd(model_dir, out_dir, quantization)` — argv list for
   `ct2-transformers-converter`; test the command shape.

## Manual / GPU steps (not auto-tested)

Downloading VIVOS, the actual LoRA training run, and CT2 conversion are manual GPU steps.
The scaffold ships with a CPU smoke path (train on 1–2 samples for 1 step) to prove the
stack wires up. The real run is the operator's.

## Testing

- `normalize_target`: punctuation/case stripped, diacritics preserved, NFC.
- `build_lora_config`: r/alpha/dropout/target_modules as expected.
- `score_wer`: known refs/hyps → expected WER (matches `vsf_wer`).
- `build_ct2_convert_cmd`: argv contains converter, `--model`, `--output_dir`, quantization.

Tests live in `finetune_asr/tests/` and run under the module's own env. They must not import
torch/transformers at module top level for the pure-unit tests (keep them importable without
the heavy deps where practical), or are skipped if deps absent.

## Verification

Pure-unit tests green in the module env. CPU smoke (1-step train) runs without error. Real
training + domain-eval improvement is reported by `evaluate.py` after the operator's GPU run.
Backend untouched → existing backend suite stays green (no backend files changed in v1).
