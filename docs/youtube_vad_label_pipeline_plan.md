# Plan: Pipeline Crawl -> Clean -> VAD Cat Cau -> Label

## Muc Tieu

Xay dung pipeline dau cuoi:

```text
crawl YouTube
-> clean WAV
-> map audio_id voi transcript VTT
-> VAD phat hien vung speech
-> cat theo tung cau / phrase
-> gan transcript tuong ung
-> xuat audio con + transcript + manifest
```

## Output Mong Muon

Voi moi file:

```text
data/processed/audio/yt_<video_id>.wav
data/raw/youtube/<video_id>__title.vi.vtt
```

se tao:

```text
pipeline_runs/youtube_sentence_labels/
  segments/
    yt_<video_id>/
      yt_<video_id>__sent000001.wav
      yt_<video_id>__sent000002.wav
  transcripts/
    yt_<video_id>/
      yt_<video_id>__sent000001.txt
      yt_<video_id>__sent000002.txt
  labels.csv
  labels.jsonl
  audio_summary.csv
  missing_transcripts.csv
```

Moi dong label nen co:

```text
audio_id, video_id, segment_id, segment_file, transcript_file,
start, end, duration, text, transcript_status, vad_status, source_wav, source_vtt
```

## Plan Thuc Hien

### 1. Chuan hoa audio_id mapping

Quy uoc map hien tai:

- WAV: `yt_0-XhSWoz_wA.wav`
- VTT: `0-XhSWoz_wA__title.vi.vtt`
- Metadata: `audio_id=yt_0-XhSWoz_wA`, `video_id=0-XhSWoz_wA`

Logic mapping:

```text
audio_id = filename stem cua WAV
video_id = audio_id bo prefix "yt_"
vtt = file trong raw/youtube bat dau bang "{video_id}__" va ket thuc ".vtt"
```

Neu khong co VTT hoac VTT trong, van xu ly VAD nhung danh dau:

```text
transcript_status=missing
```

### 2. Parse va clean transcript VTT

Can parser rieng cho YouTube `.vtt` vi file co nhieu tag kieu:

```text
<00:00:02.760><c> quy</c>
```

Parser se:

- Doc WebVTT cue `start --> end`.
- Bo header `WEBVTT`, `Kind`, `Language`.
- Bo tag timestamp, `<c>`, HTML tag.
- Xu ly duplicate do YouTube auto-caption lap lai dong truoc.
- Chuan hoa whitespace.
- Giu timestamp cho tung cue hoac tung phrase.
- Bo cue rong.

Output trung gian:

```python
TranscriptCue(
    start=2.48,
    end=4.99,
    text="thua quy vi va cac ban ..."
)
```

### 3. Tach transcript thanh sentence/phrase units

Vi YouTube caption khong phai luc nao cung tach dung cau, can rule thuc te:

- Neu co dau cau `. ? ! ...` thi gom cue thanh sentence.
- Neu khong co dau cau, tach theo pause/time gap, vi du `gap >= 0.45s`.
- Gioi han do dai cau, vi du `max_sentence_sec=12s`, de tranh segment qua dai.
- Gioi han toi thieu, vi du `min_sentence_sec=0.3s`, de tranh segment vun.

Output:

```python
SentenceUnit(
    start=12.3,
    end=18.6,
    text="..."
)
```

### 4. Chay VAD cho tung audio_id

Tan dung lai code hien co trong `VAD/batch_vad.py`, khong viet lai model.

Tham so mac dinh nen dung theo pipeline hien tai:

```text
threshold=0.7
min_volume=0.6
start_secs=0.1
stop_secs=0.45
merge_gap_secs=0.5
min_speech_secs=0.08
refine_boundaries=true
```

Output VAD trung gian:

```python
SpeechRegion(start=12.1, end=18.9)
```

### 5. Align transcript sentence voi VAD region

Day la phan quan trong nhat.

Voi moi `SentenceUnit` tu VTT:

- Tim cac VAD speech regions overlap voi sentence timestamp.
- Neu overlap tot, dung VAD de refine bien:
  - `start = min(vad_overlap.start, sentence.start)` co padding nho.
  - `end = max(vad_overlap.end, sentence.end)` co padding nho.
- Neu VAD khong detect nhung transcript co timestamp:
  - Van co the cat theo transcript timestamp.
  - Danh dau `vad_status=no_overlap`.
- Neu VAD region dai chua nhieu transcript sentences:
  - Cat thanh nhieu file theo tung sentence transcript.
- Neu mot sentence bi chia thanh nhieu VAD regions gan nhau:
  - Merge neu gap nho, vi du `< 0.5s`.

Nhu vay transcript la don vi cau, con VAD giup bien audio sach hon.

### 6. Fallback khi khong co transcript

Voi audio khong co `.vtt` hoac VTT trong:

- Van chay VAD.
- Cat theo speech regions.
- Tao `.wav`.
- Transcript `.txt` de rong hoac ghi marker.
- Manifest ghi:

```text
transcript_status=missing
text=""
```

Neu sau nay muon du transcript cho nhom nay thi them buoc ASR fallback, nhung khong nen tron vao scope dau tien.

### 7. Export audio con va transcript

Tao script moi, de xuat:

```text
scripts/segment_youtube_audio_with_vad_transcript.py
```

CLI du kien:

```powershell
python scripts\segment_youtube_audio_with_vad_transcript.py `
  --audio-dir VSF-audio-pipeline\data\processed\audio `
  --vtt-dir VSF-audio-pipeline\data\raw\youtube `
  --out-dir pipeline_runs\youtube_sentence_labels `
  --refine-boundaries `
  --overwrite
```

Script se:

- Scan toan bo WAV.
- Map VTT theo video_id.
- Parse VTT.
- Chay VAD.
- Align sentence voi VAD.
- Cat WAV bang `wave` hoac `ffmpeg`.
- Ghi `.txt`.
- Ghi `labels.csv`, `labels.jsonl`, `audio_summary.csv`.

### 8. Validation va bao cao

Sau khi chay, can kiem tra:

- Tong so WAV input.
- So WAV co transcript.
- So WAV thieu transcript.
- Tong so segment output.
- So segment co text.
- So segment rong text.
- Duration min/max/avg.
- Segment qua ngan/qua dai.
- Audio khong tao duoc segment.

Vi du summary:

```text
input_audio: 62
with_vtt: 52
missing_vtt: 10
total_segments: ...
segments_with_text: ...
segments_without_text: ...
```

### 9. Acceptance Criteria

Task duoc xem la hoan thien khi:

- Chay duoc toan bo folder `data/processed/audio`.
- Khong crash khi VTT thieu hoac trong.
- Moi `audio_id` co folder segment rieng.
- Moi audio con co transcript `.txt` tuong ung.
- Co manifest tong `labels.csv/jsonl`.
- Output giu duoc trace nguoc ve `source_wav`, `source_vtt`, `video_id`.
- Co bao cao cac case loi/missing de review tiep.

## Thu Tu Lam De Xuat

1. Viet module map `audio_id -> wav/vtt`.
2. Viet parser VTT + de-duplicate YouTube caption.
3. Tich hop VAD hien co de lay speech regions.
4. Viet aligner transcript sentence voi VAD regions.
5. Export segment WAV/TXT + manifest.
6. Chay smoke tren 1-2 audio.
7. Chay full tren toan bo `processed/audio`.
8. Review output va tinh chinh threshold/gap/sentence rules.
