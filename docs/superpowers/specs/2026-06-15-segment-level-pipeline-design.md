# Design: Segment-level Automation Pipeline (crawl → clean → VAD cắt câu → label)

**Ngày:** 2026-06-15
**Phạm vi sửa đổi:** `external_repos/VSF-audio-pipeline/backend`
**Trạng thái:** Approved design — sẵn sàng viết implementation plan

---

## 1. Mục tiêu

Biến pipeline trong `external_repos/VSF-audio-pipeline` thành automation hoàn chỉnh: sau khi
crawl 1 video YouTube, hệ thống tự động chạy và tạo ra **cặp audio–text cấp câu** dùng cho
dataset TTS/ASR tiếng Việt:

```
crawl video → clean WAV (16k mono) → VAD cắt từng câu → mỗi segment = audio_i + text_i
```

Mỗi segment là một câu nói được cắt từ audio gốc, kèm đúng lời thoại tiếng Việt của câu đó.

### Quyết định đã chốt (qua brainstorming)

| Chủ đề | Quyết định |
|---|---|
| Text mỗi segment | Lời thoại tiếng Việt (audio–text pairs), không dịch sang ngôn ngữ khác |
| Nguồn text | VTT-first, ASR fallback khi video thiếu/rỗng phụ đề |
| VAD chạy thế nào | Backend làm **client gọi Triton VAD server qua gRPC** |
| Scope | **Thay thế** full-video translation/metadata bằng output segment-level |
| Tổ chức code | Phương án C: 1 workflow node `segment_and_label` gồm các unit nhỏ test-riêng-được |
| Model ASR | `faster-whisper` (mặc định `large-v3`, cấu hình được), ẩn sau interface |
| Layout output | Per-video folder (segments + transcripts) + manifest CSV/JSONL |

---

## 2. Bối cảnh hệ thống hiện tại

Workflow LangGraph hiện tại (`application/workflow.py`):

```
validate_urls → crawl_audio → normalize_audio → build_translations → build_metadata
```

- `crawl_audio` (`pipeline_service.py`): tải `bestaudio` + phụ đề `vi` (vtt/json3) bằng `yt-dlp`,
  trả về row có `raw_file_path`, `subtitle_file_path`, `video_id`, `title`, `source_url`.
- `normalize_audio`: ffmpeg → `yt_<video_id>.wav` (mono, 16k, s16); xóa raw, **giữ** subtitle.
- `build_translations`: làm phẳng phụ đề cả video thành 1 file `.txt` (không có timestamp, không cắt câu).
- `build_metadata`: ghi CSV **1 row / video**.

Logic VAD + cắt câu + align transcript đã tồn tại offline ở
`scripts/segment_youtube_audio_with_vad_transcript.py` (import `VAD/batch_vad.py`). Việc cần làm là
**port logic đó vào backend** và **thay phần VAD in-process bằng client gRPC** tới Triton VAD server.

Triton VAD server (`VAD/`) là streaming turn-detection: gửi từng chunk audio kèm tham số, nhận
`SIGNAL` = `{signal_type: SPEAKING|QUIET, signal_at: <giây>}`. Protocol tham chiếu: `VAD/client.py`.

---

## 3. Workflow mới

```
validate_urls → crawl_audio → normalize_audio → segment_and_label → build_segment_metadata
```

- `validate_urls`, `crawl_audio`, `normalize_audio`: **giữ nguyên**.
- `build_translations`, `build_metadata`: **gỡ khỏi graph**.
- `segment_and_label` (mới): với mỗi video, sinh các segment WAV + TXT và trả `segment_rows`.
- `build_segment_metadata` (mới): gộp `segment_rows` → `labels.csv` + `labels.jsonl`.

`PipelineState` thêm field: `segment_rows: list[dict]`, `segments_manifest_path: str`. Bỏ
`translation_rows`, `translation_path` khỏi đường đi chính (giữ key trong TypedDict cũng được, nhưng
không node nào set nữa).

---

## 4. Kiến trúc module (phương án C)

Thư mục mới: `backend/app/modules/audio_pipeline/application/segmentation/`

| Unit (file) | Trách nhiệm | Input → Output | Nguồn |
|---|---|---|---|
| `types.py` | dataclass dùng chung | `TranscriptCue`, `SentenceUnit`, `SpeechRegion`, `SegmentRow` | mới (gom từ script) |
| `vtt_parser.py` | parse + de-dup WebVTT | `Path` → `list[TranscriptCue]` | port từ script offline |
| `sentence_grouper.py` | gom cue thành câu | `list[TranscriptCue]` → `list[SentenceUnit]` | port |
| `vad_grpc_client.py` | stream WAV qua Triton | `Path` → `(duration, list[SpeechRegion])` | **viết mới** |
| `aligner.py` | align câu ↔ VAD region | units + regions → `list[SegmentRow]` | port |
| `asr_adapter.py` | transcribe segment thiếu VTT | `Path` (wav) → `str` | **viết mới** (interface + impl) |
| `segment_writer.py` | cắt WAV + ghi TXT | row + src wav → file paths | port (`wave`-based) |
| `segment_service.py` | orchestrate 1 video | `processed_row` → `list[SegmentRow]` | mới |

Node `segment_and_label` chỉ gọi `AudioPipelineService` (method mới `segment_and_label(...)`),
method này lặp qua processed rows và gọi `segment_service` cho từng video. Giữ đúng quy ước repo
"1 node = 1 service method".

### Nguyên tắc ranh giới

- Mỗi unit thuần (parse/group/align/cut) **không** phụ thuộc mạng/Triton/ASR → test bằng dữ liệu tĩnh.
- `vad_grpc_client` và `asr_adapter` là 2 chỗ duy nhất chạm I/O ngoài → mock được trong test.
- `segment_service` ghép các unit; test bằng cách inject fake VAD client + fake ASR adapter.

---

## 5. VAD gRPC client (phần mới quan trọng nhất)

Thay `run_vad_regions` (in-process `batch_vad`) bằng client streaming theo đúng protocol `VAD/client.py`:

1. Mở WAV, bỏ 44 byte header. Chunk `chunk_ms=64` → `chunk_size = 64 * 16000 * 2 / 1000 = 2048` byte.
2. `sequence_id` = int ngẫu nhiên; `sess_id` = UUID. `sequence_start=True` ở chunk đầu, `sequence_end=True` ở chunk cuối (pad zero cho chunk cuối thiếu).
3. Mỗi chunk gửi input tensors: `INPUT` (int16), `SESSION` (bytes), `RATE` (int16), `THRESHOLD`, `VOLUME`, `START_SECS`, `STOP_SECS` (FP16).
4. Đọc `SIGNAL`; theo dõi state: `SPEAKING at t` → mở region tại `t`; `QUIET at t` → đóng region tại `t`. Nếu kết thúc file mà còn region mở → đóng tại `duration`.
5. Trả `(duration, list[SpeechRegion])`.

- Tham số production (cấu hình được): `threshold=0.7`, `min_volume=0.6`, `start_secs=0.1`, `stop_secs=0.45`.
- Dependency mới: `tritonclient[grpc]`. Lazy-import trong unit (giống cách repo lazy-import `yt_dlp`/`soundfile`) để API startup không cần lib worker.
- Server URL: config `vad_grpc_url` (mặc định `127.0.0.1:8001`).
- Lỗi kết nối Triton → raise lỗi đi theo pattern `BatchAbortError` (xem mục 9).

---

## 6. Transcript: VTT-first, ASR fallback

Per-video, quyết định đường đi:

- **Có VTT không rỗng** → đường VTT:
  `vtt_parser` → `sentence_grouper` → `vad_grpc_client` → `aligner` → `segment_writer`.
  `transcript_source = "vtt"`, `transcript_status = "ready"`.
- **Thiếu/rỗng VTT** → đường ASR:
  `vad_grpc_client` cắt speech region → mỗi region cắt WAV tạm → `asr_adapter` transcribe → ghi text.
  `transcript_source = "asr"`, `transcript_status = "ready"` (hoặc `"missing"` nếu ASR trả rỗng).

### asr_adapter

- Interface `AsrAdapter.transcribe(wav_path: Path) -> str`.
- Impl mặc định `FasterWhisperAdapter`:
  - Model id qua config `asr_model` (mặc định `large-v3`), device `asr_device` (`cuda`→fallback `cpu`).
  - Ngôn ngữ ép `vi`. Lazy-load model 1 lần, tái dùng giữa các segment.
- Chỉ khởi tạo khi thực sự có video đi đường ASR (đa số video có vi auto-caption → ASR hiếm chạy).

---

## 7. Output & manifest

```
data/processed/segments/<batch>/yt_<vid>/yt_<vid>__sent000001.wav
data/processed/segments/<batch>/yt_<vid>/yt_<vid>__sent000001.txt
...
data/metadata/<batch>_segments.csv
data/metadata/<batch>_segments.jsonl
```

- WAV gốc `data/processed/audio/yt_<vid>.wav` **giữ lại** làm nguồn truy vết.
- `build_segment_metadata` merge theo `segment_id` (idempotent khi chạy lại 1 video), giống cách
  `generate_metadata` hiện tại merge theo `audio_id`.

### Manifest schema (mỗi row)

```
audio_id, video_id, segment_id, segment_file, transcript_file,
start, end, duration, text, transcript_source, transcript_status,
vad_status, source_url, title
```

- `segment_id` = `yt_<vid>__sentNNNNNN`.
- `transcript_source` ∈ {`vtt`, `asr`}. `transcript_status` ∈ {`ready`, `missing`}.
- `vad_status` ∈ {`aligned`, `no_overlap`, `speech_region`} (giữ từ logic align hiện có).

---

## 8. Config / DB

### Config (`core/config.py`, đọc từ `.env`)

| Var | Mặc định | Ý nghĩa |
|---|---|---|
| `vad_grpc_url` | `127.0.0.1:8001` | địa chỉ Triton VAD server |
| `vad_threshold` / `vad_min_volume` / `vad_start_secs` / `vad_stop_secs` | `0.7 / 0.6 / 0.1 / 0.45` | tham số VAD |
| `segments_dir` | `data/processed/segments` | gốc output segment |
| `sentence_max_sec` / `sentence_min_sec` / `phrase_gap_sec` | `12 / 0.3 / 0.45` | luật tách câu |
| `segment_pad_sec` / `segment_min_sec` | `0.1 / 0.3` | padding & min độ dài segment |
| `asr_model` / `asr_device` | `large-v3` / `cuda` | cấu hình ASR fallback |

### DB (`domain/models.py`)

- Tận dụng cột sẵn có của `PipelineJob`:
  `manifest_path` / `output_path` = đường `labels.csv`; `metadata_path` = `labels.csv` (giữ tương thích `worker.py`); `translation_path` = `None`.
- **Không cần migration.** `worker.py` cập nhật để đọc `segments_manifest_path` từ state thay vì `metadata_path`/`translation_path` (đổi tối thiểu, giữ cùng tên cột DB).

---

## 9. Error handling & batch semantics

Theo đúng pattern hiện tại (`BatchAbortError` / `SkipUrlError`):

- Video **thiếu VTT** = bình thường, đi đường ASR — **không** phải lỗi.
- Lỗi không phục hồi được khi cắt/ASR/VAD 1 video → raise `BatchAbortError(step="segment_and_label", failed_url=..., remaining_urls=...)`.
- VAD region rỗng + VTT rỗng → video không sinh segment; ghi cảnh báo, đánh dấu, không abort.
- Triton server không kết nối được → `BatchAbortError` (cần server online; nêu rõ trong log + telegram như các step khác).

---

## 10. Testing (TDD)

**Unit (pytest, dữ liệu tĩnh, không mạng):**
- `vtt_parser`: de-dup caption chồng lặp; bỏ header/timestamp; encoding fallback.
- `sentence_grouper`: tách theo dấu câu, theo `phrase_gap_sec`, cắt câu quá dài `sentence_max_sec`, gộp câu quá ngắn.
- `aligner`: overlap → refine biên; no-overlap → giữ biên transcript; loại segment < `segment_min_sec`.
- `vad_grpc_client`: mock `client.infer` trả chuỗi SIGNAL → ráp đúng `SpeechRegion[]` + đóng region cuối.
- `asr_adapter`: fake transcribe; ép `language=vi`; load model 1 lần.
- `segment_writer`: cắt WAV bằng `wave` đúng số frame; ghi TXT utf-8.

**Integration smoke:**
- 1 WAV ngắn (vài giây, mono 16k) + 1 VTT giả → đường VTT: fake VAD client → ra ≥1 WAV+TXT+manifest row.
- 1 WAV ngắn, **không** VTT → đường ASR: fake VAD client + fake ASR → ra segment có `transcript_source=asr`.

---

## 11. Việc KHÔNG làm (YAGNI)

- Không dịch sang ngôn ngữ khác.
- Không tách ASR thành microservice riêng ở phase này (chỉ để sau interface `asr_adapter`).
- Không xây UI mới; frontend hiện tại không đổi (chỉ output dữ liệu khác).
- Không sửa logic crawl/normalize/proxy/cookie hiện có.
- Không thêm migration DB.

---

## 12. Acceptance criteria

1. Chạy 1 job 1 URL → tạo được folder segment per-video + `labels.csv`/`.jsonl`.
2. Video có vi auto-caption → segment text từ VTT, align VAD, `transcript_source=vtt`.
3. Video thiếu VTT → segment text từ ASR, `transcript_source=asr`, không crash.
4. Mỗi segment WAV có TXT tương ứng; manifest truy ngược được `video_id`/`source_url`.
5. VAD chạy qua Triton gRPC (không import `batch_vad` in-process trong backend).
6. Không còn output full-video translation/metadata trong graph mới.
7. Test unit + smoke pass.
