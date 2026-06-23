# Augmentation + Optuna HPO for finetune_asr — design

**Date:** 2026-06-23
**Status:** approved
**Scope:** Sub-project #6 of the WER-reduction effort, built on #5's `finetune_asr/` module.
Two independent slices (A: augmentation, B: Optuna HPO). Both opt-in; default OFF preserves
#5's existing run behaviour.

## Goal

Improve LoRA fine-tune generalization (acoustic diversity) and pick better hyper-parameters,
per the notebook recipes. Augmentation adds train-time waveform/spec perturbations; Optuna
searches lr/rank/dropout against eval WER. ROI is still tied to the ASR gate (off by
default) — value shows only after a real GPU run.

## Slice A — augmentation (`finetune_asr/augment.py`)

Pure transforms (numpy; librosa lazy-imported only for pitch/stretch):

- `add_noise(y, snr_db, rng)` — add Gaussian noise scaled to a target SNR. numpy only.
- `spec_augment(feats, *, n_freq_masks, freq_w, n_time_masks, time_w, rng)` — zero out
  random freq/time bands on a log-mel array. numpy only.
- `pitch_shift(y, sr, n_steps)` — librosa wrapper.
- `time_stretch(y, rate)` — librosa wrapper.
- `apply_waveform_augment(y, sr, rng, *, p_pitch, p_speed, p_noise, ...)` — randomly applies
  pitch/speed/noise per-sample by probability; returns possibly-modified waveform.

Hook into `train_lora._to_features`: when `--augment` is set, apply
`apply_waveform_augment` to `audio["array"]` before the feature extractor, then
`spec_augment` to `input_features` after. Default OFF → #5 behaviour unchanged.

## Slice B — Optuna HPO (`finetune_asr/hpo.py`)

- `suggest_params(trial)` — build a params dict from `trial.suggest_float/int` for
  `lr` (log 1e-5..1e-3), `rank` (4,8,16,32), `dropout` (0.0..0.2). Testable with a fake trial.
- `run_study(n_trials, *, data_dir, base, ...)` — `optuna.create_study(direction="minimize")`;
  the objective calls `train_lora.train(...)` then `evaluate.evaluate(...)`, returns the
  WER to minimize. CLI: `python hpo.py --n-trials N --data-dir data/vivos`.

Add `optuna` to `requirements-finetune-asr.txt` (librosa already listed).

## Units that get TDD (pure)

- `add_noise`: output shape preserved, values changed, higher SNR → smaller perturbation.
- `spec_augment`: masked cells become 0, shape preserved, seeded rng deterministic.
- `apply_waveform_augment`: with a seeded rng and injected fake transforms, application is
  deterministic and respects probabilities (p=0 → unchanged, p=1 → applied).
- `suggest_params`: a fake trial returning fixed values yields the expected dict with keys
  `lr`/`rank`/`dropout`.
- `pitch_shift` / `time_stretch`: under `pytest.importorskip("librosa")` — shape/length
  sanity only.

## Manual / GPU steps

Training with augmentation and a real Optuna study are GPU steps the operator runs. Tests
cover the pure transforms and search-space wiring, not training outcomes.

## Testing

Augmentation tests need numpy (and librosa for two of them) → run in an ephemeral env
(`uv run --with pytest --with numpy --with librosa --no-project`), separate from the backend
suite. HPO `suggest_params` test needs only a fake trial (stdlib). No backend files change.

## Verification

Pure-unit tests green in the ephemeral env. `train_lora`/`hpo` modules import without torch
(heavy deps stay inside functions). #5 default run is unchanged (augment OFF by default).
