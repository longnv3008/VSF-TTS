# VSF-TTS — Project Docs

AI/agent đọc file này trước. Sau đó mở phase doc liên quan khi cần debug hoặc hiểu sâu hơn.

---

## Pipeline E2E — Tổng quan

```
[YouTube URLs]
    │ Phase 0 — Crawl (audio + VTT subtitle)
    ▼
[raw audio: .wav/.webm/.mp4]
    │ Phase 1 — Demucs (auto: route by noise floor)
    │   noisy → vocal stem    |    clean → ffmpeg only
    ▼
[vocals.wav OR raw — voice source, native SR]
    │ Phase 2 — Clean / Normalize (loudnorm EBU R128)
    ▼
[clean_wav/*.wav — mono 16kHz 16-bit PCM]
    │ Phase 3 — VAD segmentation (Silero V6 ONNX)
    ▼
[SpeechRegion list: {start, end}]
    │ Phase 4 — Label & Export
    │   VTT subtitle? ── no ──> SKIP video (no ASR fallback)
    │            └─ yes: cut + align to subtitle text
    ▼
[segments/*.wav + labels.csv + labels.jsonl]
    │
    ├─ Phase 5 — Finetune VAD (offline, iterative)
    └─ Phase 6 — WER Evaluation (offline + optional in-pipeline WER gate: ASR vs VTT)
```

---

## Phase docs

| Phase | Thư mục | Tài liệu | Mô tả ngắn |
|---|---|---|---|
| **0 — Crawl** | `VSF-audio-pipeline/` | [phase-00-crawl.md](phase-00-crawl.md) | YouTube → raw audio qua VSF-audio-pipeline repo |
| **1 — Separate** | `.venv-demucs/`, `scripts/demucs_env.py` | [phase-01-separate.md](phase-01-separate.md) | Demucs vocal separation, venv setup, fallback logic |
| **2 — Clean** | `scripts/end_to_end_pipeline.py` | [phase-02-clean.md](phase-02-clean.md) | ffmpeg → mono 16kHz 16-bit WAV |
| **3 — VAD** | `VAD/` | [phase-03-vad.md](phase-03-vad.md) | Silero V6 ONNX, batch + Triton serving, params, bugs |
| **4 — Label** | `scripts/` | [phase-04-label.md](phase-04-label.md) | Cut WAV segments, manifest CSV/JSONL |
| **5 — Finetune** | `finetune/` · `finetune_asr/` | [phase-05-finetune.md](phase-05-finetune.md) · [finetune_asr/README.md](../finetune_asr/README.md) | VAD retrain (chưa deploy) + ASR LoRA finetune cho WER gate |
| **6 — Eval** | `eval/wer/` | [phase-06-eval.md](phase-06-eval.md) | WER/CER đo chất lượng transcript |

---

## Entry point scripts

| Script | Khi nào dùng |
|---|---|
| `scripts/end_to_end_pipeline.py` | Audio đã có sẵn → segments + labels |
| `scripts/run_vsf_github_to_labels.py` | YouTube URL → crawl → segments + labels |
| `scripts/run_vsf_github_crawl.py` | Chỉ crawl, không VAD |
| `scripts/segment_youtube_audio_with_vad_transcript.py` | WAV + VTT → sentence-aligned segments |

→ Xem chi tiết: [`scripts/README.md`](../scripts/README.md)

---

## Trạng thái dự án (2026-06-24)

### ✅ Hoàn thành & chạy ổn định

- VAD Triton Server (Silero V6 ONNX, Python backend, gRPC)
- Pipeline E2E: `end_to_end_pipeline.py` + `run_vsf_github_to_labels.py`
- Demucs vocal separation (auto route theo noise floor, raw fallback, env CPU/GPU)
- Segmentation theo word-timestamp: parser VTT word-level → gom câu
  (`words_to_sentence_units`), default on qua `segmentation_word_split`, fallback
  về cue khi thiếu word-timing; `SENTENCE_MAX_SEC=14`
- WER gate hardening (ASR vs VTT, off by default): VLSP normalize, **music-skip**
  (`music_detect.py`), **LLM judge** (`llm_judge.py`), windowed WER
  (`align_windowed` — đo trên span label, bỏ từ thừa do padding rìa)
- ASR LoRA finetune: `finetune_asr/` (augment, Optuna HPO, CT2 export) để hạ WER gate
- Human labelling: `audio-labelling/` (Label Studio — clone project, convert format)

### ⚠️ Chưa hoàn thành / còn mở

- **VAD finetune chưa deploy** — smoke run OK nhưng Detection@0.7 chưa beat baseline
- **ASR LoRA**: before/after WER trực tiếp còn deferred (cần chạy lại pipeline Docker)
- Dockerfile Triton còn dùng image `22.11` (cũ, 2022) — chưa upgrade 24.x
- `context` concatenation trong `vad.py` khác chuẩn Silero — chưa benchmark

---

## Tham số production VAD

```text
threshold        = 0.7
min_volume       = 0.6
start_secs       = 0.1
stop_secs        = 0.45
merge_gap_secs   = 0.5
min_speech_secs  = 0.08
refine_boundaries = True
```

---

## Môi trường (venvs)

| venv | Dùng cho | Cài đặt |
|---|---|---|
| `.venv-vad` | Pipeline chính (no torch) | `pip install -r VAD/requirements.txt` |
| `.venv-demucs` | Demucs CPU (torch 2.2.2 pinned) | `pip install -r requirements-demucs.txt` |
| `.venv-demucs-cu128` | Demucs GPU (torch 2.8, CUDA 12.8) | Xem [phase-01-separate.md](phase-01-separate.md) |

---

## Lịch sử kế hoạch & review

| File | Nội dung |
|---|---|
| [project_review.md](project_review.md) | Code review toàn bộ (2026-06-10): điểm mạnh/yếu, bugs, ưu tiên fix |
| [implementation_plan.md](implementation_plan.md) | Plan gốc: kiểm thử & cấu hình VAD Triton, debug file lỗi |
| [implementation_plan_2.md](implementation_plan_2.md) | Plan v2: xác nhận Silero V6, so sánh ONNX model |
| [youtube_vad_label_pipeline_plan.md](youtube_vad_label_pipeline_plan.md) | Plan: YouTube → VAD → align VTT → sentence labels |
| [task.md](task.md) | Checklist finetune (Phase 1–4 done) |
