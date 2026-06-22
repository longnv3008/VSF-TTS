# Phase 6 — Evaluation (WER — Word Error Rate)

## Role trong pipeline

```
pipeline output: labels.csv (cột text = transcript)
  + ground truth: lyric gốc (điền tay) hoặc VTT subtitle
  → score.py → WER/CER report per video
  → reports/wer_report.md
```

Đây là component **standalone** — không phụ thuộc Phase 0–4. Dùng để đo chất lượng transcript sau khi pipeline đã chạy xong.

## In-pipeline WER gate (ASR vs VTT) — khác `score.py`

Tách biệt với offline `score.py` ở trên. WER gate là **QC trong pipeline**, không phải nguồn
label:

- Mặc định **tắt** (`WER_GATE_ENABLED`). Bật → mỗi segment giữ lại được transcribe bằng
  faster-whisper ASR, so với text VTT của nó.
- WER > `WER_GATE_MAX` (mặc định `0.05`) → flag `needs_review` (giữ nguyên text, không xóa).
- Token-WER tự chứa trong `wer_gate.py` (không phụ thuộc `eval/wer/`).
- Mục đích: bắt caption VTT lệch / sai align — **không** sinh hay sửa label.

Báo cáo WER chính thức (doc/segment-level) vẫn nằm ở `eval/wer/` (bên dưới).

## Thư mục

```
eval/wer/
  vsf_wer/        Core library: normalize.py, wer.py, io_manifest.py
  config/         videos.txt (target videos), non_lyric.txt (cụm lọc)
  data/
    lyrics/       <video_id>.txt — BẠN dán lyric gốc vào đây
    worksheets/   <video_id>_worksheet.csv — sinh ra, BẠN điền reference
  reports/        wer_report.md, wer_detail_<id>.csv (sinh ra)
  build_worksheets.py
  propose_references.py
  score.py
  tests/
```

## Video target hiện tại

| video_id | Nguồn transcript | Title |
|---|---|---|
| `GGh0dfj2zfY` | VTT subtitle | Kimmese - Hương Ngọc Lan |
| `GjSi4OxJORY` | VTT subtitle | Kimmese - Loving You Sunny |
| `i724lraI93s` | ASR (lịch sử) | BỐN CHỮ LẮM - Trúc Nhân |

> [!NOTE]
> `i724` cột "ASR" là di sản: ASR **không còn** feed label vào pipeline (Phase 4 chỉ
> nhận VTT). Giữ làm eval target lịch sử + reference cho WER gate.

## Quy trình

```bash
# 1. Sinh worksheet để điền tay
python eval/wer/build_worksheets.py
# → data/worksheets/<video_id>_worksheet.csv

# 2a. (Tùy chọn) Auto-propose references từ lyric
python eval/wer/propose_references.py
# → điền DRAFT vào worksheet, PHẢI nghe + sửa (nhất là match_rate thấp)

# 2b. Điền tay: mở worksheet, nghe wav_path, điền cột `reference`
#     Đoạn nhạc nền → để TRỐNG

# 3. Chấm điểm
python eval/wer/score.py
# → reports/wer_report.md + reports/wer_detail_<id>.csv
```

Không cần cài gì — pure Python stdlib. Chạy bằng Python system (3.10+).

## Hai phép đo

- **doc-level**: gộp toàn bộ label 1 video → so với full lyric → 1 WER/video
- **segment (manual)**: từng segment so với reference người nghe điền → micro-average

## Chuẩn hóa

- **normalized** (headline): bỏ markup `[âm nhạc]`/`[Vỗ tay]`/`>>` + non-lyric trong `config/non_lyric.txt`, bỏ dấu câu, lowercase, **giữ dấu thanh**
- **raw**: chỉ lowercase + bỏ dấu câu — thấy rác làm phồng WER bao nhiêu

Token = âm tiết tách theo khoảng trắng (chuẩn WER tiếng Việt).

## Manifest input

Hypothesis (label text) đọc từ:
```
VSF-audio-pipeline/data/metadata/batch_001_segments.csv
```
Cột `text` = transcript từ pipeline.

## Test

```bash
python -m pytest eval/wer/tests/ -q
```

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân | Chỗ fix |
|---|---|---|
| `pending` trên nhiều video | Chưa điền lyric / worksheet | Dán lyric vào `data/lyrics/<id>.txt`, điền worksheet |
| WER rất cao (>50%) | Transcript chứa rác (nhạc nền bị transcribe) | Cập nhật `config/non_lyric.txt` |
| `propose_references.py` map sai | Lyric lặp, performance khác lyric | Nghe + sửa tay các dòng `match_rate` thấp |
| `score.py` crash | Manifest CSV thiếu cột `text` | Dùng pipeline có transcript (Phase 4 với VTT) |
