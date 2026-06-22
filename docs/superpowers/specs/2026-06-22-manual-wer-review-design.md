# Manual WER Review cho needs_review segments — Design

> Date: 2026-06-22
> Status: approved (brainstorming) → next: implementation plan
> Pipeline role: review tool, off the main ingest path. Additive, opt-in.

## Vấn đề

WER gate hiện flag segment bằng ASR (whisper `base`) vs VTT. ASR tự nó không tin
được (nhất là nhạc hát) → `wer_gate>0.3` cho biết "lệch" nhưng KHÔNG cho biết label
VTT đúng hay sai bao nhiêu %. Cần con người nghe + điền lời đúng (reference) để tính
**WER thật** của label.

## Mục tiêu

Người review nghe wav từng segment `needs_review` trên dashboard → gõ reference
(lời đúng nghe được) → backend tính WER canonical giữa label `text` (hypothesis) và
reference → lưu vào metadata file → hiện %WER per-segment + tổng hợp batch.

Non-goals: không sửa flow ingest/pipeline chính; không build review DB table (lưu ở
metadata file); không tự động đề xuất reference (đó là việc của eval/wer offline).

## Ngữ nghĩa WER

- **hypothesis** = cột `text` của segment (label VTT mà pipeline giữ).
- **reference** = lời đúng người review gõ.
- `manual_wer = (S + D + I) / N_ref`, N = số token reference, sau normalize chuẩn VN.
- Normalize (level `normalized`): NFC → lowercase → strip markup `[âm nhạc]`/`>>` →
  bỏ dấu câu → gom whitespace → bỏ run ad-lib ≥2 token. **Giữ dấu thanh** (phonemic).
- ref rỗng nhưng hyp có token → **spurious** (label phát dư): đếm riêng, KHÔNG chia 0.
- **Batch headline** = micro-average WER = Σ errors / Σ N trên các segment đã review
  có N>0. Spurious đếm thành 1 nhóm riêng.

## Kiến trúc — 4 thành phần

### 1. WER core port (backend)

File mới: `backend/app/modules/audio_pipeline/application/segmentation/wer_canonical.py`

Port từ `eval/wer/vsf_wer/` (pure stdlib, KHÔNG import chéo — backend là uv project riêng):
- `normalize(text, *, level="normalized", non_lyric=None, keep_diacritics=True)` (từ `normalize.py`)
- `align(ref, hyp) -> Counts` + `Counts` (sub/dele/ins/cor/n_ref, `.errors`, `.wer`, `.spurious`) (từ `wer.py`)
- `micro_average(counts_list)`
- `tokens(text)` = `text.split()`

`non_lyric` optional, mặc định `None` (YAGNI — chưa cần blocklist trong vòng review;
có thể thêm sau bằng cách đọc `eval/wer/config/non_lyric.txt`).

Test: mirror subset của `eval/wer/tests/test_wer.py` + `test_normalize.py` (sub/del/ins,
spurious N=0, markup strip, ad-lib collapse, giữ dấu thanh).

### 2. Metadata — 3 cột mới

Thêm vào segment metadata (`<batch_name>_segments.csv` + `.jsonl`):
- `reference` (str, default `""`)
- `manual_wer` (float|str, default `""` khi chưa review)
- `review_status` (`pending` | `reviewed` | `skipped`, default `pending` cho segment
  có `quality_label=needs_review`; các segment khác cũng `pending` nhưng UI chỉ liệt kê needs_review)

Sửa:
- `build_segment_metadata` ([pipeline_service.py](../../../VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/pipeline_service.py)):
  thêm 3 field vào `fieldnames`.
- **Merge-preserve khi re-run**: hiện merge theo `segment_id` rồi
  `{key: row.get(key, "") for key in fieldnames}` → segment_rows từ pipeline KHÔNG có
  cột review nên sẽ ghi trắng. Fix: khi build row mới cho 1 `segment_id` đã có trong
  `existing`, carry-over `reference`/`manual_wer`/`review_status` từ row cũ.

Test: re-run pipeline cùng segment_id giữ nguyên reference/manual_wer đã điền.

### 3. Backend API (router audio-pipeline)

- `GET /audio-pipeline/batches/{batch_name}/segments?status=needs_review`
  → đọc metadata jsonl của batch, lọc theo `quality_label` (mặc định `needs_review`),
  trả list: `segment_id`, `text` (hyp), `reference`, `manual_wer`, `review_status`,
  `start`, `end`, `duration`, `quality_reasons`, `segment_file` (để build audio URL).

- `GET /audio-pipeline/segments/audio?file=<segment_file>`
  → `FileResponse` stream wav. **Validate**: resolve path phải nằm trong `segments_dir`
  (chống path traversal). 404 nếu không tồn tại.

- `POST /audio-pipeline/segments/{segment_id}/review` body `{ "reference": str, "batch_name": str }`
  → tính `manual_wer = align(tokens(normalize(reference)), tokens(normalize(text))).wer`
  (spurious → trả flag riêng, manual_wer = null), set `review_status="reviewed"`
  (hoặc `"skipped"` nếu reference rỗng + có nút skip), ghi lại metadata csv+jsonl
  (rewrite full file, merge theo segment_id), trả row đã cập nhật.

- `GET /audio-pipeline/batches/{batch_name}/wer-summary`
  → micro-avg WER trên segment `reviewed` N>0 + counts: `reviewed`, `total_needs_review`,
  `spurious`, `pending`.

Lưu ý: key theo `batch_name` (metadata file đặt tên theo batch_name). `segment_id` là
unique global. Ghi file rewrite toàn bộ mỗi lần save — chấp nhận được (review 1 người,
batch cỡ chục–trăm segment). Schemas Pydantic mới trong `api/schemas.py`.

### 4. Frontend — feature review

`frontend/src/features/review/`:
- `api/review.ts`: `listSegments(batchName)`, `submitReview(segmentId, batchName, reference)`,
  `getWerSummary(batchName)`, `audioUrl(segmentFile)`.
- `components/ReviewPanel.tsx`: chọn batch (dropdown từ `/batches`) → list segment
  needs_review; mỗi dòng: nút play (`<audio src=audioUrl>`), text hyp, ô input reference,
  nút Save, badge `manual_wer`. Header: batch WER summary (micro-avg, reviewed/total, spurious).
- Gắn vào `pages/dashboard/DashboardPage.tsx` thành section/tab mới (không phá layout cũ).

## Data flow

```
chọn batch → GET segments?status=needs_review → render list
  → reviewer play wav (GET segments/audio) → gõ reference → Save
  → POST segments/{id}/review → backend normalize+align → ghi metadata → trả manual_wer
  → FE cập nhật dòng + GET wer-summary (refresh header)
```

## Error handling

- metadata file batch không tồn tại → 404.
- audio file mất / path ngoài segments_dir → 404 / 400.
- reference rỗng + hyp có token → spurious (manual_wer null, đếm riêng), không lỗi.
- reference rỗng + hyp rỗng → review_status reviewed, WER N/A.
- Ghi file lỗi (lock/IO) → 500 với `AudioPipelineError` (theo handler hiện có).

## Testing

- Backend unit: `wer_canonical` (mirror eval/wer tests subset).
- Backend API: list / audio (valid + traversal block) / review (sub-del-ins, spurious,
  empty) / summary, dùng metadata file tạm.
- Merge-preserve: re-run giữ review columns.
- Frontend: tối thiểu — ReviewPanel render list, Save gọi API (nếu repo có FE test harness;
  nếu chưa có thì bỏ, không dựng mới).

## Slices (vertical, additive, off main path)

1. Port `wer_canonical` + test. (độc lập, an toàn)
2. Metadata 3 cột + merge-preserve + test.
3. API list/audio/review/summary + schemas + test.
4. FE ReviewPanel + api client, gắn dashboard.

Mỗi slice giữ build xanh + test cũ pass. Mặc định an toàn: flow needs_review/ingest
không đổi, cột review default rỗng/pending.

## Open decisions đã chốt

- Lưu trữ: **ghi cột vào metadata file** (không DB table).
- Metric: **canonical eval/wer** (port vào backend).
- UI: **frontend dashboard**.
- Audio serve: **theo path file** + validate trong segments_dir.
- Nút **skip** cho đoạn nhạc nền/không lời (review_status=skipped, reference rỗng).
