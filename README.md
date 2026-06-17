# VSF-TTS

Vietnamese TTS **data pipeline** for VSF (Vin Smart Future).
Turns raw / crawled audio into clean, labeled speech segments ready for TTS training.

```text
YouTube / raw audio
   → Demucs (vocal separation)
   → clean (mono 16 kHz 16-bit WAV)
   → VAD (speech segmentation)
   → labels.csv / labels.jsonl
```

---

## Pipeline

| Stage | What it does |
|-------|--------------|
| **Crawl** | Download audio + subtitles from YouTube via the `VSF-audio-pipeline` repo |
| **Demucs** | Separate **vocals** from background music (on by default, raw fallback) |
| **Clean** | Downsample vocal stem → mono 16 kHz 16-bit PCM WAV |
| **VAD** | Silero-based VAD cuts speaking segments |
| **Label** | Emit one row/segment: `segment_id,label,source_file,...,start,end,duration` |

Demucs runs on full-quality raw audio; only the vocal stem is downsampled and fed
into VAD, so segments are clean speech (better for TTS).

## Repo layout

```text
scripts/        end-to-end pipeline wrappers (entry points)
VAD/            Silero VAD model + batch segmentation + Triton serving (Dockerfile)
finetune/       finetune Silero VAD on Vietnamese data (energy-aware)
eval/wer/       WER evaluation tooling
docs/           design specs + plans
PIPELINE.md     full pipeline reference
CLAUDE.md       project + style instructions
```

Not tracked (see [.gitignore](.gitignore)): virtualenvs, `external_repos/` (separate
git repo), `pipeline_runs/` output, datasets (`finetune/data*`), logs. Small model
artifacts (`*.onnx`, `*.pth`) **are** committed so the pipeline runs after clone.

## Environments

Three isolated venvs (heavy deps kept apart):

| venv | Purpose | Install |
|------|---------|---------|
| `.venv-vad` | VAD + pipeline (no torch) | `pip install -r VAD/requirements.txt` |
| `.venv-demucs` | Demucs CPU (torch 2.2.2 pinned) | `pip install -r requirements-demucs.txt` |
| `.venv-demucs-cu128` | Demucs GPU (torch 2.8, CUDA 12.8) | torch cu128 wheel + `demucs>=4.0` |

> Torch pins matter: torchaudio ≥ 2.9 routes through torchcodec and breaks Demucs;
> NumPy 2.x breaks torch 2.2.x. Keep `numpy<2`, `torch==2.2.2` for the CPU env.

## Quickstart

### Audio already downloaded

```powershell
python scripts\end_to_end_pipeline.py `
  --raw-dir tmp `
  --work-dir pipeline_runs\my_run `
  --refine-boundaries
```

Accepts `.wav .mp3 .m4a .aac .flac .ogg .opus .webm .mp4 .mkv`.

### Full crawl → labels

```powershell
Set-Content urls.txt "https://www.youtube.com/watch?v=VIDEO_ID"

python scripts\run_vsf_github_to_labels.py `
  --urls-file urls.txt `
  --batch-name batch_001 `
  --work-dir pipeline_runs\batch_001 `
  --refine-boundaries
```

Add `--cookie-file <youtube.txt>` for age/region-gated videos.
Disable separation with `--no-demucs`; point a torch env via `--demucs-cmd`,
`--demucs-device cuda` for large batches.

### Outputs

```text
<work-dir>/
  clean_wav/      normalized WAV (VAD-ready)
  segments/       one WAV per speaking segment
  labels.csv      tabular manifest
  labels.jsonl    one JSON object per segment
```

## VAD defaults

```text
threshold=0.7   min_volume=0.6   start_secs=0.1   stop_secs=0.45
merge_gap_secs=0.5   min_speech_secs=0.08
```

Tune with `--threshold`, `--min-volume`, `--refine-boundaries`.

## Finetune & eval

- Finetune Silero VAD on Vietnamese data → [finetune/README.md](finetune/README.md)
- WER evaluation → [eval/wer/README.md](eval/wer/README.md)

## Docs

- [PIPELINE.md](PIPELINE.md) — full end-to-end reference
- [VAD/README.md](VAD/README.md) — VAD model + serving
