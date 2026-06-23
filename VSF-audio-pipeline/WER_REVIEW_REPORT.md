# Báo cáo Manual WER Review (tạm thời)

**Ngày:** 2026-06-23
**Phạm vi:** 3 video YouTube (nhạc/MV) đã review thủ công toàn bộ segment.

## Phương pháp

- **Hypothesis** = text label sinh từ phụ đề VTT của video.
- **Reference** = người nghe trực tiếp segment rồi gõ tay.
- WER đo **độ sai của LABEL VTT** so với tai người (KHÔNG phải đo ASR).
- `micro` = WER trọng số theo token (tổng edit distance / tổng token reference).
- `macro` = trung bình WER không trọng số trên từng segment.

## Kết quả

| Video | Batch | Segment | micro WER | macro WER | seg khớp 0% | seg lệch ≥50% |
|---|---|---|---:|---:|---:|---:|
| yzWeRtg7UVs | retest_yzWeRtg7UVs | 26 | 25.2% | 25.1% | 4 | 2 |
| neCmEbI2VWg | batch_001 | 26 | 36.6% | 35.8% | 1 | 4 |
| ixdSsW5n2rI | batch_004 | 42 | 23.7% | 22.2% | 14 | 3 |
| **Tổng** | 3 batch | **94** | **23.7–36.6%** | **~26.8%** | 19 | 9 |

(Tổng macro ≈ 26.8% = trung bình trên 94 segment.)

## Nhận xét

- Cả 3 đều là nhạc/MV. Label VTT sai khoảng **24–37% word** so với người nghe → phụ đề nhạc KHÔNG sạch.
- `neCmEbI2VWg` tệ nhất (36.6%, chỉ 1/26 segment khớp hoàn toàn).
- `ixdSsW5n2rI` tốt nhất (23.7%, 14/42 segment khớp hoàn toàn — gần 1/3 đúng tuyệt đối).
- **ASR WER gate (whisper base) over-flag rất mạnh trên nhạc:** trên yzWeRtg7UVs gate báo ~83% trong khi label thật chỉ sai 25%. → không tin được gate ASR để kết tội label trên nội dung hát.

## Hạn chế

- Mẫu nhỏ (3 video, đều là nhạc). Chưa có nội dung nói/podcast để so.
- Nhiều video khác **không tải được** (YouTube HTTP 403 — thiếu cookie `/app/cookies/youtube.txt`; proxy backup là placeholder). Báo cáo chỉ gồm video tải + review xong.
- `neCmEbI2VWg` nằm trong `batch_001` (default name) — nên đặt tên batch riêng mỗi video.

## Bước tiếp

- Thêm cookie YouTube thật → tải thêm video → mở rộng mẫu (gồm cả nội dung nói).
- Cân nhắc ASR tốt hơn `base` cho nhạc, hoặc tắt WER gate trên nội dung hát.
