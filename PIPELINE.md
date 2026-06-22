# End-to-end crawl -> clean -> VAD -> label pipeline

This repository now has a thin offline pipeline wrapper around the existing VAD code:

```text
crawler repo / downloaded audio
  -> data/raw_audio/
  -> scripts/end_to_end_pipeline.py
  -> pipeline_runs/latest/clean_wav/
  -> pipeline_runs/latest/segments/
  -> pipeline_runs/latest/labels.csv
  -> pipeline_runs/latest/labels.jsonl
```

## Run with audio already crawled

Put audio files under `data/raw_audio/` or pass a custom folder:

```powershell
python scripts\end_to_end_pipeline.py `
  --raw-dir tmp `
  --work-dir pipeline_runs\tmp_test `
  --refine-boundaries
```

The script accepts `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.opus`, `.webm`, `.mp4`, and `.mkv`.
Every input is cleaned into mono 16 kHz 16-bit PCM WAV before VAD. Cleaning also
applies EBU R128 loudness normalization (`-af loudnorm`, default on; toggle with
`--loudnorm/--no-loudnorm`). With loudnorm on, even already-mono-16k WAV inputs are
re-encoded (the fast copy shortcut is skipped) so levels are normalized.

## Demucs vocal separation (on by default)

By default the pipeline runs [Demucs](https://github.com/facebookresearch/demucs)
to separate **vocals** from background music *before* clean/VAD. The Demucs
command is auto-resolved: a project-local `.venv-demucs` is used if present,
otherwise `python -m demucs`. If Demucs cannot run (no torch env), the pipeline
logs a warning and falls back to the raw `raw -> clean -> VAD` path. Disable
entirely with `--no-demucs`.

Demucs runs on the full-quality raw audio; only the vocal stem is downsampled to
16 kHz mono and fed into VAD, so segments are clean speech (better for TTS).

```text
raw -> Demucs (--two-stems vocals, native SR) -> vocal stem
    -> clean (downsample vocal -> mono 16k) -> VAD -> segments (cut from vocal)
```

Demucs needs `torch` (heavy), kept out of the VAD env. Use a dedicated env and
point `--demucs-cmd` at its python:

```powershell
python -m venv .venv-demucs
.venv-demucs\Scripts\pip install -r requirements-demucs.txt
python scripts\end_to_end_pipeline.py `
  --raw-dir tmp --work-dir pipeline_runs\demucs_test `
  --demucs --demucs-cmd '".venv-demucs\Scripts\python.exe" -m demucs' `
  --demucs-model htdemucs --demucs-device cpu --refine-boundaries
```

Use `--demucs-device cuda` (CUDA torch build) for large batches — CPU Demucs is
slow on long audio. Demucs is **on by default**. Per-file failures fall back to
raw for that file; a missing/broken Demucs env falls back to raw for the whole
run. Use `--no-demucs` to skip separation, or `--demucs-cmd` to point at a
specific env. Vocal stems land in `<work-dir>/vocals/`.

## Plug in a crawler repo

The GitHub repo `longnv3008/VSF-audio-pipeline.git` is wired in as a **git submodule** at:

```text
VSF-audio-pipeline
```

Fresh clones get it via `git clone --recursive`; otherwise run
`git submodule update --init --recursive`. Its backend env is built with
`uv sync --project VSF-audio-pipeline/backend` (see `setup_new_machine.ps1`).

Relevant docs/code read from that repo:

- `README.md`
- `docs/README.md`
- `docs/ai-context/project-memory.md`
- `docs/ai-context/repo-map.md`
- `docs/phases/phase-01-ingest/README.md`
- `docs/phases/phase-02-audio-processing/README.md`
- `docs/phases/phase-04-metadata/README.md`
- `backend/app/modules/audio_pipeline/application/pipeline_service.py`
- `backend/app/modules/audio_pipeline/application/workflow.py`

That repo's workflow is:

```text
validate_urls
  -> crawl_audio
  -> normalize_audio
  -> build_translations
  -> build_metadata
```

Its normalized WAV output is `data/processed/audio` by default. The local integration avoids starting FastAPI/Postgres and calls its backend service directly, then feeds the normalized WAV files into the local VAD/label pipeline.

## Full GitHub crawler -> local VAD labels

Create a URL file:

```powershell
Set-Content -Path urls.txt -Value @(
  "https://www.youtube.com/watch?v=VIDEO_ID"
)
```

Run the full pipeline:

```powershell
python scripts\run_vsf_github_to_labels.py `
  --urls-file urls.txt `
  --batch-name batch_001 `
  --work-dir pipeline_runs\vsf_github_batch_001 `
  --refine-boundaries
```

With a YouTube cookies file:

```powershell
python scripts\run_vsf_github_to_labels.py `
  --urls-file urls.txt `
  --batch-name batch_001 `
  --cookie-file VSF-audio-pipeline\cookies\youtube.txt `
  --work-dir pipeline_runs\vsf_github_batch_001 `
  --refine-boundaries
```

Demucs runs by default on the crawl path too (auto-resolved `.venv-demucs`, with
raw fallback when unavailable). The wrapper probes once and forwards the decision
to the repo: it sets `DEMUCS_ENABLED` and runs Demucs between crawl and normalize.
Use `--no-demucs` to skip it. `--demucs-cmd/--demucs-model/--demucs-device` still
apply; point `--demucs-cmd` at a torch-enabled env.

In `auto` mode (`DEMUCS_MODE=auto`, the default), the backend routes each file by
its measured noise floor instead of always separating: it runs `ffmpeg astats` on
the raw file and sends only noisy files (noise floor ≥ `DEMUCS_NOISE_FLOOR_DB`,
default `-50` dB) through Demucs; clean files go straight to ffmpeg. `DEMUCS_MODE=on`
forces Demucs for everything, `off` disables it. A failed probe (e.g. ffmpeg
missing) falls back safely to ffmpeg-only.

### Subtitles, labels, and the WER gate

Labels come only from YouTube subtitles. A video **without a usable `.vtt`
subtitle is skipped** — there is no ASR fallback that invents transcripts. VTT
captions are aligned to VAD speech regions and cleaned (blocklist/promo filtering +
VLSP normalization).

faster-whisper ASR is retained solely as an optional **WER gate** (off by default,
`WER_GATE_ENABLED`): when on, each kept segment is transcribed and compared against
its VTT text; segments with WER above `WER_GATE_MAX` (default `0.05`) are flagged
`needs_review` so misaligned captions can be caught. The canonical offline WER
report still lives in `eval/wer/`.

Outputs:

```text
pipeline_runs/vsf_github_batch_001/
  github_runtime/raw/youtube/              downloaded source files
  github_runtime/processed/audio/          normalized WAV from GitHub repo
  github_runtime/processed/separated/      Demucs vocal stems (only with --demucs)
  github_runtime/processed/translations/   subtitle-derived text
  github_runtime/metadata/                 metadata CSV from GitHub repo
  github_summary.json                      direct-run summary
  vad_labels/clean_wav/                    local normalized copy/check
  vad_labels/segments/                     VAD-cut speaking WAV segments
  vad_labels/labels.csv                    final segment labels
  vad_labels/labels.jsonl                  final segment labels
```

## Label audio already produced by the GitHub repo

If the GitHub repo has already produced WAV files in its normal location, skip crawl and only run local VAD/label:

```powershell
python scripts\run_vsf_github_to_labels.py `
  --skip-crawl `
  --processed-audio-dir VSF-audio-pipeline\data\processed\audio `
  --work-dir pipeline_runs\vsf_existing_audio `
  --refine-boundaries
```

For the local smoke test, this command was verified against `tmp/`:

```powershell
python scripts\run_vsf_github_to_labels.py `
  --skip-crawl `
  --processed-audio-dir tmp `
  --work-dir pipeline_runs\vsf_wrapper_smoke `
  --refine-boundaries `
  --overwrite
```

Result: 67 input WAV files produced 67 speech segment labels.

## Outputs

- `clean_wav/*.wav`: normalized audio ready for VAD and future training.
- `segments/*.wav`: one WAV file per detected speaking segment.
- `labels.csv`: tabular manifest for review and spreadsheet workflows.
- `labels.jsonl`: one JSON object per segment for downstream code.

Each label row contains:

```text
segment_id,label,source_file,cleaned_file,segment_file,start,end,duration
```

Currently `label` is `speaking`, because the pipeline cuts only speech segments. Quiet regions are still computed internally by `VAD/batch_vad.py` and can be exported later if needed.

## VAD defaults

The wrapper uses the local production-oriented defaults:

```text
threshold=0.7
min_volume=0.6
start_secs=0.1
stop_secs=0.45
merge_gap_secs=0.5
min_speech_secs=0.08
```

Use `--threshold`, `--min-volume`, and `--refine-boundaries` to tune the segmentation for crawled data quality.
