# Segment-level Automation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm bước tự động cắt audio YouTube thành các segment cấp câu kèm transcript tiếng Việt (VTT-first, ASR fallback), thay thế output full-video translation/metadata trong backend `external_repos/VSF-audio-pipeline`.

**Architecture:** Một workflow node mới `segment_and_label` gồm các unit nhỏ test-riêng-được (vtt_parser, sentence_grouper, vad_grpc_client, aligner, asr_adapter, segment_writer) + node `build_segment_metadata`. VAD chạy qua Triton gRPC; ASR chạy `faster-whisper` chỉ khi thiếu phụ đề.

**Tech Stack:** Python 3.10+, FastAPI, LangGraph, `uv`, pytest, `tritonclient[grpc]`, `faster-whisper`, `numpy`, `wave`, `soundfile`.

**Lưu ý chung cho người thực thi:**
- Mọi path đều **tương đối từ `external_repos/VSF-audio-pipeline/`** trừ khi ghi rõ.
- Lệnh chạy từ thư mục `external_repos/VSF-audio-pipeline/backend/`.
- Code mới đặt trong package `app.modules.audio_pipeline.application.segmentation`.
- Port logic thuần (VTT/sentence/align/cut) từ `scripts/segment_youtube_audio_with_vad_transcript.py` ở TTS root — **không** import script đó; copy code vào module backend.
- Commit vào git repo của chính `external_repos/VSF-audio-pipeline` trên một feature branch (đây là nơi code sống). KHÔNG đụng spec/plan ở TTS root.

---

## Task 0: Branch, dependencies, test scaffold

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_smoke_scaffold.py`

- [ ] **Step 1: Tạo feature branch**

```bash
cd external_repos/VSF-audio-pipeline
git checkout -b feat/segment-level-pipeline
```

- [ ] **Step 2: Thêm dependencies vào `backend/pyproject.toml`**

Trong mảng `dependencies`, thêm 3 dòng:

```toml
    "tritonclient[grpc]",
    "faster-whisper",
    "numpy",
```

Sau mảng `[build-system]`/`[tool.hatch...]`, thêm cấu hình pytest và dev group:

```toml
[dependency-groups]
dev = [
    "pytest",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: Sync môi trường**

```bash
cd backend
uv sync
```
Expected: cài thêm tritonclient, faster-whisper, numpy, pytest không lỗi.

- [ ] **Step 4: Tạo test scaffold**

`backend/tests/__init__.py`: file rỗng.

`backend/tests/conftest.py`:
```python
from __future__ import annotations

import sys
import wave
from pathlib import Path

import pytest

# Cho phép `import app...` khi chạy pytest từ thư mục backend.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def make_wav(tmp_path):
    """Tạo file WAV mono 16k s16 chứa toàn silence dài `seconds` giây."""

    def _make(seconds: float = 1.0, sample_rate: int = 16000, name: str = "sample.wav") -> Path:
        path = tmp_path / name
        frames = int(seconds * sample_rate)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(b"\x00\x00" * frames)
        return path

    return _make
```

`backend/tests/test_smoke_scaffold.py`:
```python
def test_pytest_runs():
    assert True
```

- [ ] **Step 5: Chạy thử**

```bash
cd backend
uv run pytest tests/test_smoke_scaffold.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/tests
git commit -m "chore: add test scaffold and segmentation deps"
```

---

## Task 1: Config settings cho segmentation

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config_segmentation.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/test_config_segmentation.py`:
```python
from app.core.config import Settings


def test_segmentation_settings_defaults():
    s = Settings()
    assert s.vad_grpc_url == "127.0.0.1:8001"
    assert s.vad_threshold == 0.7
    assert s.vad_min_volume == 0.6
    assert s.vad_start_secs == 0.1
    assert s.vad_stop_secs == 0.45
    assert str(s.segments_dir) == "data/processed/segments"
    assert s.sentence_max_sec == 12.0
    assert s.sentence_min_sec == 0.3
    assert s.phrase_gap_sec == 0.45
    assert s.segment_pad_sec == 0.1
    assert s.segment_min_sec == 0.3
    assert s.asr_model == "large-v3"
    assert s.asr_device == "cuda"
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/test_config_segmentation.py -v
```
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'vad_grpc_url'`).

- [ ] **Step 3: Thêm fields vào `Settings`**

Trong `backend/app/core/config.py`, ngay sau khối `telegram_*` (dòng ~70), thêm:
```python
    # Cấu hình segment-level pipeline (VAD gRPC + cắt câu + ASR fallback).
    vad_grpc_url: str = Field(default="127.0.0.1:8001", alias="VAD_GRPC_URL")
    vad_threshold: float = Field(default=0.7, alias="VAD_THRESHOLD")
    vad_min_volume: float = Field(default=0.6, alias="VAD_MIN_VOLUME")
    vad_start_secs: float = Field(default=0.1, alias="VAD_START_SECS")
    vad_stop_secs: float = Field(default=0.45, alias="VAD_STOP_SECS")
    vad_chunk_ms: int = Field(default=64, alias="VAD_CHUNK_MS")
    segments_dir: Path = Field(default=Path("data/processed/segments"), alias="SEGMENTS_DIR")
    sentence_max_sec: float = Field(default=12.0, alias="SENTENCE_MAX_SEC")
    sentence_min_sec: float = Field(default=0.3, alias="SENTENCE_MIN_SEC")
    phrase_gap_sec: float = Field(default=0.45, alias="PHRASE_GAP_SEC")
    segment_pad_sec: float = Field(default=0.1, alias="SEGMENT_PAD_SEC")
    segment_min_sec: float = Field(default=0.3, alias="SEGMENT_MIN_SEC")
    segment_boundary_slack_sec: float = Field(default=0.5, alias="SEGMENT_BOUNDARY_SLACK_SEC")
    segment_merge_gap_sec: float = Field(default=0.5, alias="SEGMENT_MERGE_GAP_SEC")
    asr_model: str = Field(default="large-v3", alias="ASR_MODEL")
    asr_device: str = Field(default="cuda", alias="ASR_DEVICE")
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/test_config_segmentation.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_config_segmentation.py
git commit -m "feat: add segmentation config settings"
```

---

## Task 2: Shared types

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/__init__.py`
- Create: `backend/app/modules/audio_pipeline/application/segmentation/types.py`
- Test: `backend/tests/segmentation/__init__.py`, `backend/tests/segmentation/test_types.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/__init__.py`: file rỗng.

`backend/tests/segmentation/test_types.py`:
```python
from app.modules.audio_pipeline.application.segmentation.types import (
    AlignedSegment,
    SegmentationConfig,
    SentenceUnit,
    SpeechRegion,
    TranscriptCue,
)


def test_dataclasses_construct():
    cue = TranscriptCue(start=1.0, end=2.0, text="xin chao")
    unit = SentenceUnit(start=1.0, end=2.0, text="xin chao")
    region = SpeechRegion(start=1.0, end=2.0)
    seg = AlignedSegment(start=1.0, end=2.0, text="xin chao", transcript_status="ready", vad_status="aligned")
    assert cue.text == unit.text == seg.text == "xin chao"
    assert region.end == 2.0


def test_segmentation_config_from_mapping():
    cfg = SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45,
        pad_sec=0.1, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
    )
    assert cfg.threshold == 0.7
    assert cfg.sentence_max_sec == 12.0
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_types.py -v
```
Expected: FAIL (`ModuleNotFoundError: ...segmentation.types`).

- [ ] **Step 3: Tạo module**

`backend/app/modules/audio_pipeline/application/segmentation/__init__.py`: file rỗng.

`backend/app/modules/audio_pipeline/application/segmentation/types.py`:
```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SentenceUnit:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float


@dataclass(frozen=True)
class AlignedSegment:
    start: float
    end: float
    text: str
    transcript_status: str  # "ready" | "missing"
    vad_status: str         # "aligned" | "no_overlap" | "speech_region"


@dataclass(frozen=True)
class SegmentationConfig:
    chunk_ms: int
    threshold: float
    min_volume: float
    start_secs: float
    stop_secs: float
    sentence_max_sec: float
    sentence_min_sec: float
    phrase_gap_sec: float
    pad_sec: float
    min_segment_sec: float
    boundary_slack_sec: float
    merge_gap_sec: float
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_types.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation backend/tests/segmentation
git commit -m "feat: add segmentation shared types"
```

---

## Task 3: VTT parser

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/vtt_parser.py`
- Test: `backend/tests/segmentation/test_vtt_parser.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_vtt_parser.py`:
```python
from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.vtt_parser import parse_youtube_vtt

VTT = """WEBVTT
Kind: captions
Language: vi

00:00:01.000 --> 00:00:03.000
<00:00:01.000><c> xin</c><00:00:01.500><c> chao</c>

00:00:01.000 --> 00:00:03.000
xin chao

00:00:03.200 --> 00:00:05.000
cac ban.
"""


def test_parse_dedup_and_clean(tmp_path: Path):
    p = tmp_path / "vid__title.vi.vtt"
    p.write_text(VTT, encoding="utf-8")
    cues = parse_youtube_vtt(p)
    texts = [c.text for c in cues]
    assert "xin chao" in texts[0]
    assert any("cac ban" in t for t in texts)
    # Không lặp lại cue "xin chao" hai lần liên tiếp.
    assert texts.count("xin chao") == 1
    assert cues[0].start == 1.0 and cues[0].end == 3.0
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_vtt_parser.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement (port từ script offline)**

`backend/app/modules/audio_pipeline/application/segmentation/vtt_parser.py`:
```python
from __future__ import annotations

import html
import re
from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.types import TranscriptCue

TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})"
)
INLINE_TIMESTAMP_RE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>|<\d{2}:\d{2}\.\d{3}>")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def parse_timecode(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"invalid WebVTT timecode: {value}")


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def clean_caption_text(line: str) -> str:
    line = INLINE_TIMESTAMP_RE.sub(" ", line)
    line = TAG_RE.sub(" ", line)
    line = html.unescape(line)
    return SPACE_RE.sub(" ", line).strip()


def normalize_for_compare(text: str) -> str:
    return SPACE_RE.sub(" ", text.casefold()).strip()


def strip_known_prefix(text: str, prefix: str) -> str:
    text_norm = normalize_for_compare(text)
    prefix_norm = normalize_for_compare(prefix)
    if not text_norm.startswith(prefix_norm):
        return text
    candidate = text[len(prefix):].strip()
    return candidate or text


def parse_youtube_vtt(path: Path) -> list[TranscriptCue]:
    text = read_text_with_fallback(path)
    lines = text.splitlines()
    cues: list[TranscriptCue] = []
    i = 0
    previous_visible = ""

    while i < len(lines):
        match = TIMESTAMP_RE.search(lines[i])
        if not match:
            i += 1
            continue

        start = parse_timecode(match.group("start"))
        end = parse_timecode(match.group("end"))
        i += 1

        raw_lines: list[str] = []
        while i < len(lines) and lines[i].strip():
            raw_lines.append(lines[i])
            i += 1

        cleaned_lines: list[str] = []
        for raw_line in raw_lines:
            cleaned = clean_caption_text(raw_line)
            if not cleaned:
                continue
            if cleaned_lines and normalize_for_compare(cleaned) == normalize_for_compare(cleaned_lines[-1]):
                continue
            cleaned_lines.append(cleaned)

        if previous_visible and len(cleaned_lines) > 1:
            if normalize_for_compare(cleaned_lines[0]) == normalize_for_compare(previous_visible):
                cleaned_lines = cleaned_lines[1:]

        if not cleaned_lines:
            continue

        caption_text = SPACE_RE.sub(" ", " ".join(cleaned_lines)).strip()
        if previous_visible:
            caption_text = strip_known_prefix(caption_text, previous_visible)

        if caption_text and normalize_for_compare(caption_text) != normalize_for_compare(previous_visible):
            cues.append(TranscriptCue(start=start, end=end, text=caption_text))

        previous_visible = cleaned_lines[-1]

    return cues
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_vtt_parser.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/vtt_parser.py backend/tests/segmentation/test_vtt_parser.py
git commit -m "feat: add youtube vtt parser"
```

---

## Task 4: Sentence grouper

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/sentence_grouper.py`
- Test: `backend/tests/segmentation/test_sentence_grouper.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_sentence_grouper.py`:
```python
from app.modules.audio_pipeline.application.segmentation.sentence_grouper import cues_to_sentence_units
from app.modules.audio_pipeline.application.segmentation.types import TranscriptCue


def test_groups_until_sentence_end():
    cues = [
        TranscriptCue(0.0, 1.0, "xin chao"),
        TranscriptCue(1.0, 2.0, "cac ban."),
        TranscriptCue(2.1, 3.0, "hom nay"),
        TranscriptCue(3.0, 4.0, "troi dep."),
    ]
    units = cues_to_sentence_units(cues, phrase_gap_sec=0.45, max_sentence_sec=12.0, min_sentence_sec=0.3)
    assert len(units) == 2
    assert units[0].text == "xin chao cac ban."
    assert units[0].start == 0.0 and units[0].end == 2.0
    assert units[1].text == "hom nay troi dep."


def test_splits_on_large_gap():
    cues = [
        TranscriptCue(0.0, 1.0, "phan mot"),
        TranscriptCue(3.0, 4.0, "phan hai"),
    ]
    units = cues_to_sentence_units(cues, phrase_gap_sec=0.45, max_sentence_sec=12.0, min_sentence_sec=0.3)
    assert len(units) == 2
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_sentence_grouper.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement (port từ script offline)**

`backend/app/modules/audio_pipeline/application/segmentation/sentence_grouper.py`:
```python
from __future__ import annotations

import re

from app.modules.audio_pipeline.application.segmentation.types import SentenceUnit, TranscriptCue

SPACE_RE = re.compile(r"\s+")
SENTENCE_END_RE = re.compile(r"[.!?。！？…]+[\"')\]]*$")


def split_long_cues(cues: list[TranscriptCue], max_sentence_sec: float) -> list[TranscriptCue]:
    split: list[TranscriptCue] = []
    for cue in cues:
        duration = cue.end - cue.start
        words = cue.text.split()
        if duration > max_sentence_sec and len(words) < 2:
            split.append(TranscriptCue(cue.start, min(cue.end, cue.start + max_sentence_sec), cue.text))
            continue
        if duration <= max_sentence_sec or len(words) < 2:
            split.append(cue)
            continue

        chunk_count = max(1, int(duration // max_sentence_sec) + 1)
        words_per_chunk = max(1, (len(words) + chunk_count - 1) // chunk_count)
        chunk_duration = duration / chunk_count
        for idx in range(chunk_count):
            chunk_words = words[idx * words_per_chunk:(idx + 1) * words_per_chunk]
            if not chunk_words:
                continue
            chunk_start = cue.start + idx * chunk_duration
            chunk_end = cue.end if idx == chunk_count - 1 else cue.start + (idx + 1) * chunk_duration
            split.append(TranscriptCue(chunk_start, chunk_end, " ".join(chunk_words)))
    return split


def cues_to_sentence_units(
    cues: list[TranscriptCue],
    phrase_gap_sec: float,
    max_sentence_sec: float,
    min_sentence_sec: float,
) -> list[SentenceUnit]:
    cues = split_long_cues(cues, max_sentence_sec)
    units: list[SentenceUnit] = []
    words: list[str] = []
    start: float | None = None
    end: float | None = None

    def flush() -> None:
        nonlocal words, start, end
        if start is None or end is None or not words:
            words, start, end = [], None, None
            return
        text = SPACE_RE.sub(" ", " ".join(words)).strip()
        if text and end > start:
            if end - start >= min_sentence_sec or not units:
                units.append(SentenceUnit(start=start, end=end, text=text))
            else:
                prev = units.pop()
                units.append(SentenceUnit(prev.start, end, SPACE_RE.sub(" ", f"{prev.text} {text}").strip()))
        words, start, end = [], None, None

    for cue in cues:
        if start is not None and end is not None:
            gap = cue.start - end
            duration = end - start
            projected_duration = cue.end - start
            if gap >= phrase_gap_sec or duration >= max_sentence_sec or projected_duration > max_sentence_sec:
                flush()

        if start is None:
            start = cue.start
        words.append(cue.text)
        end = cue.end

        duration = end - start
        if SENTENCE_END_RE.search(cue.text) and duration >= min_sentence_sec:
            flush()
        elif duration >= max_sentence_sec:
            flush()

    flush()
    return units
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_sentence_grouper.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/sentence_grouper.py backend/tests/segmentation/test_sentence_grouper.py
git commit -m "feat: add sentence grouper"
```

---

## Task 5: Aligner (align câu ↔ VAD + fallback chỉ-VAD)

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/aligner.py`
- Test: `backend/tests/segmentation/test_aligner.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_aligner.py`:
```python
from app.modules.audio_pipeline.application.segmentation.aligner import (
    align_units_to_vad,
    vad_only_segments,
)
from app.modules.audio_pipeline.application.segmentation.types import SentenceUnit, SpeechRegion


def test_align_refines_boundary_when_close():
    units = [SentenceUnit(1.0, 2.0, "xin chao")]
    regions = [SpeechRegion(0.9, 2.1)]
    segs = align_units_to_vad(units, regions, duration=10.0, pad_sec=0.0,
                              merge_gap_sec=0.5, min_segment_sec=0.3, boundary_slack_sec=0.5)
    assert len(segs) == 1
    assert segs[0].vad_status == "aligned"
    assert segs[0].start == 0.9 and segs[0].end == 2.1
    assert segs[0].text == "xin chao"


def test_align_no_overlap_keeps_unit_bounds():
    units = [SentenceUnit(1.0, 2.0, "xin chao")]
    regions = [SpeechRegion(5.0, 6.0)]
    segs = align_units_to_vad(units, regions, duration=10.0, pad_sec=0.0,
                              merge_gap_sec=0.5, min_segment_sec=0.3, boundary_slack_sec=0.5)
    assert segs[0].vad_status == "no_overlap"
    assert segs[0].start == 1.0 and segs[0].end == 2.0


def test_vad_only_segments_chunks_long_region():
    regions = [SpeechRegion(0.0, 5.0)]
    segs = vad_only_segments(regions, duration=5.0, pad_sec=0.0,
                             min_segment_sec=0.3, max_segment_sec=2.0)
    assert len(segs) == 3
    assert all(s.text == "" and s.transcript_status == "missing" for s in segs)
    assert all(s.vad_status == "speech_region" for s in segs)
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_aligner.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement (port + đổi sang trả `AlignedSegment`)**

`backend/app/modules/audio_pipeline/application/segmentation/aligner.py`:
```python
from __future__ import annotations

from app.modules.audio_pipeline.application.segmentation.types import (
    AlignedSegment,
    SentenceUnit,
    SpeechRegion,
)


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge_regions(regions: list[SpeechRegion], max_gap_sec: float) -> list[SpeechRegion]:
    if not regions:
        return []
    ordered = sorted(regions, key=lambda r: r.start)
    merged = [ordered[0]]
    for region in ordered[1:]:
        previous = merged[-1]
        if region.start - previous.end <= max_gap_sec:
            merged[-1] = SpeechRegion(previous.start, max(previous.end, region.end))
        else:
            merged.append(region)
    return merged


def align_units_to_vad(
    units: list[SentenceUnit],
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    merge_gap_sec: float,
    min_segment_sec: float,
    boundary_slack_sec: float,
) -> list[AlignedSegment]:
    segments: list[AlignedSegment] = []
    for unit in units:
        overlapping = [
            region for region in vad_regions
            if overlap_seconds(unit.start, unit.end, region.start, region.end) > 0.0
        ]
        overlapping = merge_regions(overlapping, merge_gap_sec)
        if overlapping:
            vad_start = min(r.start for r in overlapping)
            vad_end = max(r.end for r in overlapping)
            start = vad_start if abs(vad_start - unit.start) <= boundary_slack_sec else unit.start
            end = vad_end if abs(vad_end - unit.end) <= boundary_slack_sec else unit.end
            vad_status = "aligned"
        else:
            start, end, vad_status = unit.start, unit.end, "no_overlap"

        start = max(0.0, start - pad_sec)
        end = min(duration, end + pad_sec)
        if end - start < min_segment_sec:
            continue
        segments.append(AlignedSegment(start, end, unit.text, "ready", vad_status))
    return segments


def vad_only_segments(
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    min_segment_sec: float,
    max_segment_sec: float,
) -> list[AlignedSegment]:
    segments: list[AlignedSegment] = []
    for region in vad_regions:
        start = max(0.0, region.start - pad_sec)
        end = min(duration, region.end + pad_sec)
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + max_segment_sec) if max_segment_sec > 0 else end
            if chunk_end - cursor >= min_segment_sec:
                segments.append(AlignedSegment(cursor, chunk_end, "", "missing", "speech_region"))
            cursor = chunk_end
    return segments
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_aligner.py -v
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/aligner.py backend/tests/segmentation/test_aligner.py
git commit -m "feat: add transcript-vad aligner"
```

---

## Task 6: Segment writer (cắt WAV + ghi TXT)

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/segment_writer.py`
- Test: `backend/tests/segmentation/test_segment_writer.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_segment_writer.py`:
```python
import wave

from app.modules.audio_pipeline.application.segmentation.segment_writer import (
    cut_wav_segment,
    write_text,
)


def test_cut_wav_segment_length(make_wav, tmp_path):
    src = make_wav(seconds=2.0)
    dst = tmp_path / "out" / "seg.wav"
    cut_wav_segment(src, dst, start_sec=0.5, end_sec=1.5)
    assert dst.exists()
    with wave.open(str(dst), "rb") as r:
        assert r.getframerate() == 16000
        # ~1.0s @ 16k = ~16000 frames
        assert abs(r.getnframes() - 16000) <= 2


def test_write_text(tmp_path):
    p = tmp_path / "a" / "b.txt"
    write_text(p, "xin chao")
    assert p.read_text(encoding="utf-8") == "xin chao"
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_segment_writer.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement (port từ script offline)**

`backend/app/modules/audio_pipeline/application/segmentation/segment_writer.py`:
```python
from __future__ import annotations

import wave
from pathlib import Path


def cut_wav_segment(src: Path, dst: Path, start_sec: float, end_sec: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as reader:
        params = reader.getparams()
        sample_rate = reader.getframerate()
        total_frames = reader.getnframes()
        start_frame = max(0, min(total_frames, int(round(start_sec * sample_rate))))
        end_frame = max(start_frame, min(total_frames, int(round(end_sec * sample_rate))))
        reader.setpos(start_frame)
        frames = reader.readframes(end_frame - start_frame)

    with wave.open(str(dst), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_segment_writer.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/segment_writer.py backend/tests/segmentation/test_segment_writer.py
git commit -m "feat: add segment writer"
```

---

## Task 7: VAD gRPC client

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/vad_grpc_client.py`
- Test: `backend/tests/segmentation/test_vad_grpc_client.py`

**Bối cảnh:** Client stream từng chunk 64ms qua Triton model `vad`, đọc output `SIGNAL` = chuỗi byte-encoded dict `{"signal_type": "SPEAKING"|"QUIET", "signal_at": <float giây>}`. Ráp transition thành `SpeechRegion`. Test inject một `client_factory` giả → không cần server thật.

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_vad_grpc_client.py`:
```python
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vad_grpc_client import TritonVadClient


def _cfg() -> SegmentationConfig:
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45,
        pad_sec=0.1, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
    )


class _FakeResult:
    def __init__(self, signals):
        self._signals = signals

    def as_numpy(self, name):
        assert name == "SIGNAL"
        return [str(s).encode("utf-8") for s in self._signals]


class _FakeClient:
    """Trả SPEAKING ở lần infer đầu, QUIET ở lần infer cuối."""

    def __init__(self, url, verbose=False):
        self.calls = 0

    def infer(self, model_name, inputs, sequence_id, sequence_start, sequence_end):
        self.calls += 1
        if sequence_start:
            return _FakeResult([{"signal_type": "SPEAKING", "signal_at": 0.20}])
        if sequence_end:
            return _FakeResult([{"signal_type": "QUIET", "signal_at": 0.90}])
        return _FakeResult([])


def test_detect_regions_builds_region(make_wav):
    wav = make_wav(seconds=1.0)  # 16k -> ~16 chunks of 64ms
    client = TritonVadClient(url="fake:8001", config=_cfg(), client_factory=_FakeClient)
    duration, regions = client.detect_regions(wav)
    assert round(duration, 2) == 1.0
    assert len(regions) == 1
    assert regions[0].start == 0.20 and regions[0].end == 0.90


def test_open_region_closed_at_duration(make_wav):
    wav = make_wav(seconds=1.0)

    class _OnlySpeaking(_FakeClient):
        def infer(self, model_name, inputs, sequence_id, sequence_start, sequence_end):
            if sequence_start:
                return _FakeResult([{"signal_type": "SPEAKING", "signal_at": 0.10}])
            return _FakeResult([])

    client = TritonVadClient(url="fake:8001", config=_cfg(), client_factory=_OnlySpeaking)
    duration, regions = client.detect_regions(wav)
    assert len(regions) == 1
    assert regions[0].start == 0.10
    assert round(regions[0].end, 2) == 1.0
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_vad_grpc_client.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`backend/app/modules/audio_pipeline/application/segmentation/vad_grpc_client.py`:
```python
from __future__ import annotations

import random
import uuid
import wave
from ast import literal_eval
from pathlib import Path
from typing import Callable

import numpy as np

from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion


def _default_client_factory(url: str, verbose: bool = False):
    # Lazy-import để API startup không cần tritonclient.
    import tritonclient.grpc as grpcclient

    return grpcclient.InferenceServerClient(url=url, verbose=verbose)


class TritonVadClient:
    def __init__(
        self,
        url: str,
        config: SegmentationConfig,
        client_factory: Callable[..., object] = _default_client_factory,
    ) -> None:
        self.url = url
        self.config = config
        self._client_factory = client_factory

    def _build_inputs(self, data: np.ndarray, sess_id: str, sample_rate: int) -> list:
        import tritonclient.grpc as grpcclient

        data = data.astype(np.int16).reshape([1, -1])
        in_audio = grpcclient.InferInput("INPUT", data.shape, "INT16")
        in_sess = grpcclient.InferInput("SESSION", [1, 1], "BYTES")
        in_rate = grpcclient.InferInput("RATE", [1, 1], "INT16")
        in_thr = grpcclient.InferInput("THRESHOLD", [1, 1], "FP16")
        in_vol = grpcclient.InferInput("VOLUME", [1, 1], "FP16")
        in_start = grpcclient.InferInput("START_SECS", [1, 1], "FP16")
        in_stop = grpcclient.InferInput("STOP_SECS", [1, 1], "FP16")

        in_audio.set_data_from_numpy(data)
        in_sess.set_data_from_numpy(np.array([[f"{sess_id}"]], dtype=np.bytes_))
        in_rate.set_data_from_numpy(np.array([[sample_rate]], dtype=np.int16))
        in_thr.set_data_from_numpy(np.array([[self.config.threshold]], dtype=np.float16))
        in_vol.set_data_from_numpy(np.array([[self.config.min_volume]], dtype=np.float16))
        in_start.set_data_from_numpy(np.array([[self.config.start_secs]], dtype=np.float16))
        in_stop.set_data_from_numpy(np.array([[self.config.stop_secs]], dtype=np.float16))
        return [in_audio, in_sess, in_rate, in_thr, in_vol, in_start, in_stop]

    def detect_regions(self, wav_path: Path) -> tuple[float, list[SpeechRegion]]:
        with wave.open(str(wav_path), "rb") as reader:
            sample_rate = reader.getframerate()
            total_frames = reader.getnframes()
            duration = total_frames / sample_rate if sample_rate else 0.0
            frames_per_chunk = max(1, int(self.config.chunk_ms * sample_rate / 1000))

            client = self._client_factory(url=self.url, verbose=False)
            seq_id = random.randint(1, 1_000_000)
            sess_id = str(uuid.uuid4())
            first = True
            regions: list[SpeechRegion] = []
            open_start: float | None = None
            pos = 0

            while pos < total_frames:
                frames = reader.readframes(frames_per_chunk)
                pos += frames_per_chunk
                end = pos >= total_frames
                data = np.frombuffer(frames, dtype=np.int16)
                if data.size < frames_per_chunk:
                    data = np.pad(data, (0, frames_per_chunk - data.size))

                inputs = self._build_inputs(data, sess_id, sample_rate)
                result = client.infer(
                    model_name="vad",
                    inputs=inputs,
                    sequence_id=seq_id,
                    sequence_start=first,
                    sequence_end=end,
                )
                first = False
                for raw in result.as_numpy("SIGNAL"):
                    payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    signal = literal_eval(payload)
                    at = float(signal["signal_at"])
                    if signal["signal_type"] == "SPEAKING" and open_start is None:
                        open_start = at
                    elif signal["signal_type"] == "QUIET" and open_start is not None:
                        regions.append(SpeechRegion(start=open_start, end=at))
                        open_start = None

            if open_start is not None:
                regions.append(SpeechRegion(start=open_start, end=duration))

        return duration, regions
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_vad_grpc_client.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/vad_grpc_client.py backend/tests/segmentation/test_vad_grpc_client.py
git commit -m "feat: add triton vad grpc client"
```

---

## Task 8: ASR adapter (faster-whisper, fallback)

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/asr_adapter.py`
- Test: `backend/tests/segmentation/test_asr_adapter.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_asr_adapter.py`:
```python
from app.modules.audio_pipeline.application.segmentation.asr_adapter import FasterWhisperAdapter


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append((audio, language))
        return [_FakeSegment(" xin "), _FakeSegment("chao ")], {"language": language}


def test_transcribe_joins_and_forces_vietnamese(tmp_path):
    fake = _FakeModel()
    adapter = FasterWhisperAdapter(model_name="tiny", device="cpu", model=fake)
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")  # nội dung không quan trọng vì model bị fake
    text = adapter.transcribe(wav)
    assert text == "xin chao"
    assert fake.calls[0][1] == "vi"


def test_model_lazy_built_once(tmp_path, monkeypatch):
    built = {"count": 0}

    def fake_builder(self):
        built["count"] += 1
        return _FakeModel()

    monkeypatch.setattr(FasterWhisperAdapter, "_build_model", fake_builder)
    adapter = FasterWhisperAdapter(model_name="tiny", device="cpu")
    wav = tmp_path / "seg.wav"
    wav.write_bytes(b"RIFF")
    adapter.transcribe(wav)
    adapter.transcribe(wav)
    assert built["count"] == 1
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_asr_adapter.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`backend/app/modules/audio_pipeline/application/segmentation/asr_adapter.py`:
```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AsrAdapter(Protocol):
    def transcribe(self, wav_path: Path) -> str: ...


class FasterWhisperAdapter:
    """ASR fallback dùng faster-whisper, ép ngôn ngữ tiếng Việt. Model load lười 1 lần."""

    def __init__(self, model_name: str = "large-v3", device: str = "cuda", model: object | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self._model = model

    def _build_model(self):
        from faster_whisper import WhisperModel

        compute_type = "float16" if self.device == "cuda" else "int8"
        try:
            return WhisperModel(self.model_name, device=self.device, compute_type=compute_type)
        except Exception:
            # Không có GPU/driver -> rơi về CPU.
            return WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def _get_model(self):
        if self._model is None:
            self._model = self._build_model()
        return self._model

    def transcribe(self, wav_path: Path) -> str:
        model = self._get_model()
        segments, _info = model.transcribe(str(wav_path), language="vi")
        return " ".join(seg.text.strip() for seg in segments).strip()
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_asr_adapter.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/asr_adapter.py backend/tests/segmentation/test_asr_adapter.py
git commit -m "feat: add faster-whisper asr adapter"
```

---

## Task 9: Segment service (orchestrate 1 video)

**Files:**
- Create: `backend/app/modules/audio_pipeline/application/segmentation/segment_service.py`
- Test: `backend/tests/segmentation/test_segment_service.py`

**Bối cảnh:** `segment_video` nhận 1 processed row + injected `vad_client` + `asr_adapter` + config + output dirs, quyết định đường VTT vs ASR, cắt WAV/ghi TXT, trả `list[dict]` (manifest rows). Inject dependency để test bằng fake.

- [ ] **Step 1: Viết test thất bại**

`backend/tests/segmentation/test_segment_service.py`:
```python
from app.modules.audio_pipeline.application.segmentation.segment_service import segment_video
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion


def _cfg():
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45,
        pad_sec=0.0, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
    )


class _FakeVad:
    def __init__(self, regions, duration):
        self._regions, self._duration = regions, duration

    def detect_regions(self, wav_path):
        return self._duration, list(self._regions)


class _FakeAsr:
    def transcribe(self, wav_path):
        return "loi asr"


VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
xin chao cac ban.
"""


def test_vtt_path_produces_segment(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["transcript_source"] == "vtt"
    assert rows[0]["text"] == "xin chao cac ban."
    assert rows[0]["segment_id"] == "yt_vid__sent000001"
    assert (tmp_path / "segments" / "b1" / "yt_vid" / "yt_vid__sent000001.wav").exists()
    assert (tmp_path / "segments" / "b1" / "yt_vid" / "yt_vid__sent000001.txt").read_text(encoding="utf-8") == "xin chao cac ban."


def test_asr_fallback_when_no_vtt(make_wav, tmp_path):
    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": ""}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 1.0)], 2.0), asr_adapter=_FakeAsr(),
        config=_cfg(), segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 1
    assert rows[0]["transcript_source"] == "asr"
    assert rows[0]["text"] == "loi asr"
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/segmentation/test_segment_service.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`backend/app/modules/audio_pipeline/application/segmentation/segment_service.py`:
```python
from __future__ import annotations

from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.aligner import (
    align_units_to_vad,
    vad_only_segments,
)
from app.modules.audio_pipeline.application.segmentation.asr_adapter import AsrAdapter
from app.modules.audio_pipeline.application.segmentation.segment_writer import (
    cut_wav_segment,
    write_text,
)
from app.modules.audio_pipeline.application.segmentation.sentence_grouper import cues_to_sentence_units
from app.modules.audio_pipeline.application.segmentation.types import AlignedSegment, SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vtt_parser import parse_youtube_vtt


class VadClient:  # giao diện tối thiểu để type-hint
    def detect_regions(self, wav_path: Path): ...


def _has_usable_vtt(subtitle_path: str) -> bool:
    if not subtitle_path:
        return False
    path = Path(subtitle_path)
    return path.exists() and path.is_file() and path.suffix.lower() == ".vtt"


def segment_video(
    processed_row: dict,
    *,
    vad_client: VadClient,
    asr_adapter: AsrAdapter,
    config: SegmentationConfig,
    segments_root: Path,
    batch_name: str,
) -> list[dict]:
    audio_id = processed_row["audio_id"]
    video_id = processed_row.get("video_id", "")
    wav_path = Path(processed_row["audio_file_path"])
    subtitle_path = processed_row.get("subtitle_file_path", "")

    duration, regions = vad_client.detect_regions(wav_path)

    use_vtt = _has_usable_vtt(subtitle_path)
    transcript_source = "vtt"
    if use_vtt:
        cues = parse_youtube_vtt(Path(subtitle_path))
        units = cues_to_sentence_units(
            cues, config.phrase_gap_sec, config.sentence_max_sec, config.sentence_min_sec
        )
        aligned: list[AlignedSegment] = align_units_to_vad(
            units, regions, duration, config.pad_sec, config.merge_gap_sec,
            config.min_segment_sec, config.boundary_slack_sec,
        )
        if not aligned:  # có VTT nhưng không ráp được -> rơi về VAD-only + ASR
            use_vtt = False

    if not use_vtt:
        transcript_source = "asr"
        aligned = vad_only_segments(
            regions, duration, config.pad_sec, config.min_segment_sec, config.sentence_max_sec
        )

    out_dir = segments_root / batch_name / audio_id
    rows: list[dict] = []
    for index, seg in enumerate(aligned, start=1):
        segment_id = f"{audio_id}__sent{index:06d}"
        seg_wav = out_dir / f"{segment_id}.wav"
        seg_txt = out_dir / f"{segment_id}.txt"
        cut_wav_segment(wav_path, seg_wav, seg.start, seg.end)

        text = seg.text
        transcript_status = seg.transcript_status
        if transcript_source == "asr":
            text = asr_adapter.transcribe(seg_wav).strip()
            transcript_status = "ready" if text else "missing"
        write_text(seg_txt, text)

        rows.append({
            "audio_id": audio_id,
            "video_id": video_id,
            "segment_id": segment_id,
            "segment_file": str(seg_wav.resolve()),
            "transcript_file": str(seg_txt.resolve()),
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "duration": round(seg.end - seg.start, 3),
            "text": text,
            "transcript_source": transcript_source,
            "transcript_status": transcript_status,
            "vad_status": seg.vad_status,
            "source_url": processed_row.get("source_url", ""),
            "title": processed_row.get("title", ""),
        })
    return rows
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/segmentation/test_segment_service.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/segmentation/segment_service.py backend/tests/segmentation/test_segment_service.py
git commit -m "feat: add segment orchestration service"
```

---

## Task 10: Service methods `segment_and_label` + `build_segment_metadata`

**Files:**
- Modify: `backend/app/modules/audio_pipeline/application/pipeline_service.py` (thêm 2 method vào `AudioPipelineService`, dòng cuối class)
- Test: `backend/tests/test_pipeline_service_segments.py`

**Bối cảnh:** 2 method mới đặt sau `generate_metadata`. `segment_and_label` build config từ `settings`, tạo `TritonVadClient` + `FasterWhisperAdapter` (lazy), gọi `segment_video` cho từng row. `build_segment_metadata` ghi `labels.csv` + `labels.jsonl`. Test override `_build_segment_dependencies` để inject fake.

- [ ] **Step 1: Viết test thất bại**

`backend/tests/test_pipeline_service_segments.py`:
```python
import json

from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService
from app.modules.audio_pipeline.application.segmentation.types import SpeechRegion


class _FakeVad:
    def detect_regions(self, wav_path):
        return 2.0, [SpeechRegion(0.0, 1.0)]


class _FakeAsr:
    def transcribe(self, wav_path):
        return "loi asr"


def test_segment_and_label_and_metadata(make_wav, tmp_path, monkeypatch):
    service = AudioPipelineService()
    monkeypatch.setattr(service, "segments_dir", tmp_path / "segments")
    monkeypatch.setattr(service, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(
        service, "_build_segment_dependencies",
        lambda: (_FakeVad(), _FakeAsr()),
    )

    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": "",
    }]
    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    assert len(seg_rows) == 1
    assert seg_rows[0]["transcript_source"] == "asr"

    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")
    assert manifest.exists()
    jsonl = manifest.with_suffix(".jsonl")
    assert jsonl.exists()
    first = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert first["segment_id"] == "yt_vid__sent000001"
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/test_pipeline_service_segments.py -v
```
Expected: FAIL (`AttributeError: ... has no attribute 'segments_dir'` hoặc `segment_and_label`).

- [ ] **Step 3a: Thêm `segments_dir` vào `__init__`**

Trong `pipeline_service.py`, `AudioPipelineService.__init__` (dòng ~152-156), thêm dòng cuối:
```python
        self.segments_dir = ensure_dir(settings.segments_dir)
```

- [ ] **Step 3b: Thêm 2 method + import**

Đầu file `pipeline_service.py`, sau các import hiện có, thêm:
```python
from app.modules.audio_pipeline.application.segmentation.asr_adapter import FasterWhisperAdapter
from app.modules.audio_pipeline.application.segmentation.segment_service import segment_video
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vad_grpc_client import TritonVadClient
```

Cuối class `AudioPipelineService` (sau `generate_metadata`), thêm:
```python
    def _build_segmentation_config(self) -> SegmentationConfig:
        return SegmentationConfig(
            chunk_ms=settings.vad_chunk_ms,
            threshold=settings.vad_threshold,
            min_volume=settings.vad_min_volume,
            start_secs=settings.vad_start_secs,
            stop_secs=settings.vad_stop_secs,
            sentence_max_sec=settings.sentence_max_sec,
            sentence_min_sec=settings.sentence_min_sec,
            phrase_gap_sec=settings.phrase_gap_sec,
            pad_sec=settings.segment_pad_sec,
            min_segment_sec=settings.segment_min_sec,
            boundary_slack_sec=settings.segment_boundary_slack_sec,
            merge_gap_sec=settings.segment_merge_gap_sec,
        )

    def _build_segment_dependencies(self):
        # Tách riêng để test có thể inject fake VAD/ASR.
        config = self._build_segmentation_config()
        vad_client = TritonVadClient(url=settings.vad_grpc_url, config=config)
        asr_adapter = FasterWhisperAdapter(model_name=settings.asr_model, device=settings.asr_device)
        return vad_client, asr_adapter

    def segment_and_label(
        self,
        processed_rows: list[dict[str, str]],
        job_id: int | None = None,
        batch_name: str | None = None,
    ) -> list[dict]:
        config = self._build_segmentation_config()
        vad_client, asr_adapter = self._build_segment_dependencies()
        batch = batch_name or "batch_001"
        all_rows: list[dict] = []
        for index, row in enumerate(processed_rows):
            current_url = row.get("source_url", "")
            remaining_urls = [
                item.get("source_url", "").strip()
                for item in processed_rows[index + 1:]
                if item.get("source_url", "").strip()
            ]
            try:
                logger.info("step=segment_and_label | url=%s", current_url)
                rows = segment_video(
                    row,
                    vad_client=vad_client,
                    asr_adapter=asr_adapter,
                    config=config,
                    segments_root=self.segments_dir,
                    batch_name=batch,
                )
                if not rows:
                    logger.warning("step=segment_and_label | url=%s | no_segments", current_url)
                all_rows.extend(rows)
            except Exception as exc:
                logger.exception(
                    "step=segment_and_label | url=%s | error=%s",
                    current_url,
                    format_function_error("segment_and_label", exc),
                )
                raise BatchAbortError(
                    step="segment_and_label",
                    failed_url=current_url,
                    remaining_urls=remaining_urls,
                    cause=exc,
                ) from exc
        logger.info("step=segment_and_label")
        return all_rows

    def build_segment_metadata(
        self,
        segment_rows: list[dict],
        job_id: int | None = None,
        batch_name: str | None = None,
    ) -> Path:
        batch = batch_name or "batch_001"
        fieldnames = [
            "audio_id", "video_id", "segment_id", "segment_file", "transcript_file",
            "start", "end", "duration", "text", "transcript_source",
            "transcript_status", "vad_status", "source_url", "title",
        ]
        csv_path = self.metadata_dir / f"{batch}_segments.csv"

        existing = read_csv(csv_path)
        merged: dict[str, dict] = {row.get("segment_id", f"row_{i}"): row for i, row in enumerate(existing)}
        for row in segment_rows:
            merged[row["segment_id"]] = {key: row.get(key, "") for key in fieldnames}

        write_csv(csv_path, fieldnames, merged.values())

        jsonl_path = csv_path.with_suffix(".jsonl")
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in merged.values():
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        logger.info("step=build_segment_metadata")
        return csv_path
```

(`json`, `Path`, `read_csv`, `write_csv`, `BatchAbortError`, `format_function_error`, `logger` đã được import sẵn ở đầu `pipeline_service.py`.)

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/test_pipeline_service_segments.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/pipeline_service.py backend/tests/test_pipeline_service_segments.py
git commit -m "feat: add segment_and_label and build_segment_metadata service methods"
```

---

## Task 11: Workflow graph — thay node translation/metadata bằng segment

**Files:**
- Modify: `backend/app/modules/audio_pipeline/application/workflow.py`
- Test: `backend/tests/test_workflow_graph.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/test_workflow_graph.py`:
```python
from app.modules.audio_pipeline.application import workflow


def test_graph_has_segment_nodes_not_translation():
    nodes = set(workflow.audio_pipeline_graph.get_graph().nodes.keys())
    assert "segment_and_label" in nodes
    assert "build_segment_metadata" in nodes
    assert "build_translations" not in nodes
    assert "build_metadata" not in nodes
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/test_workflow_graph.py -v
```
Expected: FAIL (`build_translations` vẫn còn / `segment_and_label` chưa có).

- [ ] **Step 3: Sửa `workflow.py`**

Trong `PipelineState`, thay 3 field `translation_rows`/`metadata_path`/`translation_path` bằng:
```python
    segment_rows: list[dict]
    segments_manifest_path: str
```

Xóa 2 hàm `build_translations` và `build_metadata`. Thêm 2 hàm:
```python
def segment_and_label(state: PipelineState) -> PipelineState:
    mark_step_started(state, "segment_and_label")
    segment_rows = service.segment_and_label(
        state.get("processed_rows", []),
        job_id=state.get("job_id"),
        batch_name=state["batch_name"],
    )
    logger.info("step=segment_and_label")
    return {"current_step": "segment_and_label", "segment_rows": segment_rows}


def build_segment_metadata(state: PipelineState) -> PipelineState:
    mark_step_started(state, "build_segment_metadata")
    manifest_path = service.build_segment_metadata(
        state.get("segment_rows", []),
        job_id=state.get("job_id"),
        batch_name=state["batch_name"],
    )
    logger.info("step=build_segment_metadata")
    return {"current_step": "build_segment_metadata", "segments_manifest_path": str(manifest_path)}
```

Sửa `build_graph()`:
```python
def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("validate_urls", validate_urls)
    graph.add_node("crawl_audio", crawl_audio)
    graph.add_node("normalize_audio", normalize_audio)
    graph.add_node("segment_and_label", segment_and_label)
    graph.add_node("build_segment_metadata", build_segment_metadata)
    graph.set_entry_point("validate_urls")
    graph.add_edge("validate_urls", "crawl_audio")
    graph.add_edge("crawl_audio", "normalize_audio")
    graph.add_edge("normalize_audio", "segment_and_label")
    graph.add_edge("segment_and_label", "build_segment_metadata")
    graph.add_edge("build_segment_metadata", END)
    return graph.compile()
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/test_workflow_graph.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/workflow.py backend/tests/test_workflow_graph.py
git commit -m "feat: swap workflow to segment-level nodes"
```

---

## Task 12: Worker mapping — đọc `segments_manifest_path`

**Files:**
- Modify: `backend/app/modules/audio_pipeline/application/worker.py:87-90`
- Test: `backend/tests/test_worker_mapping.py`

- [ ] **Step 1: Viết test thất bại**

`backend/tests/test_worker_mapping.py`:
```python
from app.modules.audio_pipeline.application.worker import _map_state_to_job_paths


def test_map_state_uses_segments_manifest():
    paths = _map_state_to_job_paths({"segments_manifest_path": "/data/metadata/b1_segments.csv"})
    assert paths["metadata_path"] == "/data/metadata/b1_segments.csv"
    assert paths["manifest_path"] == "/data/metadata/b1_segments.csv"
    assert paths["output_path"] == "/data/metadata/b1_segments.csv"
    assert paths["translation_path"] is None


def test_map_state_handles_missing():
    paths = _map_state_to_job_paths({})
    assert paths["metadata_path"] is None
    assert paths["translation_path"] is None
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

```bash
cd backend
uv run pytest tests/test_worker_mapping.py -v
```
Expected: FAIL (`ImportError: cannot import name '_map_state_to_job_paths'`).

- [ ] **Step 3: Thêm helper + dùng trong worker**

Trong `worker.py`, thêm hàm (trên `enqueue_pipeline_job`):
```python
def _map_state_to_job_paths(latest_state: object) -> dict[str, str | None]:
    # Map state cuối của graph sang các cột path của PipelineJob.
    manifest = latest_state.get("segments_manifest_path") if isinstance(latest_state, dict) else None
    return {
        "manifest_path": manifest,
        "metadata_path": manifest,
        "output_path": manifest,
        "translation_path": None,
    }
```

Thay block dòng 87-90 hiện tại:
```python
                job.manifest_path = None
                job.metadata_path = latest_state.get("metadata_path") if isinstance(latest_state, dict) else None
                job.translation_path = latest_state.get("translation_path") if isinstance(latest_state, dict) else None
                job.output_path = job.metadata_path
```
bằng:
```python
                paths = _map_state_to_job_paths(latest_state)
                job.manifest_path = paths["manifest_path"]
                job.metadata_path = paths["metadata_path"]
                job.translation_path = paths["translation_path"]
                job.output_path = paths["output_path"]
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

```bash
cd backend
uv run pytest tests/test_worker_mapping.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/audio_pipeline/application/worker.py backend/tests/test_worker_mapping.py
git commit -m "feat: map segments manifest path to job in worker"
```

---

## Task 13: Integration smoke test (graph thật + fake VAD/ASR)

**Files:**
- Test: `backend/tests/test_integration_segment_pipeline.py`

**Bối cảnh:** Chạy `service.segment_and_label` → `build_segment_metadata` end-to-end với WAV thật (silence) + fake VAD + (đường VTT, không cần ASR). Đảm bảo các module ráp đúng với nhau.

- [ ] **Step 1: Viết test**

`backend/tests/test_integration_segment_pipeline.py`:
```python
import csv

from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService
from app.modules.audio_pipeline.application.segmentation.types import SpeechRegion

VTT = """WEBVTT

00:00:00.000 --> 00:00:01.000
cau mot.

00:00:01.200 --> 00:00:02.000
cau hai.
"""


class _FakeVad:
    def detect_regions(self, wav_path):
        return 2.0, [SpeechRegion(0.0, 1.0), SpeechRegion(1.2, 2.0)]


class _FakeAsr:
    def transcribe(self, wav_path):
        return "khong dung"


def test_end_to_end_vtt_path(make_wav, tmp_path, monkeypatch):
    service = AudioPipelineService()
    monkeypatch.setattr(service, "segments_dir", tmp_path / "segments")
    monkeypatch.setattr(service, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(service, "_build_segment_dependencies", lambda: (_FakeVad(), _FakeAsr()))

    wav = make_wav(seconds=2.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    processed_rows = [{
        "audio_id": "yt_vid", "video_id": "vid", "title": "t", "source_url": "u",
        "audio_file_path": str(wav), "subtitle_file_path": str(vtt),
    }]

    seg_rows = service.segment_and_label(processed_rows, batch_name="b1")
    manifest = service.build_segment_metadata(seg_rows, batch_name="b1")

    with manifest.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {r["text"] for r in rows} == {"cau mot.", "cau hai."}
    assert all(r["transcript_source"] == "vtt" for r in rows)
    for r in rows:
        assert (tmp_path / "segments" / "b1" / "yt_vid" / f"{r['segment_id']}.wav").exists()
```

- [ ] **Step 2: Chạy toàn bộ test**

```bash
cd backend
uv run pytest -v
```
Expected: tất cả test PASS (bao gồm integration mới).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_integration_segment_pipeline.py
git commit -m "test: add end-to-end segment pipeline smoke test"
```

---

## Task 14: Cập nhật `.env.example` + docs ngắn

**Files:**
- Modify: `.env.example` (nếu có; nếu không, tạo)
- Modify: `README.md` (mục workflow)

- [ ] **Step 1: Thêm biến mới vào `.env.example`**

Thêm khối:
```bash
# Segment-level pipeline
VAD_GRPC_URL=127.0.0.1:8001
VAD_THRESHOLD=0.7
VAD_MIN_VOLUME=0.6
VAD_START_SECS=0.1
VAD_STOP_SECS=0.45
SEGMENTS_DIR=data/processed/segments
SENTENCE_MAX_SEC=12.0
SENTENCE_MIN_SEC=0.3
PHRASE_GAP_SEC=0.45
SEGMENT_PAD_SEC=0.1
SEGMENT_MIN_SEC=0.3
ASR_MODEL=large-v3
ASR_DEVICE=cuda
```

- [ ] **Step 2: Cập nhật mục "6. Workflow hien tai" trong `README.md`**

Đổi chuỗi step thành:
```text
validate_urls
-> crawl_audio
-> normalize_audio
-> segment_and_label
-> build_segment_metadata
```
Thêm 1 đoạn: output là segment WAV + transcript TXT per câu + `data/metadata/<batch>_segments.csv/.jsonl`; VAD chạy qua Triton gRPC (`VAD_GRPC_URL`), thiếu phụ đề thì ASR fallback (`faster-whisper`).

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document segment-level pipeline config and workflow"
```

---

## Hoàn tất

- [ ] **Chạy lại toàn bộ test**

```bash
cd backend
uv run pytest -v
```
Expected: tất cả PASS.

- [ ] **(Tùy chọn) Smoke thật với Triton server đang chạy + 1 URL** — cần `docker run ... vad-server` (xem `VAD/README.md`) và `.env` trỏ `VAD_GRPC_URL` đúng. Không bắt buộc cho việc merge code; chỉ để kiểm chứng đường gRPC thật.

---

## Ghi chú thực thi

- **VAD server phải online** khi chạy job thật (không phải khi chạy unit test — test dùng fake).
- **faster-whisper** lần đầu sẽ tải model về (`ASR_MODEL`); chỉ kích hoạt khi có video thiếu VTT.
- Không chạy migration DB; tái dùng cột `manifest_path`/`metadata_path`/`output_path` sẵn có.
- Tất cả commit nằm trên branch `feat/segment-level-pipeline` trong repo `external_repos/VSF-audio-pipeline`.
