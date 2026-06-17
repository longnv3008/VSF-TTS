# Báo cáo WER — chất lượng label 3 video test (pipeline E2E)

_Ngày 2026-06-17. Số liệu: `eval/wer/score.py`. Raw auto: [wer_report.md](wer_report.md);
per-segment: `wer_detail_<id>.csv`._

## 1. Mục tiêu & dữ liệu

Đo chất lượng **label text** pipeline sinh ra so với **lyric gốc**, 3 video ca nhạc — đã chấm
**đầy đủ doc-level + segment-level (manual, 100% segment, reference người nghe & soát)**.

| # | video_id | source | #seg | bài |
|---|----------|--------|------|-----|
| 1 | GGh0dfj2zfY | vtt | 31 | Kimmese — Hương Ngọc Lan |
| 2 | GjSi4OxJORY | vtt | 48 | Kimmese — Loving You Sunny |
| 3 | i724lraI93s | asr | 34 | Bốn Chữ Lắm — Trúc Nhân |

## 2. Phương pháp (tóm tắt)

WER=(S+D+I)/N mức token, CER mức ký tự. **normalized** (headline): bỏ markup, lọc cụm
non-lyric (quảng cáo + ad-lib lặp), bỏ dấu câu, giữ dấu thanh. **raw**: chỉ lowercase + bỏ dấu
câu. **doc-level** = gộp cả video vs full lyric; **segment** = từng đoạn vs reference người soát
(micro-average). Chi tiết: [README.md](../README.md).

## 3. Kết quả

### Doc-level (gộp toàn video)
| video | source | WER | CER | S/D/I |
|-------|--------|-----|-----|-------|
| GGh0dfj2zfY | vtt | 129.5% | 92.4% | S84/D0/I131 |
| GjSi4OxJORY | vtt | 12.0% | 7.0% | S43/D31/I5 |
| i724lraI93s | asr | 62.2% | 54.5% | S93/D114/I7 |

### Segment-level (manual — KẾT QUẢ CHÍNH)
| video | source | seg-WER | raw | S/D/I | **trượt 100%** | chế độ hỏng |
|-------|--------|---------|-----|-------|----------------|-------------|
| GGh0dfj2zfY | vtt | **69.0%** | 70.7% | **S134**/D30/I36 | 1/26 | chữ hỏng (corruption) |
| GjSi4OxJORY | vtt | **14.2%** | 14.4% | S42/D44/I9 | 1/48 | **sạch** |
| i724lraI93s | asr | **65.2%** | 64.7% | S28/**D238**/I24 | **9/20** | **hallucination** |

> **trượt 100%** = segment có lời thật nhưng label 0 từ đúng (label sai hoàn toàn). Chỉ số này
> phân biệt rõ 3 chế độ hỏng — xem mục 4.

## 4. Phát hiện then chốt — 3 chế độ hỏng KHÁC NHAU

Cùng WER ~65-69% nhưng nguyên nhân hoàn toàn khác, lộ qua S/D/I + "trượt 100%":

**① GGh0 (VTT auto-gen) — CHỮ HỎNG.** seg-WER 69%, **S áp đảo (S134)**, CER 92%, trượt chỉ 1/26.
Từ bị méo cấp ký tự nhưng vẫn đúng vị trí, gần như không đoạn nào sai 100%:
```
REF: ... lan xòa bóng mát và vẫn hương thơm nơi ta
HYP: ... là  xòa bông ban và vẫn hướng thơm nơi ta   ("cành ngồ"="cây ngọc", "bông ban"="bóng mát")
```
→ Dấu hiệu **phụ đề YouTube auto-generated** (ASR máy YT) kém: nghe ra âm gần đúng nhưng viết sai.

**② GjSi (VTT người) — SẠCH.** seg-WER 14.2%, S/D cân bằng, trượt 1/48. doc (12%) ≈ seg (14%)
→ nhất quán, KHÔNG phải ảo coverage. Label khớp lyric gần verbatim (Việt + Anh):
```
REF: spend more time with me and you will see ...
HYP: spend mo   time with me and ... (lỗi nhỏ: "more"→"mo", thiếu vài từ)
```
→ **caption chính chủ / người làm.** Chất lượng dùng được.

**③ i724 (ASR faster-whisper) — HALLUCINATION.** seg-WER 65.2%, **D áp đảo (D238)**, **9/20 segment
trượt 100%**. Whisper bịa boilerplate kênh YouTube VN đè lên đoạn HÁT:

| segment | audio thật (reference) | label (hypothesis) |
|---------|------------------------|--------------------|
| sent7 | "ngày mai ai biết ra sao, người có đi xa…" | "Hãy subscribe cho kênh **Ghiền Mì Gõ**…" |
| sent8 | "từng ngày ta thôi còn trông ngóng…" | "Hãy subscribe cho kênh Ghiền Mì Gõ…" |
| sent30 | "…sản phẩm mới nhất của anh Trúc Nhân…" | "Hãy subscribe cho kênh Ghiền Mì Gõ…" |

9/20 segment có lời = label promo bịa (sai 100%). ~11 segment còn lại ASR phiên âm **tốt** (WER
~24%, vài đoạn 0%). → ASR **nhị thể**: tốt khi rõ tiếng, **hallucinate trên nhạc/hát**.

## 5. Tổng hợp & cảnh báo so sánh

- Nhóm "VTT vs ASR" (doc 35.6% vs 62.2%, seg 30.7% vs 65.2%) **GÂY HIỂU LẦM** — đừng dùng: gộp
  GGh0-rác với GjSi-tốt rồi so ASR-bị-hallucinate. **Chất lượng quyết bởi LOẠI nguồn:**

| loại nguồn | ví dụ | chế độ hỏng | dùng được? |
|------------|-------|-------------|-----------|
| VTT auto-gen (YouTube) | GGh0 | chữ hỏng ~69% | ❌ loại |
| VTT người / chính chủ | GjSi | sạch ~14% | ✅ dùng (xác nhận nguồn lyric) |
| ASR faster-whisper | i724 | hallucination 45% segment | ⚠️ chỉ dùng sau khi lọc segment hỏng |

- **Doc-level đánh lừa:** i724 doc-WER trông như "thiếu phủ", nhưng segment-level lộ ra
  hallucination (chính bộ lọc promo che ở doc-level). → **QA phải chấm segment-level + theo dõi
  "trượt 100%"**, đừng tin mỗi doc-WER.

## 6. Kết luận & khuyến nghị

1. **GGh0 (VTT auto-gen): LOẠI.** Chữ hỏng pervasive ~69%, không cứu tự động.
2. **GjSi (VTT người): DÙNG ĐƯỢC** (~14% WER). Xác nhận lyric độc lập (không lấy từ chính caption).
3. **i724 (ASR): KHÔNG dùng nguyên trạng.** ~55% segment tốt nhưng 45% hallucination promo →
   phải **phát hiện & loại segment hỏng** trước khi đưa vào TTS:
   - Lọc segment có label khớp blocklist promo ("subscribe", "ghiền mì gõ", "la la school", "đăng ký kênh").
   - Cờ segment có label trùng y hệt nhau (dấu hiệu bịa lặp).
   - Bật `no_speech_threshold` cao / `condition_on_previous_text=False` / VAD-filter của faster-whisper.
4. **Pipeline:** phân biệt VTT người vs auto-gen (`writeautomaticsub`); ưu tiên caption người; ASR
   bắt buộc có bước hậu-kiểm hallucination.
5. **Quy trình QA:** luôn segment-level + chỉ số **"trượt 100%"** (phơi hallucination trực tiếp).

## 7. Hạn chế

- Reference segment do người soát (có hỗ trợ draft auto cho GGh0/GjSi qua `propose_references.py`);
  ranh giới đoạn có thể xê dịch ±vài từ → ảnh hưởng nhỏ tới WER tuyệt đối, không đổi kết luận.
- GjSi 14%: nên xác nhận nguồn lyric độc lập (nếu trùng caption → con số thấp giả nhẹ).
- Mẫu 3 video; mở rộng thêm video để vững thống kê theo từng loại nguồn.

---
_Phụ lục: [wer_report.md](wer_report.md) (bảng + alignment đầy đủ), `wer_detail_<id>.csv` (per-segment)._
