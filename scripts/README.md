# scripts/ — Entry Points Pipeline

## Map scripts → phase

| Script | Phase | Use case |
|---|---|---|
| `end_to_end_pipeline.py` | Phase 1–4 | Audio đã có sẵn trên disk → segments + labels |
| `run_vsf_github_to_labels.py` | Phase 0–4 | YouTube URL → crawl → segments + labels |
| `run_vsf_github_crawl.py` | Phase 0 | Chỉ crawl, không chạy VAD |
| `segment_youtube_audio_with_vad_transcript.py` | Phase 3–4 | WAV + VTT → sentence-aligned segments + transcript |
| `demucs_env.py` | Phase 1 | Helper: auto-resolve Demucs venv (không chạy trực tiếp) |

---

## Khi nào dùng script nào?

### Có audio rồi, muốn segment + label nhanh

```powershell
python scripts\end_to_end_pipeline.py `
  --raw-dir tmp `
  --work-dir pipeline_runs\my_run `
  --refine-boundaries
```

### Chưa có audio, muốn crawl YouTube + segment luôn

```powershell
Set-Content urls.txt "https://www.youtube.com/watch?v=VIDEO_ID"

python scripts\run_vsf_github_to_labels.py `
  --urls-file urls.txt `
  --batch-name batch_001 `
  --work-dir pipeline_runs\batch_001 `
  --refine-boundaries
```

### Crawl YouTube đã xong, chỉ muốn chạy VAD + transcript alignment

```powershell
python scripts\segment_youtube_audio_with_vad_transcript.py `
  --audio-dir external_repos\VSF-audio-pipeline\data\processed\audio `
  --vtt-dir external_repos\VSF-audio-pipeline\data\raw\youtube `
  --out-dir pipeline_runs\youtube_sentence_labels `
  --refine-boundaries
```

### Chỉ crawl, xử lý VAD sau

```powershell
python scripts\run_vsf_github_crawl.py `
  --urls-file urls.txt `
  --batch-name batch_001
```

---

## Tham số quan trọng chung

| Param | Default | Ý nghĩa |
|---|---|---|
| `--raw-dir` | `data/raw_audio` | Thư mục chứa audio input |
| `--work-dir` | `pipeline_runs/latest` | Thư mục output |
| `--refine-boundaries` | off | Energy-based boundary refinement (khuyên dùng) |
| `--overwrite` | off | Overwrite cache — dùng khi muốn chạy lại |
| `--no-demucs` | — | Bỏ qua Demucs vocal separation |
| `--threshold` | `0.7` | VAD threshold |
| `--min-volume` | `0.6` | Minimum volume |

---

## Import dependencies

Scripts import `batch_vad` từ `VAD/` qua `sys.path.insert`:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VAD_DIR = PROJECT_ROOT / "VAD"
sys.path.insert(0, str(VAD_DIR))
from batch_vad import VADModel, run_vad_file
```

> [!IMPORTANT]
> Chạy scripts từ project root (không phải từ trong `scripts/`):
> ```powershell
> # Đúng
> python scripts\end_to_end_pipeline.py --raw-dir tmp
>
> # Sai (path resolve sẽ lệch)
> cd scripts && python end_to_end_pipeline.py
> ```

---

## Environment

Dùng `.venv-vad` để chạy pipeline (không cần torch):

```powershell
.venv-vad\Scripts\python scripts\end_to_end_pipeline.py ...
```

Demucs tự resolve sang `.venv-demucs` / `.venv-demucs-cu128` (subprocess riêng).
