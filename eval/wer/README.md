# eval/wer — Bộ test Manual WER cho label output

Đo **chất lượng label text** (WER/CER) của pipeline E2E so với **lyric gốc**, cho 3 video
ca nhạc test. Pure-Python (stdlib), **không cần cài gì**, chạy bằng Python hệ thống (3.12).

## Video target

| video_id | source | title | #seg |
|----------|--------|-------|------|
| `GGh0dfj2zfY` | vtt | Kimmese - Hương Ngọc Lan | 31 |
| `GjSi4OxJORY` | vtt | Kimmese - Loving You Sunny | 48 |
| `i724lraI93s` | asr | BỐN CHỮ LẮM - Trúc Nhân | 34 |

Hypothesis (label) đọc từ cột `text` của manifest
`external_repos/VSF-audio-pipeline/data/metadata/batch_001_segments.csv`.

## Quy trình 3 bước

```bash
# 1) Sinh worksheet chấm tay (chạy ngay được)
python eval/wer/build_worksheets.py
#    -> data/worksheets/<video_id>_worksheet.csv  (31/48/34 dòng)

# 2) Điền dữ liệu chuẩn (ground truth):
#    a. Dán full lyric mỗi bài vào  data/lyrics/<video_id>.txt
#    b. Mở worksheet, nghe wav_path từng đoạn, điền cột `reference`
#       = lời hát ĐÚNG của đoạn. Đoạn nhạc nền/quảng cáo -> để TRỐNG.
#       (đoạn không lời có thể ghi "âm thanh không có lời" -> coi như rỗng)

# 2b) (TÙY CHỌN) Đề xuất reference tự động để soát cho nhanh thay vì gõ trắng:
python eval/wer/propose_references.py        # map lyric->segment, ghi DRAFT vào worksheet
#    -> điền cột `reference` + `match_rate` (độ tin). PHẢI nghe & sửa, nhất là match_rate thấp.
#    Bỏ qua video đã điền tay. Chỉ tin cao khi hyp tốt + lyric không lặp lệch performance.

# 3) Chấm + sinh báo cáo
python eval/wer/score.py
#    -> reports/wer_report.md  +  reports/wer_detail_<video_id>.csv
```

`score.py` chạy được kể cả khi chưa đủ lyric/worksheet — phần thiếu đánh dấu `pending`,
không crash.

## Hai phép đo

- **doc-level**: gộp toàn bộ label 1 video → so full lyric → 1 con số WER/video.
- **segment (manual)**: từng đoạn so reference người nghe điền → micro-average (chỉ đoạn N>0).
  Đoạn lyric rỗng nhưng label phát token → nhóm **spurious** (đếm riêng, không chia 0).

## Hai mức chuẩn hóa (báo cáo song song)

- **normalized** (headline): bỏ markup `[âm nhạc]`/`[Vỗ tay]`/`>>` + cụm non-lyric trong
  `config/non_lyric.txt` (quảng cáo kênh, ad-lib), bỏ dấu câu, lowercase, **giữ dấu thanh**.
- **raw**: chỉ lowercase + bỏ dấu câu (giữ rác) — để thấy rác làm phồng WER bao nhiêu.

Token = âm tiết tách theo khoảng trắng (chuẩn WER tiếng Việt). WER = (S+D+I)/N.

## Cấu trúc

```
eval/wer/
  vsf_wer/        normalize.py  wer.py  io_manifest.py   (core, có test)
  config/         videos.txt  non_lyric.txt              (sửa được)
  data/lyrics/    <video_id>.txt   <- BẠN dán lyric
  data/worksheets/<video_id>_worksheet.csv  <- sinh ra, BẠN điền reference
  reports/        wer_report.md  wer_detail_<id>.csv     (sinh ra)
  build_worksheets.py   score.py
  tests/          test_wer.py  test_normalize.py
```

## Test

```bash
python -m pytest eval/wer/tests/ -q
```

Tinh chỉnh việc lọc rác: sửa `config/non_lyric.txt` (1 dòng = 1 cụm, cụm dài lọc trước).
