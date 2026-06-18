# Phase 4 — Label & Export (Segments + Manifest)

## Role trong pipeline

```
SpeechRegion list [{start, end}] + clean_wav/*.wav
  → cut WAV theo từng region
  → segments/*.wav
  → labels.csv + labels.jsonl
```

## Output format

### Thư mục output

```
<work-dir>/
  clean_wav/        WAV đã normalize (Phase 2 output)
  vocals/           Demucs vocal stems (Phase 1 output, nếu dùng Demucs)
  segments/         Một WAV file per speaking segment
  labels.csv        Manifest tabular
  labels.jsonl      Manifest JSON Lines
```

### Schema labels.csv / labels.jsonl

```
segment_id    : "<clean_stem>__seg0001"
label         : "speaking"  (luôn là speaking — pipeline chỉ cut speech)
source_file   : absolute path tới raw audio gốc
cleaned_file  : absolute path tới clean WAV
segment_file  : absolute path tới segment WAV
start         : float (seconds)
end           : float (seconds)
duration      : float (seconds)
```

> [!NOTE]
> `label` luôn là `"speaking"`. Quiet regions được tính nội bộ bởi `batch_vad.py` nhưng không xuất ra — có thể thêm sau nếu cần.

### Schema labels với transcript (YouTube + VTT pipeline)

Khi dùng `scripts/segment_youtube_audio_with_vad_transcript.py`:
```
audio_id, video_id, segment_id, segment_file, transcript_file,
start, end, duration, text, transcript_status, vad_status, source_wav, source_vtt
```

## Segment naming

```
<clean_stem>__seg<0001>.wav
```

Ví dụ: `yt_0-XhSWoz_wA__abc12345__seg0001.wav`

## WAV cutting

Dùng stdlib `wave` (không cần ffmpeg): frame-accurate cut từ clean WAV.

```python
# scripts/end_to_end_pipeline.py:cut_wav_segment()
with wave.open(src) as r:
    r.setpos(start_frame)
    frames = r.readframes(end_frame - start_frame)
with wave.open(dst, "wb") as w:
    w.writeframes(frames)
```

## Chạy transcript-aligned segmentation (YouTube + VTT)

```powershell
python scripts\segment_youtube_audio_with_vad_transcript.py `
  --audio-dir VSF-audio-pipeline\data\processed\audio `
  --vtt-dir VSF-audio-pipeline\data\raw\youtube `
  --out-dir pipeline_runs\youtube_sentence_labels `
  --refine-boundaries `
  --overwrite
```

Script này:
1. Scan WAV → map VTT theo `video_id`
2. Parse VTT (YouTube caption format, de-duplicate)
3. Tách thành sentence/phrase units (dấu câu + time gap)
4. Chạy VAD → align sentence với VAD regions
5. Cắt WAV + ghi `.txt` transcript
6. Ghi `labels.csv`, `labels.jsonl`, `audio_summary.csv`

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân | Chỗ fix |
|---|---|---|
| `segments/` rỗng | VAD trả về 0 regions | Xem Phase 3 — điều chỉnh threshold |
| Segment quá ngắn / nhiều quá | `min_speech_secs` quá thấp | Tăng `--min-speech-secs 0.5` |
| Segment bị cắt sai biên | boundary refinement | `--refine-boundaries` + điều chỉnh `--refine-*` |
| `labels.csv` thiếu cột `text` | Dùng pipeline basic (không có VTT) | Dùng `segment_youtube_audio_with_vad_transcript.py` |
| VTT parse sai, transcript lộn xộn | YouTube caption duplicate/overlap | Xem parser trong `segment_youtube_audio_with_vad_transcript.py` |

## Files liên quan

- `scripts/end_to_end_pipeline.py` — `run_vad_and_label()`, `cut_wav_segment()`, `write_manifest()`
- `scripts/segment_youtube_audio_with_vad_transcript.py` — pipeline transcript-aligned
- `scripts/run_vsf_github_to_labels.py` — wrapper cho full crawl path
