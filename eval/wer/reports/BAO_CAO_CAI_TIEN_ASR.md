# Báo cáo cải tiến chất lượng label ASR — chống ảo giác (hallucination)

_Ngày 2026-06-18. Phạm vi: nhánh `asr-text-hardening` + vá gap blocklist promo-substring._

## 1. Vấn đề (đo trước cải tiến)

Pipeline nguồn ASR (faster-whisper) **bịa boilerplate kênh YouTube** đè lên đoạn HÁT và đoạn
nhạc/intro. Video test `i724lraI93s` (Bốn Chữ Lắm — Trúc Nhân), 34 segment: **24/34 label là rác**
nhưng pipeline vẫn đánh dấu `transcript_status=ready`.

Hai loại rác:
- **Poison** (nguy hiểm nhất): 9 segment có lời hát thật → label = `"Hãy subscribe cho kênh Ghiền
  Mì Gõ Để không bỏ lỡ những video hấp dẫn"`. Text sai 100% nhưng audio là giọng hát → nếu đưa vào
  TTS sẽ dạy model sai hoàn toàn.
- **Spurious**: đoạn nhạc/lặng → label promo (`"Hãy đăng ký kênh để ủng hộ kênh của mình nhé."`) hoặc
  ad-lib (`"NAN NAN NAN NAN"`, `"Nên là"`).

## 2. Công nghệ / thay đổi đã thêm

Module `text_quality.py` (pure stdlib) — 3 lớp lọc + chuẩn hóa VLSP, áp cho cả backend service lẫn
script crawl:

| # | lớp | cơ chế | tham số |
|---|---|---|---|
| 1 | **reject-by-prob** | loại nếu `no_speech_prob > 0.6` **VÀ** `avg_logprob < -1.0` | `ASR_NO_SPEECH_THRESHOLD`, `ASR_LOGPROB_MIN` |
| 2a | **blocklist (exact)** | khớp TOÀN BỘ cụm ảo giác → rỗng | `_BLOCKLIST_PHRASES` |
| 2b | **promo-substring** _(mới — vá gap)_ | CHỨA cụm promo đặc trưng (`đăng ký kênh`, `ghiền mì gõ`, `bỏ lỡ những video`...) → rỗng, kể cả khi có chữ thừa quanh | `_PROMO_SUBSTRINGS` |
| 3 | **anti-repetition** | 1 token lặp > 10 lần → rỗng | `repetition_limit` |
| + | **VLSP normalize** | gộp acronym đánh vần, giữ tên riêng EN, giữ dấu thanh | — |

**Gap đã vá:** blocklist (2a) khớp exact nên **bỏ lọt** hallucination i724 (`"Hãy subscribe ... Để
không bỏ lỡ..."` có đuôi thừa). Thêm lớp **promo-substring (2b)**: các cụm promo đủ đặc trưng để khớp
substring an toàn (không xuất hiện trong lời hát/nói thật). Áp đủ 3 call site: ASR (`clean_transcript`),
VTT (`segment_service`), script crawl. Test: +5 test mới, **toàn suite 93 pass**.

## 3. Kết quả: cải thiện bao nhiêu? (ĐO THẬT)

Áp `clean_transcript` đã vá lên chính label đã lưu của i724 (lớp text-quality tất định trên text →
before/after thật, không cần re-run ASR). Script: [`measure_hardening.py`](../measure_hardening.py).

| chỉ số | BEFORE | AFTER | đổi |
|---|--:|--:|---|
| usable label (pipeline phát `ready`) | 34 | 15 | −19 rác bị loại |
| **poison** (lời thật nhưng label sai 100%) | **9** | **0** | **−100%** |
| spurious (rác trên đoạn không lời) | 14 | 4 | −71% |
| **precision label usable** (label phát ra có ≥1 từ đúng) | **29.4%** | **66.7%** | **+37 điểm (×2.3)** |
| seg-WER **của label GIỮ LẠI** | 65.2% | **24.8%** | −40 điểm |

9 poison segment bị diệt: sent 7, 8, 15, 17, 19, 22, 30, 31, 33.

**Đọc số cho đúng:**
- Cải tiến lõi = **loại sạch 9/9 label poison** + ~10 promo trên đoạn nhạc. Corpus label dùng được từ
  71% rác → 33% rác.
- `seg-WER của label giữ lại` 65.2% → 24.8% là **chất lượng phần DATA TA THỰC SỰ DÙNG** (sau khi vứt
  segment bị loại). ⚠️ KHÔNG phải seg-WER kiểu cũ trên toàn bộ reference: nếu chấm theo
  `score.py` (giữ segment rỗng = deletion), con số ~65% gần như không đổi — vì với metric đó, label
  rỗng và label bịa đều = "thiếu phủ". Hardening đổi **rác độc → đánh dấu bỏ**, không phải sửa được lời.

## 4. Hạn chế & việc còn lại

- **Chưa đo reject-by-prob live.** Win ở trên do lớp **promo-substring (text)** mang lại — đủ diệt
  toàn bộ poison của video này. reject-by-prob (cần `no_speech_prob`/`avg_logprob` live) chỉ verify
  được khi re-run pipeline Docker (Docker đang tắt + faster-whisper GPU-only trên máy này).
- **Mất coverage:** 9 segment hát thật bị bỏ (audio tốt nhưng ASR không phiên âm nổi). Chấp nhận với
  TTS (thà thiếu còn hơn nhãn sai); muốn cứu thì cần ASR mạnh hơn cho đoạn hát.
- **4 spurious còn sót** (`"Nên là"`, `"nan nan nan nan"`...): không phải promo. Hạ `repetition_limit`
  hoặc mở rộng seed để dọn tiếp.

## 5. Tóm tắt 1 dòng

Vá gap blocklist (thêm lớp promo-substring) → **diệt 9/9 label poison**, precision label dùng được
**29.4% → 66.7%**, WER của data giữ lại **65.2% → 24.8%** (đo thật trên i724, 93 test xanh). reject-by-prob
chờ re-run pipeline để verify live.

---
_Nguồn số: [`measure_hardening.py`](../measure_hardening.py), [BAO_CAO_WER.md](BAO_CAO_WER.md),
`wer_detail_i724lraI93s.csv`. Research: `Toi_Uu_Hoa_Luong_ASR_SER_Vietnamese.md`._
