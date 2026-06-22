# Manual WER Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho người review nghe wav từng segment `needs_review` trên dashboard, gõ reference (lời đúng), backend tính WER thật canonical (label `text` vs reference), lưu vào metadata file, hiện %WER per-segment + tổng batch.

**Architecture:** Backend thêm WER core (port từ `eval/wer`, stdlib), 3 cột review vào metadata file, một `SegmentReviewService` đọc/ghi metadata + 4 REST route. Frontend thêm feature `review` (antd) gắn thành tab mới trong dashboard. Tất cả additive, nằm ngoài flow ingest chính.

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy (không đụng DB cho feature này) · pytest · React + TypeScript + Ant Design + axios (Vite).

## Global Constraints

- **WER metric** = canonical eval/wer: token = âm tiết tách theo whitespace; normalize level `normalized` (NFC → lowercase → strip markup `[..]`/`>>` → bỏ dấu câu → gom whitespace → collapse ad-lib ≥2 token); **GIỮ dấu thanh**. `WER = (S+D+I)/N_ref`.
- **hypothesis** = cột `text` của segment (label VTT). **reference** = người gõ.
- **Persistence** = ghi cột vào metadata file (`<batch_name>_segments.csv` + `.jsonl`). KHÔNG tạo DB table. Cột review phải **giữ nguyên khi pipeline re-run**.
- **KHÔNG import `pipeline_service`** từ service/API review (nó kéo audio libs; API startup phải nhẹ — xem `worker.py`). Dùng module dùng chung nhẹ cho fieldnames.
- **Audio serve**: chỉ qua `batch_name` + `segment_id`; service tự resolve `segment_file` từ metadata rồi validate path nằm trong `segments_dir` (chống traversal).
- **Run backend tests** (Windows, committed `.venv` là Linux-only):
  ```powershell
  $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
  uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest -q
  ```
  Chạy 1 test: thêm `tests/<path>::<name>` vào cuối. Baseline hiện tại: **118 passed**.
- **Frontend không có test harness** (không vitest). Verify FE bằng `npm run build` (= `tsc && vite build`) trong `VSF-audio-pipeline/frontend`.
- Commit message tiếng Anh ngắn; kết thúc bằng `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

| File | Trách nhiệm |
|------|-------------|
| `backend/app/modules/audio_pipeline/application/segmentation/wer_canonical.py` (create) | WER core: `normalize`, `tokens`, `Counts`, `align`, `micro_average` (stdlib port) |
| `backend/app/modules/audio_pipeline/application/segmentation/metadata_fields.py` (create) | Hằng `SEGMENT_METADATA_FIELDS`, `REVIEW_FIELDS` dùng chung |
| `backend/app/modules/audio_pipeline/application/pipeline_service.py` (modify) | `build_segment_metadata` dùng fieldnames chung + merge-preserve cột review |
| `backend/app/modules/audio_pipeline/application/segment_review_service.py` (create) | Đọc/ghi metadata, tính WER, list/submit/summary/resolve-audio |
| `backend/app/modules/audio_pipeline/api/schemas.py` (modify) | `ReviewSegment`, `ReviewRequest`, `WerSummary` |
| `backend/app/modules/audio_pipeline/api/routes.py` (modify) | 4 route review + dependency `get_review_service` |
| `backend/tests/segmentation/test_wer_canonical.py` (create) | Test WER core |
| `backend/tests/test_pipeline_service_segments.py` (modify) | Test merge-preserve |
| `backend/tests/test_segment_review_service.py` (create) | Test service |
| `backend/tests/test_review_endpoints.py` (create) | Test 4 route |
| `frontend/src/entities/review/model.ts` (create) | Types `ReviewSegment`, `WerSummary` |
| `frontend/src/features/review/api/review.ts` (create) | API client |
| `frontend/src/features/review/components/ReviewPanel.tsx` (create) | UI review |
| `frontend/src/pages/dashboard/DashboardPage.tsx` (modify) | Thêm tab "Review WER" |

---

### Task 1: WER canonical core (port từ eval/wer)

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/wer_canonical.py`
- Test: `backend/tests/segmentation/test_wer_canonical.py`

**Interfaces:**
- Produces:
  - `normalize(text: str, *, level: str = "normalized", keep_diacritics: bool = True) -> str`
  - `tokens(text: str) -> list[str]`
  - `align(ref: list[str], hyp: list[str]) -> Counts`
  - `Counts` dataclass: fields `sub, dele, ins, cor, n_ref: int`; props `.errors -> int`, `.wer -> float` (nan nếu n_ref=0), `.spurious -> bool`
  - `micro_average(counts_list: list[Counts]) -> float`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/segmentation/test_wer_canonical.py`:

```python
from math import isnan

from app.modules.audio_pipeline.application.segmentation.wer_canonical import (
    Counts,
    align,
    micro_average,
    normalize,
    tokens,
)


def test_normalize_strips_markup_and_punct_keeps_tones():
    # [âm nhạc] markup bị bỏ; dấu câu bỏ; dấu thanh giữ.
    assert normalize("[âm nhạc] Chợt nhận ra, rằng!") == "chợt nhận ra rằng"


def test_normalize_collapses_adlib_runs():
    # run >=2 token ad-lib bị xoá; 'là' (có dấu) KHÁC 'la' nên không bị nuốt.
    assert normalize("la la la chợt nhận ra") == "chợt nhận ra"
    assert normalize("là chợt nhận ra") == "là chợt nhận ra"


def test_align_counts_sub_del_ins():
    ref = tokens(normalize("một hai ba bốn"))
    hyp = tokens(normalize("một hai bốn năm"))
    c = align(ref, hyp)
    # ref=4 token. "ba" deleted, "năm" inserted -> sai lệch.
    assert c.n_ref == 4
    assert c.errors == c.sub + c.dele + c.ins
    assert c.wer == c.errors / 4


def test_align_empty_ref_is_spurious_when_hyp_has_tokens():
    c = align([], tokens(normalize("lời thừa")))
    assert c.n_ref == 0
    assert isnan(c.wer)
    assert c.spurious is True


def test_micro_average_ignores_zero_ref():
    a = align(tokens("a b c"), tokens("a b c"))      # 0 lỗi / 3
    b = align(tokens("x y"), tokens("x z"))          # 1 lỗi / 2
    empty = align([], tokens("junk"))                # bỏ qua (N=0)
    assert micro_average([a, b, empty]) == 1 / 5
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/segmentation/test_wer_canonical.py -q
```
Expected: FAIL — `ModuleNotFoundError: ... wer_canonical`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/modules/audio_pipeline/application/segmentation/wer_canonical.py`:

```python
"""WER canonical tiếng Việt — port stdlib từ eval/wer/vsf_wer (normalize + wer).

Dùng cho manual WER review: so label `text` (hypothesis) với reference người nghe.
Token = âm tiết tách theo whitespace. Giữ dấu thanh (phonemic). Không import chéo
sang eval/wer (project riêng) — copy logic tối thiểu vào backend.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from math import nan

_BRACKET_RE = re.compile(r"[\[\(][^\]\)]*[\]\)]")
_MARKER_RE = re.compile(r">>+|&gt;")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_ADLIB = {"na", "la", "oh", "ohh", "ooh", "ooo", "hey", "ah", "uh", "yeah", "wo", "woah"}


def _collapse_adlib(text: str) -> str:
    toks = text.split()
    out: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i] in _ADLIB:
            j = i
            while j < n and toks[j] in _ADLIB:
                j += 1
            if j - i >= 2:
                i = j
                continue
        out.append(toks[i])
        i += 1
    return " ".join(out)


def normalize(text: str, *, level: str = "normalized", keep_diacritics: bool = True) -> str:
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text)).lower()
    if level == "normalized":
        s = _BRACKET_RE.sub(" ", s)
        s = _MARKER_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    if level == "normalized":
        s = _collapse_adlib(s)
    if not keep_diacritics:
        s = s.replace("đ", "d").replace("Đ", "D")
        decomposed = unicodedata.normalize("NFD", s)
        s = "".join(c for c in decomposed if not unicodedata.combining(c))
        s = unicodedata.normalize("NFC", s)
    return _WS_RE.sub(" ", s).strip()


def tokens(text: str) -> list[str]:
    return text.split() if text else []


EQUAL, SUB, DEL, INS = "=", "S", "D", "I"


@dataclass
class Counts:
    sub: int = 0
    dele: int = 0
    ins: int = 0
    cor: int = 0
    n_ref: int = 0
    ops: list[tuple[str, str | None, str | None]] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return self.sub + self.dele + self.ins

    @property
    def wer(self) -> float:
        return self.errors / self.n_ref if self.n_ref else nan

    @property
    def spurious(self) -> bool:
        return self.n_ref == 0 and self.ins > 0


def align(ref: list[str], hyp: list[str]) -> Counts:
    """Levenshtein DP + backtrace (sub=1 nếu khác, ins=del=1)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    bt: list[list[str | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
        bt[i][0] = DEL
    for j in range(1, m + 1):
        d[0][j] = j
        bt[0][j] = INS
    for i in range(1, n + 1):
        ri = ref[i - 1]
        for j in range(1, m + 1):
            if ri == hyp[j - 1]:
                sub_cost, tag = 0, EQUAL
            else:
                sub_cost, tag = 1, SUB
            diag = d[i - 1][j - 1] + sub_cost
            up = d[i - 1][j] + 1
            left = d[i][j - 1] + 1
            best = min(diag, up, left)
            d[i][j] = best
            bt[i][j] = tag if best == diag else (DEL if best == up else INS)

    c = Counts(n_ref=n)
    i, j = n, m
    ops_rev: list[tuple[str, str | None, str | None]] = []
    while i > 0 or j > 0:
        tag = bt[i][j]
        if tag in (EQUAL, SUB):
            ops_rev.append((tag, ref[i - 1], hyp[j - 1]))
            if tag == EQUAL:
                c.cor += 1
            else:
                c.sub += 1
            i, j = i - 1, j - 1
        elif tag == DEL:
            ops_rev.append((DEL, ref[i - 1], None))
            c.dele += 1
            i -= 1
        else:
            ops_rev.append((INS, None, hyp[j - 1]))
            c.ins += 1
            j -= 1
    c.ops = list(reversed(ops_rev))
    return c


def micro_average(counts_list: list[Counts]) -> float:
    tot_err = sum(c.errors for c in counts_list if c.n_ref > 0)
    tot_n = sum(c.n_ref for c in counts_list if c.n_ref > 0)
    return tot_err / tot_n if tot_n else nan
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/segmentation/test_wer_canonical.py -q
```
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/wer_canonical.py backend/tests/segmentation/test_wer_canonical.py
git commit -m "feat: add canonical VN WER core for manual review

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Metadata review columns + merge-preserve

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/metadata_fields.py`
- Modify: `backend/app/modules/audio_pipeline/application/pipeline_service.py` (`build_segment_metadata`, hiện ~dòng 1695-1723)
- Test: `backend/tests/test_pipeline_service_segments.py` (thêm 1 test)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SEGMENT_METADATA_FIELDS: list[str]` (20 cột: 17 cũ + `reference`, `manual_wer`, `review_status`)
  - `REVIEW_FIELDS: tuple[str, str, str]` = `("reference", "manual_wer", "review_status")`

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `backend/tests/test_pipeline_service_segments.py`:

```python
def test_rebuild_preserves_review_columns(make_wav, tmp_path, monkeypatch):
    from app.utils.filesystem import read_csv, write_csv
    from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
        SEGMENT_METADATA_FIELDS,
    )

    service = AudioPipelineService()
    monkeypatch.setattr(service, "segments_dir", tmp_path / "segments")
    monkeypatch.setattr(service, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(
        service, "_build_segment_dependencies", lambda: (_FakeVad(), _FakeAsr())
    )
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": str(vtt),
    }]
    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")

    # Giả lập 1 lượt review: ghi reference + manual_wer + review_status vào CSV.
    rows = read_csv(manifest)
    rows[0]["reference"] = "cau mot"
    rows[0]["manual_wer"] = "0.25"
    rows[0]["review_status"] = "reviewed"
    write_csv(manifest, SEGMENT_METADATA_FIELDS, rows)

    # Re-run build với cùng segment_id -> cột review phải còn nguyên.
    service.build_segment_metadata(seg_rows, batch_name="b1")
    after = read_csv(manifest)[0]
    assert after["reference"] == "cau mot"
    assert after["manual_wer"] == "0.25"
    assert after["review_status"] == "reviewed"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/test_pipeline_service_segments.py::test_rebuild_preserves_review_columns -q
```
Expected: FAIL — `ModuleNotFoundError: ... metadata_fields` (hoặc KeyError cột review).

- [ ] **Step 3a: Create the shared fieldnames module**

Create `backend/app/modules/audio_pipeline/application/segmentation/metadata_fields.py`:

```python
"""Fieldnames của segment metadata — dùng chung giữa pipeline_service (ghi) và
segment_review_service (đọc/ghi). Tách riêng để không phải import pipeline_service
(kéo audio libs) từ tầng review."""

from __future__ import annotations

REVIEW_FIELDS: tuple[str, str, str] = ("reference", "manual_wer", "review_status")

SEGMENT_METADATA_FIELDS: list[str] = [
    "audio_id", "video_id", "segment_id", "segment_file", "transcript_file",
    "start", "end", "duration", "text", "transcript_source",
    "transcript_status", "vad_status", "quality_label", "quality_score",
    "quality_reasons", "source_url", "title",
    *REVIEW_FIELDS,
]
```

- [ ] **Step 3b: Rewrite `build_segment_metadata` to use shared fields + preserve review columns**

In `backend/app/modules/audio_pipeline/application/pipeline_service.py`, replace the body of `build_segment_metadata` (currently dòng ~1701-1723, từ `batch = batch_name or "batch_001"` đến `return csv_path`) with:

```python
        batch = batch_name or "batch_001"
        csv_path = self.metadata_dir / f"{batch}_segments.csv"

        existing = read_csv(csv_path)
        merged: dict[str, dict] = {
            row.get("segment_id", f"row_{i}"): row for i, row in enumerate(existing)
        }
        for row in segment_rows:
            segment_id = row["segment_id"]
            prev = merged.get(segment_id, {})
            new_row = {key: row.get(key, "") for key in SEGMENT_METADATA_FIELDS}
            # Giữ lại dữ liệu review người dùng đã điền khi pipeline chạy lại.
            for review_field in REVIEW_FIELDS:
                if prev.get(review_field):
                    new_row[review_field] = prev[review_field]
            if not new_row["review_status"] and new_row["quality_label"] == "needs_review":
                new_row["review_status"] = "pending"
            merged[segment_id] = new_row

        write_csv(csv_path, SEGMENT_METADATA_FIELDS, merged.values())

        jsonl_path = csv_path.with_suffix(".jsonl")
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in merged.values():
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        logger.info("step=build_segment_metadata")
        return csv_path
```

Then add the import near the top of `pipeline_service.py` (cùng nhóm import segmentation, ví dụ cạnh dòng 18 `from app.modules.audio_pipeline.application.segmentation.asr_adapter import FasterWhisperAdapter`):

```python
from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
    REVIEW_FIELDS,
    SEGMENT_METADATA_FIELDS,
)
```

> Note: xoá biến `fieldnames` cũ định nghĩa inline trong hàm (đã thay bằng `SEGMENT_METADATA_FIELDS`).

- [ ] **Step 4: Run tests to verify they pass**

Run (test mới + test cũ của file này để chắc không vỡ):
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/test_pipeline_service_segments.py -q
```
Expected: PASS (2 passed — `test_segment_and_label_and_metadata` cũ + `test_rebuild_preserves_review_columns` mới).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/metadata_fields.py backend/app/modules/audio_pipeline/application/pipeline_service.py backend/tests/test_pipeline_service_segments.py
git commit -m "feat: add review columns to segment metadata, preserve on re-run

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: SegmentReviewService

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segment_review_service.py`
- Test: `backend/tests/test_segment_review_service.py`

**Interfaces:**
- Consumes: `wer_canonical.{normalize, tokens, align, micro_average}` (Task 1); `metadata_fields.{SEGMENT_METADATA_FIELDS}` (Task 2); `app.utils.filesystem.{read_csv, write_csv}`.
- Produces `SegmentReviewService`:
  - `__init__(self, metadata_dir: Path, segments_dir: Path)`
  - `list_segments(self, batch_name: str, status: str = "needs_review") -> list[dict]` — mỗi dict: `segment_id, text, reference, manual_wer (float|None), review_status, start, end, duration, quality_reasons, spurious (bool)`. Raise `FileNotFoundError` nếu metadata batch không có.
  - `submit_review(self, batch_name: str, segment_id: str, reference: str) -> dict` — cùng shape; ghi lại csv+jsonl. Raise `FileNotFoundError` nếu segment_id không có.
  - `wer_summary(self, batch_name: str) -> dict` — `{batch_name, micro_wer (float|None), reviewed, total_needs_review, spurious, pending}`.
  - `resolve_audio_path(self, batch_name: str, segment_id: str) -> Path` — Raise `FileNotFoundError` (batch/segment/file thiếu) hoặc `ValueError` (path ngoài segments_dir).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_segment_review_service.py`:

```python
import json
from math import isnan

import pytest

from app.modules.audio_pipeline.application.segment_review_service import (
    SegmentReviewService,
)
from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
    SEGMENT_METADATA_FIELDS,
)


def _row(**kw):
    base = {k: "" for k in SEGMENT_METADATA_FIELDS}
    base.update(kw)
    return base


def _write_batch(metadata_dir, segments_dir, batch, rows):
    metadata_dir.mkdir(parents=True, exist_ok=True)
    path = metadata_dir / f"{batch}_segments.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    # csv để submit_review rewrite được cả hai
    import csv
    with (metadata_dir / f"{batch}_segments.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SEGMENT_METADATA_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


@pytest.fixture()
def service(tmp_path):
    meta = tmp_path / "metadata"
    segs = tmp_path / "segments"
    segs.mkdir(parents=True, exist_ok=True)
    seg_file = segs / "yt_v__sent000001.wav"
    seg_file.write_bytes(b"RIFFfake")
    rows = [
        _row(segment_id="yt_v__sent000001", text="chợt nhận ra", quality_label="needs_review",
             review_status="pending", quality_reasons="wer_gate>0.3",
             start="0.0", end="1.0", duration="1.0", segment_file=str(seg_file)),
        _row(segment_id="yt_v__sent000002", text="ổn", quality_label="speech_clean",
             review_status="", start="1.0", end="2.0", duration="1.0"),
    ]
    _write_batch(meta, segs, "b1", rows)
    return SegmentReviewService(metadata_dir=meta, segments_dir=segs)


def test_list_only_needs_review(service):
    items = service.list_segments("b1")
    assert len(items) == 1
    assert items[0]["segment_id"] == "yt_v__sent000001"
    assert items[0]["review_status"] == "pending"
    assert items[0]["manual_wer"] is None


def test_list_missing_batch_raises(service):
    with pytest.raises(FileNotFoundError):
        service.list_segments("nope")


def test_submit_review_computes_and_persists(service):
    # hyp="chợt nhận ra" (3 token). ref="chợt nhận biết" -> 1 sub / 3 = 0.333
    out = service.submit_review("b1", "yt_v__sent000001", "chợt nhận biết")
    assert out["review_status"] == "reviewed"
    assert out["manual_wer"] == pytest.approx(1 / 3, abs=1e-3)
    # persisted: đọc lại list thấy reference + wer.
    again = service.list_segments("b1")[0]
    assert again["reference"] == "chợt nhận biết"
    assert again["manual_wer"] == pytest.approx(1 / 3, abs=1e-3)


def test_submit_empty_reference_is_skipped(service):
    out = service.submit_review("b1", "yt_v__sent000001", "   ")
    assert out["review_status"] == "skipped"
    assert out["manual_wer"] is None
    assert out["spurious"] is True  # hyp có token, ref rỗng


def test_submit_unknown_segment_raises(service):
    with pytest.raises(FileNotFoundError):
        service.submit_review("b1", "no_such", "x")


def test_wer_summary_micro_average(service):
    service.submit_review("b1", "yt_v__sent000001", "chợt nhận biết")  # 1/3
    s = service.wer_summary("b1")
    assert s["total_needs_review"] == 1
    assert s["reviewed"] == 1
    assert s["pending"] == 0
    assert s["micro_wer"] == pytest.approx(1 / 3, abs=1e-3)


def test_wer_summary_empty_when_none_reviewed(service):
    s = service.wer_summary("b1")
    assert s["reviewed"] == 0
    assert s["micro_wer"] is None


def test_resolve_audio_ok(service):
    p = service.resolve_audio_path("b1", "yt_v__sent000001")
    assert p.exists()


def test_resolve_audio_traversal_blocked(service, tmp_path):
    # Trỏ segment_file ra ngoài segments_dir -> ValueError.
    outside = tmp_path / "evil.wav"
    outside.write_bytes(b"x")
    meta = service.metadata_dir
    path = meta / "b1_segments.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["segment_file"] = str(outside)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        service.resolve_audio_path("b1", "yt_v__sent000001")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/test_segment_review_service.py -q
```
Expected: FAIL — `ModuleNotFoundError: ... segment_review_service`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/modules/audio_pipeline/application/segment_review_service.py`:

```python
"""Service cho manual WER review: đọc/ghi metadata file, tính WER canonical.

KHÔNG import pipeline_service (kéo audio libs). Chỉ dùng filesystem helpers +
wer_canonical + metadata_fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
    SEGMENT_METADATA_FIELDS,
)
from app.modules.audio_pipeline.application.segmentation.wer_canonical import (
    align,
    micro_average,
    normalize,
    tokens,
)
from app.utils.filesystem import write_csv


def _to_float(value: object) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


class SegmentReviewService:
    def __init__(self, metadata_dir: Path, segments_dir: Path) -> None:
        self.metadata_dir = Path(metadata_dir)
        self.segments_dir = Path(segments_dir)

    # ---- file io ----------------------------------------------------------
    def _jsonl_path(self, batch_name: str) -> Path:
        return self.metadata_dir / f"{batch_name}_segments.jsonl"

    def _csv_path(self, batch_name: str) -> Path:
        return self.metadata_dir / f"{batch_name}_segments.csv"

    def _read_rows(self, batch_name: str) -> list[dict]:
        path = self._jsonl_path(batch_name)
        if not path.exists():
            raise FileNotFoundError(f"Metadata not found for batch: {batch_name}")
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _write_rows(self, batch_name: str, rows: list[dict]) -> None:
        normalized = [{k: r.get(k, "") for k in SEGMENT_METADATA_FIELDS} for r in rows]
        write_csv(self._csv_path(batch_name), SEGMENT_METADATA_FIELDS, normalized)
        with self._jsonl_path(batch_name).open("w", encoding="utf-8") as handle:
            for row in normalized:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---- view model -------------------------------------------------------
    def _to_view(self, row: dict) -> dict:
        text = row.get("text", "") or ""
        reference = row.get("reference", "") or ""
        spurious = (not normalize(reference)) and bool(tokens(normalize(text)))
        return {
            "segment_id": row.get("segment_id", ""),
            "text": text,
            "reference": reference,
            "manual_wer": _to_float(row.get("manual_wer")),
            "review_status": row.get("review_status", "") or "pending",
            "start": _to_float(row.get("start")),
            "end": _to_float(row.get("end")),
            "duration": _to_float(row.get("duration")),
            "quality_reasons": row.get("quality_reasons", "") or "",
            "spurious": spurious,
        }

    # ---- public api -------------------------------------------------------
    def list_segments(self, batch_name: str, status: str = "needs_review") -> list[dict]:
        rows = self._read_rows(batch_name)
        return [self._to_view(r) for r in rows if r.get("quality_label") == status]

    def submit_review(self, batch_name: str, segment_id: str, reference: str) -> dict:
        rows = self._read_rows(batch_name)
        target = next((r for r in rows if r.get("segment_id") == segment_id), None)
        if target is None:
            raise FileNotFoundError(f"Segment not found: {segment_id}")

        ref_tokens = tokens(normalize(reference))
        hyp_tokens = tokens(normalize(target.get("text", "")))
        if not ref_tokens:
            target["reference"] = reference
            target["manual_wer"] = ""
            target["review_status"] = "skipped"
        else:
            counts = align(ref_tokens, hyp_tokens)
            target["reference"] = reference
            target["manual_wer"] = f"{counts.wer:.4f}"
            target["review_status"] = "reviewed"

        self._write_rows(batch_name, rows)
        return self._to_view(target)

    def wer_summary(self, batch_name: str) -> dict:
        rows = self._read_rows(batch_name)
        needs = [r for r in rows if r.get("quality_label") == "needs_review"]
        counts_list = []
        reviewed = pending = spurious = 0
        for r in needs:
            status = r.get("review_status", "") or "pending"
            ref_tokens = tokens(normalize(r.get("reference", "")))
            hyp_tokens = tokens(normalize(r.get("text", "")))
            if status == "reviewed" and ref_tokens:
                counts_list.append(align(ref_tokens, hyp_tokens))
                reviewed += 1
            elif status == "skipped":
                if hyp_tokens:
                    spurious += 1
            else:
                pending += 1
        micro = micro_average(counts_list) if counts_list else float("nan")
        return {
            "batch_name": batch_name,
            "micro_wer": None if micro != micro else micro,  # nan -> None
            "reviewed": reviewed,
            "total_needs_review": len(needs),
            "spurious": spurious,
            "pending": pending,
        }

    def resolve_audio_path(self, batch_name: str, segment_id: str) -> Path:
        rows = self._read_rows(batch_name)
        target = next((r for r in rows if r.get("segment_id") == segment_id), None)
        if target is None:
            raise FileNotFoundError(f"Segment not found: {segment_id}")
        raw = target.get("segment_file", "") or ""
        if not raw:
            raise FileNotFoundError(f"No audio path for segment: {segment_id}")
        path = Path(raw).resolve()
        root = self.segments_dir.resolve()
        if root != path and root not in path.parents:
            raise ValueError("Segment file outside segments_dir")
        if not path.exists():
            raise FileNotFoundError(f"Audio file missing: {path}")
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/test_segment_review_service.py -q
```
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segment_review_service.py backend/tests/test_segment_review_service.py
git commit -m "feat: add SegmentReviewService (list/submit/summary/audio)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Review API routes + schemas

**Files:**
- Modify: `backend/app/modules/audio_pipeline/api/schemas.py`
- Modify: `backend/app/modules/audio_pipeline/api/routes.py`
- Test: `backend/tests/test_review_endpoints.py`

**Interfaces:**
- Consumes: `SegmentReviewService` (Task 3); `settings.metadata_dir`, `settings.segments_dir`.
- Produces routes (prefix `/audio-pipeline` đã có ở `router.py`):
  - `GET /batches/{batch_name}/segments?status=needs_review` → `list[ReviewSegment]`
  - `GET /batches/{batch_name}/segments/{segment_id}/audio` → `FileResponse` (audio/wav)
  - `POST /batches/{batch_name}/segments/{segment_id}/review` body `ReviewRequest` → `ReviewSegment`
  - `GET /batches/{batch_name}/wer-summary` → `WerSummary`
  - Dependency `get_review_service() -> SegmentReviewService`
- Pydantic: `ReviewSegment`, `ReviewRequest`, `WerSummary`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_review_endpoints.py`:

```python
"""Tests cho 4 route review. Build mini FastAPI từ cùng router, override
get_review_service bằng mock."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audio_pipeline.api.routes import get_review_service, router


def _seg(**kw):
    base = dict(
        segment_id="yt_v__sent000001", text="chợt nhận ra", reference="",
        manual_wer=None, review_status="pending", start=0.0, end=1.0,
        duration=1.0, quality_reasons="wer_gate>0.3", spurious=False,
    )
    base.update(kw)
    return base


@pytest.fixture()
def client():
    svc = MagicMock()
    mini = FastAPI()
    mini.include_router(router)
    mini.dependency_overrides[get_review_service] = lambda: svc
    with TestClient(mini, raise_server_exceptions=True) as tc:
        yield tc, svc


def test_list_segments(client):
    tc, svc = client
    svc.list_segments.return_value = [_seg()]
    resp = tc.get("/batches/b1/segments?status=needs_review")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["segment_id"] == "yt_v__sent000001"
    assert data[0]["manual_wer"] is None
    svc.list_segments.assert_called_once_with("b1", status="needs_review")


def test_list_segments_missing_batch_404(client):
    tc, svc = client
    svc.list_segments.side_effect = FileNotFoundError("nope")
    resp = tc.get("/batches/zzz/segments")
    assert resp.status_code == 404


def test_submit_review(client):
    tc, svc = client
    svc.submit_review.return_value = _seg(reference="chợt nhận biết",
                                          manual_wer=0.3333, review_status="reviewed")
    resp = tc.post("/batches/b1/segments/yt_v__sent000001/review",
                   json={"reference": "chợt nhận biết"})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "reviewed"
    assert resp.json()["manual_wer"] == pytest.approx(0.3333)
    svc.submit_review.assert_called_once_with("b1", "yt_v__sent000001", "chợt nhận biết")


def test_submit_review_unknown_segment_404(client):
    tc, svc = client
    svc.submit_review.side_effect = FileNotFoundError("no seg")
    resp = tc.post("/batches/b1/segments/x/review", json={"reference": "y"})
    assert resp.status_code == 404


def test_wer_summary(client):
    tc, svc = client
    svc.wer_summary.return_value = dict(
        batch_name="b1", micro_wer=0.83, reviewed=2,
        total_needs_review=5, spurious=1, pending=2,
    )
    resp = tc.get("/batches/b1/wer-summary")
    assert resp.status_code == 200
    assert resp.json()["micro_wer"] == pytest.approx(0.83)
    assert resp.json()["total_needs_review"] == 5


def test_audio_traversal_400(client):
    tc, svc = client
    svc.resolve_audio_path.side_effect = ValueError("outside")
    resp = tc.get("/batches/b1/segments/x/audio")
    assert resp.status_code == 400


def test_audio_missing_404(client):
    tc, svc = client
    svc.resolve_audio_path.side_effect = FileNotFoundError("missing")
    resp = tc.get("/batches/b1/segments/x/audio")
    assert resp.status_code == 404


def test_audio_ok(client, tmp_path):
    tc, svc = client
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFFfake")
    svc.resolve_audio_path.return_value = wav
    resp = tc.get("/batches/b1/segments/yt_v__sent000001/audio")
    assert resp.status_code == 200
    assert resp.content == b"RIFFfake"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/test_review_endpoints.py -q
```
Expected: FAIL — `ImportError: cannot import name 'get_review_service'`.

- [ ] **Step 3a: Add schemas**

Append to `backend/app/modules/audio_pipeline/api/schemas.py`:

```python
class ReviewSegment(BaseModel):
    segment_id: str
    text: str
    reference: str = ""
    manual_wer: float | None = None
    review_status: str = "pending"
    start: float | None = None
    end: float | None = None
    duration: float | None = None
    quality_reasons: str = ""
    spurious: bool = False


class ReviewRequest(BaseModel):
    reference: str = ""


class WerSummary(BaseModel):
    batch_name: str
    micro_wer: float | None = None
    reviewed: int = 0
    total_needs_review: int = 0
    spurious: int = 0
    pending: int = 0
```

- [ ] **Step 3b: Add routes + dependency**

In `backend/app/modules/audio_pipeline/api/routes.py`:

Add imports near the top (cạnh các import hiện có):

```python
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings
from app.modules.audio_pipeline.api.schemas import (
    ReviewRequest,
    ReviewSegment,
    WerSummary,
)
from app.modules.audio_pipeline.application.segment_review_service import (
    SegmentReviewService,
)
```

> Lưu ý: file đã import nhiều schema từ `app.modules.audio_pipeline.api.schemas` — gộp 3 tên mới vào khối import đó thay vì viết khối mới nếu muốn gọn. `FileResponse` thêm cạnh `StreamingResponse` đã có.

Add dependency provider + routes (đặt cuối file):

```python
def get_review_service() -> SegmentReviewService:
    return SegmentReviewService(
        metadata_dir=settings.metadata_dir,
        segments_dir=settings.segments_dir,
    )


@router.get("/batches/{batch_name}/segments", response_model=list[ReviewSegment])
async def list_review_segments(
    batch_name: str,
    status: str = "needs_review",
    review_service: SegmentReviewService = Depends(get_review_service),
) -> list[ReviewSegment]:
    try:
        return review_service.list_segments(batch_name, status=status)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_name}/segments/{segment_id}/audio")
async def get_segment_audio(
    batch_name: str,
    segment_id: str,
    review_service: SegmentReviewService = Depends(get_review_service),
) -> FileResponse:
    try:
        path = review_service.resolve_audio_path(batch_name, segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@router.post("/batches/{batch_name}/segments/{segment_id}/review", response_model=ReviewSegment)
async def submit_segment_review(
    batch_name: str,
    segment_id: str,
    payload: ReviewRequest,
    review_service: SegmentReviewService = Depends(get_review_service),
) -> ReviewSegment:
    try:
        return review_service.submit_review(batch_name, segment_id, payload.reference)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_name}/wer-summary", response_model=WerSummary)
async def get_wer_summary(
    batch_name: str,
    review_service: SegmentReviewService = Depends(get_review_service),
) -> WerSummary:
    try:
        return review_service.wer_summary(batch_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

> Route order: `GET /batches/{batch_id}/...` (timings, int) đã tồn tại. Các route mới dùng `{batch_name}` (str) trên path khác (`/segments`, `/wer-summary`) nên không xung đột với `/batches/{batch_id}` (response_model=BatchRead) — FastAPI match theo full path. `GET /batches/{batch_id}` chỉ match path đúng 1 segment, không nuốt `/batches/{batch_name}/segments`.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest tests/test_review_endpoints.py -q
```
Expected: PASS (8 passed).

- [ ] **Step 5: Run full backend suite (regression guard)**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "vsf_test_venv"
uv run --directory "E:\VSF\TTS\VSF-audio-pipeline\backend" python -m pytest -q
```
Expected: PASS — 118 cũ + 5 + 1 + 9 + 8 = **141 passed** (con số có thể lệch nhẹ nếu test cũ đếm khác; điều kiện: 0 failed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/audio_pipeline/api/schemas.py backend/app/modules/audio_pipeline/api/routes.py backend/tests/test_review_endpoints.py
git commit -m "feat: add review REST endpoints (segments/audio/review/summary)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Frontend Review tab

**Files:**
- Create: `frontend/src/entities/review/model.ts`
- Create: `frontend/src/features/review/api/review.ts`
- Create: `frontend/src/features/review/components/ReviewPanel.tsx`
- Modify: `frontend/src/pages/dashboard/DashboardPage.tsx`

**Interfaces:**
- Consumes: backend routes từ Task 4; `apiClient` (`shared/api/client.ts`); `VITE_API_BASE_URL`.
- Produces: tab "Review WER" trong dashboard.

- [ ] **Step 1: Add types**

Create `frontend/src/entities/review/model.ts`:

```ts
export type ReviewSegment = {
  segment_id: string;
  text: string;
  reference: string;
  manual_wer: number | null;
  review_status: string;
  start: number | null;
  end: number | null;
  duration: number | null;
  quality_reasons: string;
  spurious: boolean;
};

export type WerSummary = {
  batch_name: string;
  micro_wer: number | null;
  reviewed: number;
  total_needs_review: number;
  spurious: number;
  pending: number;
};
```

- [ ] **Step 2: Add API client**

Create `frontend/src/features/review/api/review.ts`:

```ts
import { apiClient } from "../../../shared/api/client";
import type { ReviewSegment, WerSummary } from "../../../entities/review/model";

const BASE = "/audio-pipeline";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

function toErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const e = error as { response?: { data?: { detail?: string } }; message?: string };
    if (e.response?.data?.detail) return e.response.data.detail;
    if (e.message) return e.message;
  }
  return "Unknown API error";
}

export async function fetchReviewSegments(batchName: string): Promise<ReviewSegment[]> {
  try {
    const res = await apiClient.get<ReviewSegment[]>(
      `${BASE}/batches/${encodeURIComponent(batchName)}/segments`,
      { params: { status: "needs_review" } },
    );
    return res.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function submitReview(
  batchName: string,
  segmentId: string,
  reference: string,
): Promise<ReviewSegment> {
  try {
    const res = await apiClient.post<ReviewSegment>(
      `${BASE}/batches/${encodeURIComponent(batchName)}/segments/${encodeURIComponent(segmentId)}/review`,
      { reference },
    );
    return res.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function fetchWerSummary(batchName: string): Promise<WerSummary> {
  try {
    const res = await apiClient.get<WerSummary>(
      `${BASE}/batches/${encodeURIComponent(batchName)}/wer-summary`,
    );
    return res.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export function segmentAudioUrl(batchName: string, segmentId: string): string {
  return `${API_BASE_URL}${BASE}/batches/${encodeURIComponent(batchName)}/segments/${encodeURIComponent(segmentId)}/audio`;
}
```

- [ ] **Step 3: Add ReviewPanel component**

Create `frontend/src/features/review/components/ReviewPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button, Card, Empty, Input, Space, Statistic, Table, Tag, message } from "antd";

import type { ReviewSegment, WerSummary } from "../../../entities/review/model";
import {
  fetchReviewSegments,
  fetchWerSummary,
  segmentAudioUrl,
  submitReview,
} from "../api/review";

type Props = { batchName: string | null };

function werTag(wer: number | null, status: string) {
  if (status === "skipped") return <Tag color="default">skipped</Tag>;
  if (wer === null) return <Tag color="orange">pending</Tag>;
  const pct = (wer * 100).toFixed(1);
  return <Tag color={wer > 0.3 ? "red" : "green"}>{pct}%</Tag>;
}

export default function ReviewPanel({ batchName }: Props) {
  const [segments, setSegments] = useState<ReviewSegment[]>([]);
  const [summary, setSummary] = useState<WerSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [msgApi, contextHolder] = message.useMessage();

  async function load() {
    if (!batchName) return;
    setLoading(true);
    try {
      const [segs, sum] = await Promise.all([
        fetchReviewSegments(batchName),
        fetchWerSummary(batchName),
      ]);
      setSegments(segs);
      setSummary(sum);
      setDrafts(Object.fromEntries(segs.map((s) => [s.segment_id, s.reference])));
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Không tải được segment review");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchName]);

  async function handleSave(segmentId: string) {
    if (!batchName) return;
    setSavingId(segmentId);
    try {
      const updated = await submitReview(batchName, segmentId, drafts[segmentId] ?? "");
      setSegments((cur) => cur.map((s) => (s.segment_id === segmentId ? updated : s)));
      setSummary(await fetchWerSummary(batchName));
      msgApi.success("Đã lưu review");
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Lưu review thất bại");
    } finally {
      setSavingId(null);
    }
  }

  if (!batchName) return <Empty description="Chọn batch để review" />;

  const columns = [
    {
      title: "Audio",
      dataIndex: "segment_id",
      width: 240,
      render: (segmentId: string) => (
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio controls preload="none" style={{ width: 220 }} src={segmentAudioUrl(batchName, segmentId)} />
      ),
    },
    {
      title: "Label (hypothesis)",
      dataIndex: "text",
      render: (text: string, row: ReviewSegment) => (
        <Space direction="vertical" size={2}>
          <span>{text}</span>
          <Tag color="volcano">{row.quality_reasons}</Tag>
        </Space>
      ),
    },
    {
      title: "Reference (nghe & gõ)",
      dataIndex: "reference",
      width: 280,
      render: (_: string, row: ReviewSegment) => (
        <Input.TextArea
          rows={2}
          value={drafts[row.segment_id] ?? ""}
          placeholder="Lời đúng nghe được (để trống = skip)"
          onChange={(e) =>
            setDrafts((d) => ({ ...d, [row.segment_id]: e.target.value }))
          }
        />
      ),
    },
    {
      title: "WER",
      dataIndex: "manual_wer",
      width: 90,
      render: (wer: number | null, row: ReviewSegment) => werTag(wer, row.review_status),
    },
    {
      title: "",
      width: 90,
      render: (_: unknown, row: ReviewSegment) => (
        <Button
          type="primary"
          size="small"
          loading={savingId === row.segment_id}
          onClick={() => handleSave(row.segment_id)}
        >
          Lưu
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      {contextHolder}
      {summary && (
        <Card>
          <Space size={48} wrap>
            <Statistic
              title="WER micro (đã review)"
              value={summary.micro_wer === null ? "—" : (summary.micro_wer * 100).toFixed(1)}
              suffix={summary.micro_wer === null ? "" : "%"}
            />
            <Statistic title="Đã review" value={`${summary.reviewed}/${summary.total_needs_review}`} />
            <Statistic title="Pending" value={summary.pending} />
            <Statistic title="Spurious" value={summary.spurious} />
          </Space>
        </Card>
      )}
      <Table
        rowKey="segment_id"
        loading={loading}
        dataSource={segments}
        columns={columns}
        pagination={false}
        size="small"
      />
    </Space>
  );
}
```

- [ ] **Step 4: Wire tab into DashboardPage**

In `frontend/src/pages/dashboard/DashboardPage.tsx`:

Add import (cạnh các import component khác, ~dòng 11):

```tsx
import ReviewPanel from "../../features/review/components/ReviewPanel";
```

Add a batch-name option list. After the `batchOptions` useMemo (ends ~dòng 83), add:

```tsx
  // Review API key theo batch_name (không phải id).
  const reviewBatchOptions = useMemo(() => {
    const names = new Set<string>();
    for (const job of jobs) names.add(job.batch_name);
    return [...names].map((name) => ({ value: name, label: name }));
  }, [jobs]);

  const [reviewBatchName, setReviewBatchName] = useState<string | null>(null);
```

> `useState` đã được import sẵn (dòng 1). Nếu linter phàn nàn thứ tự hooks, đặt `useState` cùng nhóm với các `useState` khác ở đầu component thay vì sau useMemo — di chuyển dòng `const [reviewBatchName, ...]` lên cạnh `selectedBatchId` (dòng 41) và chỉ giữ `reviewBatchOptions` useMemo ở đây.

Add a new tab item to the `Tabs` `items` array (sau tab `history`, ~dòng 184):

```tsx
          {
            key: "review",
            label: "Review WER",
            children: (
              <div>
                <Select
                  style={{ minWidth: 240, marginBottom: 12 }}
                  placeholder="Chọn batch (tên)"
                  options={reviewBatchOptions}
                  value={reviewBatchName ?? undefined}
                  onChange={(value) => setReviewBatchName(value)}
                  allowClear
                />
                <ReviewPanel batchName={reviewBatchName} />
              </div>
            ),
          },
```

- [ ] **Step 5: Verify frontend builds**

Run:
```powershell
cd E:\VSF\TTS\VSF-audio-pipeline\frontend
npm run build
```
Expected: `tsc` no type errors + `vite build` succeeds (dist written). If `node_modules` missing, run `npm install` first.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/entities/review/model.ts frontend/src/features/review/api/review.ts frontend/src/features/review/components/ReviewPanel.tsx frontend/src/pages/dashboard/DashboardPage.tsx
git commit -m "feat: add Review WER tab to dashboard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Manual end-to-end verification (sau Task 5)

1. Rebuild backend image nếu cần (mount `./backend` đã live-reload code): `docker restart audio-backend`.
2. Đảm bảo có batch đã chạy với `WER_GATE_ENABLED=true` sinh segment `needs_review` (vd `retest_yzWeRtg7UVs`).
3. Mở frontend `http://localhost:5174` → tab **Review WER** → chọn batch → nghe wav từng segment, gõ reference, Lưu → thấy %WER + summary cập nhật.
4. Kiểm tra metadata file: `data/metadata/<batch>_segments.jsonl` có `reference`/`manual_wer`/`review_status`.

## Self-Review notes (coverage)

- Spec §"WER core port" → Task 1. §"Metadata 3 cột + merge-preserve" → Task 2. §"API list/audio/review/summary" → Task 4 (service Task 3). §"Frontend review feature" → Task 5. §"Testing" → tests trong Task 1-4 + FE build Task 5. §"skip nút" → empty reference ⇒ `review_status=skipped` (Task 3 `submit_review`).
- API path refinement so với design: audio + review đổi sang scope `/batches/{batch_name}/segments/{segment_id}/...` (an toàn hơn `?file=`), đã ghi rõ trong Global Constraints + Task 4.
