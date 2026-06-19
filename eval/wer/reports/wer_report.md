# Báo cáo WER — label output 3 video (pipeline E2E)

_Sinh tự động bởi `eval/wer/score.py` ngày 2026-06-19._

## 1. Dữ liệu

| video_id | source | #segment | title |
| --- | --- | --- | --- |
| GGh0dfj2zfY | vtt | 31 | Kimmese - Hương Ngọc Lan |
| GjSi4OxJORY | vtt | 48 | Kimmese - Loving You Sunny ft. Sunny |
| i724lraI93s | asr | 34 | BỐN CHỮ LẮM (MV) - TRÚC NHÂN - TRƯƠNG THẢO NHI |

Tổng **113 segment** / 3 video.

## 2. Phương pháp

- **WER** = (S+D+I)/N mức token (âm tiết tách theo space — chuẩn tiếng Việt); **CER** mức ký tự.
- **normalized** (headline): bỏ markup `[..]`/`>>` + cụm non-lyric (`config/non_lyric.txt`), bỏ dấu câu, lowercase, **giữ dấu thanh**.
- **raw**: chỉ lowercase + bỏ dấu câu (giữ rác) — để so độ phồng lỗi.
- **doc-level**: gộp toàn bộ label 1 video so full lyric. **segment**: từng đoạn so reference người nghe điền (micro-average, N>0).

## 3. WER toàn bài (doc-level: label gộp vs full lyric)

| video_id | source | N_ref | S/D/I (norm) | WER (norm) | CER (norm) | WER (raw) |
| --- | --- | --- | --- | --- | --- | --- |
| GGh0dfj2zfY | vtt | 166 | S84/D0/I131 | 129.5% | 92.4% | 142.6% |
| GjSi4OxJORY | vtt | 661 | S43/D31/I5 | 12.0% | 7.0% | 14.1% |
| i724lraI93s | asr | 344 | S93/D114/I7 | 62.2% | 54.5% | 87.3% |

_D (deletion) cao = label **không phủ hết** lời bài (bỏ đoạn / hát lặp không bắt); S (substitution) cao = **sai chữ** khi phiên âm. Doc-level trộn cả hai._

## 4. WER theo segment (manual, micro-average)

| video_id | source | #seg chấm | S/D/I (norm) | WER (norm) | WER (raw) | trượt 100% | spurious |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GGh0dfj2zfY | vtt | 31 | S134/D30/I36 | 69.0% | 70.7% | 1/26 | 3 (3 tok) |
| GjSi4OxJORY | vtt | 48 | S42/D44/I9 | 14.2% | 14.4% | 1/48 | 0 (0 tok) |
| i724lraI93s | asr | 34 | S28/D238/I24 | 65.2% | 64.7% | 9/20 | 2 (6 tok) |

_**trượt 100%** = segment có lời thật nhưng label 0 từ đúng → label sai hoàn toàn (dấu hiệu ASR hallucination). spurious = lời rỗng nhưng label phát token dư._

## 5. So sánh nguồn: VTT vs ASR

| nguồn | video | WER doc (norm) | WER seg (norm) |
| --- | --- | --- | --- |
| VTT | GGh0dfj2zfY,GjSi4OxJORY | 35.6% | 30.7% |
| ASR | i724lraI93s | 62.2% | 65.2% |

## 6. Ví dụ lỗi điển hình (alignment)

### GGh0dfj2zfY (vtt)

- `yt_GGh0dfj2zfY__sent000025`:

```
REF: *  *  *   *   *   *    *     chớm đông hoa thơm lụi    tàn  để gió mãi cuốn
HYP: gi xẽ đêm mai néu biết trước cháp đống hoa thầm ngườii tàng nề gi  mãi *   
     I  I  I   I   I   I    I     S    S        S    S      S    S  S       D   
```

- `yt_GGh0dfj2zfY__sent000006`:

```
REF: *  *    *   *  *   *    *   *   *    *   lan xòa bóng mát và vẫn hương thơm nơi ta
HYP: từ ngày nào em mới quên anh vẫn cành ngồ là  xòa bông ban và vẫn hướng thơm nơi ta
     I  I    I   I  I   I    I   I   I    I   S       S    S          S                
```

- `yt_GGh0dfj2zfY__sent000028`:

```
REF: * * *     *  * *     *  sẽ mãi mãi yêu anh là thế sẽ  mãi mãi
HYP: m c trong gi c trong gi em an  mới yêu anh là thế xem m   mơ 
     I I I     I  I I     I  S  S   S                  S   S   S  
```

### GjSi4OxJORY (vtt)

- `yt_GjSi4OxJORY__sent000023`:

```
REF: *    spend more time with me and you will see you will see we re  meant to be
HYP: just spend mo   time with me and *   *    *   u   will see we are meant to be
     I          S                     D   D    D   S               S              
```

- `yt_GjSi4OxJORY__sent000037`:

```
REF: không đủ mình sẽ phải cần thêm nhiều cà phê hơn vì đêm nay chúng ta sẽ không ngủ anh sẽ vặn ngược lại kim của đồng hồ để nó luôn chỉ vào thời khắc nửa đêm ta sẽ có ...
HYP: *     *  mình sẽ phải cần thêm nhiều cà phê hơn vì đêm nay chúng ta sẽ không ngủ anh sẽ vặn ngược lại kim của đồng hồ để nó luôn chỉ vào thời khắc nửa đêm ta sẽ có ...
     D     D                                                                                                                                                             ...
```

- `yt_GjSi4OxJORY__sent000027`:

```
REF: here s     my heart just take it everywhere you go destiny will bring me back to you for show oh  
HYP: *    heres my heart just take it everywhere u   go destiny will bring me back to you fo  sho  woah
     D    S                                      S                                        S   S    S   
```

### i724lraI93s (asr)

- `yt_i724lraI93s__sent000008`:

```
REF: từng ngày ta thôi còn trông ngóng trái tim thôi ngủ yên để từng đêm ta say triền miên để đêm nay ngừng trôi một mình anh nơi đây vẫn thao thức yêu lắm
HYP: *    *    *  *    *   *     *     *    *   *    *   *   *  *    *   *  *   *     *    *  *   *   *     *    *   *    *   *   *   *   *    *    *   hãy
     D    D    D  D    D   D     D     D    D   D    D   D   D  D    D   D  D   D     D    D  D   D   D     D    D   D    D   D   D   D   D    D    D   S  
```

- `yt_i724lraI93s__sent000015`:

```
REF: từng ngày ta thôi còn trông ngóng trái tim thôi ngủ yên để từng đêm ta say triền miên để đêm nay ngừng trôi một mình anh nơi đây vẫn thao thức yêu lắm
HYP: *    *    *  *    *   *     *     *    *   *    *   *   *  *    *   *  *   *     *    *  *   *   *     *    *   *    *   *   *   *   *    *    *   hãy
     D    D    D  D    D   D     D     D    D   D    D   D   D  D    D   D  D   D     D    D  D   D   D     D    D   D    D   D   D   D   D    D    D   S  
```

- `yt_i724lraI93s__sent000007`:

```
REF: ngày mai ai biết ra sao người có đi xa tận phương trời nắng trong mưa tìm nhau chờ một ngày yêu thương lả lơi nói cho nhau một câu để 
HYP: *    *   *  *    *  *   *     *  *  *  *   *      *    *    *     *   *   *    *   *   *    *   *      *  *   *   *   *    *   *   hãy
     D    D   D  D    D  D   D     D  D  D  D   D      D    D    D     D   D   D    D   D   D    D   D      D  D   D   D   D    D   D   S  
```

## 7. Kết luận (nháp tự động)

- **GGh0dfj2zfY** (vtt): WER 129.5% / CER 92.4% (raw WER 142.6%) — chủ yếu **dư** (I): label phát text ngoài lời → **phiên âm hỏng nặng (CER cao)**.
- **GjSi4OxJORY** (vtt): WER 12.0% / CER 7.0% (raw WER 14.1%) — chủ yếu **sai chữ** (S) → **tốt**.
- **i724lraI93s** (asr): WER 62.2% / CER 54.5% (raw WER 87.3%) — chủ yếu **thiếu phủ** (D): label bỏ/không bắt hết lời (lặp, đoạn trống) → **phiên âm hỏng nặng (CER cao)**.
- ⚠️ Doc-level trộn **chất lượng phiên âm** với **độ phủ** (bài hát lặp điệp khúc → D phồng). Verdict chất lượng cuối cùng dựa vào **segment-level** (cần điền worksheet).
- Nhóm doc-WER: VTT 35.6% vs ASR 62.2% — ⚠️ **gây hiểu lầm**, đừng dùng: gộp video chất lượng trái ngược; chất lượng phụ thuộc **loại caption**, không phải VTT-vs-ASR.
- **GGh0dfj2zfY** (segment): WER 69.0% — 1/26 segment sai hoàn toàn.
- **GjSi4OxJORY** (segment): WER 14.2% — 1/48 segment sai hoàn toàn.
- **i724lraI93s** (segment): WER 65.2% — ⚠️ **9/20 segment sai hoàn toàn** (0 từ đúng): dấu hiệu **ASR hallucination** (label = promo/boilerplate thay cho audio thật).
