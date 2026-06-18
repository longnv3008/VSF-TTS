# Phase 2 — Clean / Normalize Audio

## Role trong pipeline

```
vocals.wav (native SR, từ Demucs)
  hoặc raw audio (nếu --no-demucs)
  → ffmpeg: mono, 16kHz, 16-bit PCM WAV
  → clean_wav/*.wav
  → Phase 3 (VAD)
```

## Chuẩn đầu ra bắt buộc

VAD (`batch_vad.py`) **chỉ đọc** mono 16-bit PCM WAV, 16kHz. Bất kỳ định dạng nào khác sẽ fail.

```
channels = 1      (mono)
sample_width = 2  (16-bit = 2 bytes)
frame_rate = 16000
```

## Format input hỗ trợ

`.wav .mp3 .m4a .aac .flac .ogg .opus .webm .mp4 .mkv`

Tất cả đều convert qua ffmpeg. WAV đã đúng chuẩn → copy trực tiếp (không re-encode, tránh quality loss).

## ffmpeg dependency

```powershell
# Kiểm tra
ffmpeg -version

# Cài nếu chưa có (Windows)
winget install ffmpeg
# hoặc download binary từ https://ffmpeg.org/download.html
```

## Logic clean trong code

File: `scripts/end_to_end_pipeline.py:clean_audio_files()`

```python
# Với Demucs: clean vocal stem, dùng raw làm source name
source_audio = vocal_map.get(src, src) if vocal_map else src

# Nếu đã đúng chuẩn → copy, không re-encode
if wav_is_clean(source_audio, 16000):
    shutil.copy2(source_audio, dst)
else:
    # ffmpeg -ac 1 -ar 16000 -sample_fmt s16
    convert_with_ffmpeg(source_audio, dst, 16000, "ffmpeg")

# Verify sau convert — raise nếu sai chuẩn
if not wav_is_clean(dst, 16000):
    raise ValueError(f"cleaned file is not mono 16k PCM WAV: {dst}")
```

## Output naming

Stable name dựa trên path tương đối + SHA1 digest (8 char) → tránh collision, reproducible:

```python
# stable_audio_name(src, raw_dir) → "subfolder__filename__<sha1[:8]>.wav"
```

## Output

```
<work-dir>/clean_wav/
  <stable_name>.wav    ← mono 16kHz 16-bit WAV, sẵn sàng cho VAD
```

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân | Chỗ fix |
|---|---|---|
| `ffmpeg not found` | ffmpeg chưa cài hoặc không trong PATH | Cài ffmpeg, hoặc dùng `--ffmpeg /path/to/ffmpeg` |
| `cleaned file is not mono 16k PCM WAV` | ffmpeg output lạ | Chạy ffmpeg thủ công để debug |
| File bị skip (cached) nhưng corrupt | `--overwrite` chưa set | Thêm `--overwrite` để re-clean |
| Convert thành công nhưng VAD cho 0 segment | Không phải clean phase bug — xem Phase 3 | Kiểm tra volume / threshold |

## Files liên quan

- `scripts/end_to_end_pipeline.py` — `clean_audio_files()`, `wav_is_clean()`, `convert_with_ffmpeg()`
- `scripts/end_to_end_pipeline.py` — `stable_audio_name()` (naming logic)
