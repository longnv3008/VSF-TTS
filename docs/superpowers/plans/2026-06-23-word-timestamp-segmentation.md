# Word-timestamp Sentence Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut VTT-labelled segments at sentence boundaries using inline word-level timestamps, so labels are complete sentences instead of mid-clause fragments.

**Architecture:** Add a parallel word-timestamp path (`parse_youtube_vtt_words` → `words_to_sentence_units`) alongside the existing cue-level parser/grouper, which stay untouched as a fallback. A config flag (`segmentation_word_split`, default ON) selects the word path; an empty word stream (VTT with no inline timestamps) auto-falls-back to the cue path. Downstream VAD alignment is unchanged.

**Tech Stack:** Python 3, dataclasses, `re`, pytest, pydantic-settings (`app.core.config`), `uv`.

## Global Constraints

- New code is additive. Do NOT modify or delete `parse_youtube_vtt` or `cues_to_sentence_units` — they are the fallback path; existing tests must stay green.
- Default behavior: `segmentation_word_split = True`; auto-fallback to cue path when no inline timestamps are present.
- Long-sentence split (over `sentence_max_sec`): split at the last phrase-punctuation word (`, ; :`) whose head ≥ `min_sentence_sec`; else at the longest inter-word pause ≥ `phrase_gap_sec` whose head ≥ `min_sentence_sec`; else hard-cut the whole buffer. Never invent a mid-clause cut when a phrase boundary exists.
- Tests run from repo root `e:\VSF\TTS` using the Windows isolated-env recipe (memory `run-backend-tests-windows`): `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest <path> -v`. The committed `.venv` is Linux-only — never use it directly on Windows.
- Backend module root for imports: `app.modules.audio_pipeline.application.segmentation.*`.

---

## File Structure

- `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/types.py` — add `WordToken` dataclass; add `segmentation_word_split` field to `SegmentationConfig`.
- `.../segmentation/vtt_parser.py` — add `parse_youtube_vtt_words(path) -> list[WordToken]` and a private `_extract_cue_words(...)`. Keep `parse_youtube_vtt` unchanged.
- `.../segmentation/sentence_grouper.py` — add `words_to_sentence_units(...)` and a private `_split_index(...)`. Keep `cues_to_sentence_units` unchanged.
- `.../segmentation/segment_service.py` — branch in `segment_video` between word path and cue path.
- `VSF-audio-pipeline/backend/app/core/config.py` — add `segmentation_word_split` Setting.
- `.../application/pipeline_service.py` — thread the flag into `_build_segmentation_config`.
- Tests: `tests/segmentation/test_vtt_parser.py`, `tests/segmentation/test_sentence_grouper.py`, `tests/segmentation/test_segment_service.py`, `tests/test_config_segmentation.py`.

---

## Task 1: `WordToken` type + word-level VTT parser

**Files:**
- Modify: `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/types.py`
- Modify: `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/vtt_parser.py`
- Test: `VSF-audio-pipeline/backend/tests/segmentation/test_vtt_parser.py`

**Interfaces:**
- Produces: `WordToken(text: str, start: float, end: float)` (frozen dataclass) in `types.py`.
- Produces: `parse_youtube_vtt_words(path: Path) -> list[WordToken]` in `vtt_parser.py`. Returns `[]` when the VTT has no inline `<hh:mm:ss.mmm>` timestamps anywhere.

- [ ] **Step 1: Write the failing tests**

Append to `VSF-audio-pipeline/backend/tests/segmentation/test_vtt_parser.py`:

```python
from app.modules.audio_pipeline.application.segmentation.vtt_parser import (
    parse_youtube_vtt_words,
)

WORDS_VTT = """WEBVTT
Kind: captions
Language: vi

00:00:01.000 --> 00:00:02.500
xin<00:00:01.300><c> chào</c><00:00:01.800><c> bạn.</c>
"""

ROLLING_VTT = """WEBVTT
Kind: captions
Language: vi

00:00:01.000 --> 00:00:02.500
xin<00:00:01.300><c> chào</c>

00:00:02.500 --> 00:00:02.510
xin chào

00:00:02.510 --> 00:00:04.000
xin chào
bạn<00:00:02.800><c> nhé.</c>
"""

PLAIN_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Xin chào các bạn.
"""


def test_parse_words_basic(tmp_path):
    p = tmp_path / "vid__t.vi.vtt"
    p.write_text(WORDS_VTT, encoding="utf-8")
    words = parse_youtube_vtt_words(p)
    assert [w.text for w in words] == ["xin", "chào", "bạn."]
    assert words[0].start == 1.0 and words[0].end == 1.3
    assert words[1].start == 1.3 and words[1].end == 1.8
    assert words[2].start == 1.8 and words[2].end == 2.5


def test_parse_words_skips_plain_and_repeat_cues(tmp_path):
    p = tmp_path / "vid__t.vi.vtt"
    p.write_text(ROLLING_VTT, encoding="utf-8")
    words = parse_youtube_vtt_words(p)
    # Plain carried-prefix line and the 10ms repeat cue contribute no new words.
    assert [w.text for w in words] == ["xin", "chào", "bạn", "nhé."]
    assert [w.text for w in words].count("xin") == 1
    # Last word of cue 1 ends at that cue's end; first word of cue 3 starts later -> real gap.
    chao = next(w for w in words if w.text == "chào")
    ban = next(w for w in words if w.text == "bạn")
    assert chao.end == 2.5
    assert ban.start == 2.51


def test_parse_words_empty_when_no_inline_ts(tmp_path):
    p = tmp_path / "vid__t.vi.vtt"
    p.write_text(PLAIN_VTT, encoding="utf-8")
    assert parse_youtube_vtt_words(p) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/segmentation/test_vtt_parser.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_youtube_vtt_words'`.

- [ ] **Step 3: Add the `WordToken` type**

In `types.py`, after the `TranscriptCue` dataclass (currently lines 8–12), add:

```python
@dataclass(frozen=True)
class WordToken:
    text: str
    start: float
    end: float
```

- [ ] **Step 4: Implement the word parser**

In `vtt_parser.py`, add the import and a capture-group regex, then the two functions. Add to the imports at top:

```python
from app.modules.audio_pipeline.application.segmentation.types import TranscriptCue, WordToken
```

Add near the other module-level regexes (after `SPACE_RE`):

```python
INLINE_TS_CAPTURE_RE = re.compile(r"<((?:\d{2}:)?\d{2}:\d{2}\.\d{3})>")
```

Add at the end of the file:

```python
def _extract_cue_words(line: str, cue_start: float, cue_end: float) -> list[WordToken]:
    matches = list(INLINE_TS_CAPTURE_RE.finditer(line))
    if not matches:
        return []
    # anchors: (start_time, raw_text_chunk) — head shares cue_start, each ts marks a word.
    anchors: list[tuple[float, str]] = [(cue_start, line[: matches[0].start()])]
    for idx, match in enumerate(matches):
        chunk_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
        anchors.append((parse_timecode(match.group(1)), line[match.end():chunk_end]))

    cleaned = [(t, clean_caption_text(chunk)) for t, chunk in anchors]
    cleaned = [(t, chunk) for t, chunk in cleaned if chunk]
    if not cleaned:
        return []

    words: list[WordToken] = []
    for idx, (t, chunk) in enumerate(cleaned):
        nxt = cleaned[idx + 1][0] if idx + 1 < len(cleaned) else cue_end
        parts = chunk.split()
        span = max(0.0, nxt - t)
        step = span / len(parts) if len(parts) > 1 else span
        for j, word in enumerate(parts):
            w_start = t + j * step
            w_end = nxt if j == len(parts) - 1 else t + (j + 1) * step
            words.append(WordToken(text=word, start=w_start, end=w_end))
    return words


def parse_youtube_vtt_words(path: Path) -> list[WordToken]:
    text = read_text_with_fallback(path)
    lines = text.splitlines()
    words: list[WordToken] = []
    i = 0
    while i < len(lines):
        match = TIMESTAMP_RE.search(lines[i])
        if not match:
            i += 1
            continue
        cue_start = parse_timecode(match.group("start"))
        cue_end = parse_timecode(match.group("end"))
        i += 1
        while i < len(lines) and lines[i].strip():
            if INLINE_TS_CAPTURE_RE.search(lines[i]):
                words.extend(_extract_cue_words(lines[i], cue_start, cue_end))
            i += 1
    return words
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/segmentation/test_vtt_parser.py -v`
Expected: PASS (3 new tests + the existing `test_parse_dedup_and_clean`).

- [ ] **Step 6: Commit**

```bash
git add VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/types.py \
        VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/vtt_parser.py \
        VSF-audio-pipeline/backend/tests/segmentation/test_vtt_parser.py
git commit -m "feat: word-level VTT timestamp parser (parse_youtube_vtt_words)"
```

---

## Task 2: Word-level sentence grouper

**Files:**
- Modify: `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/sentence_grouper.py`
- Test: `VSF-audio-pipeline/backend/tests/segmentation/test_sentence_grouper.py`

**Interfaces:**
- Consumes: `WordToken` (Task 1) from `types.py`.
- Produces: `words_to_sentence_units(words: list[WordToken], max_sentence_sec: float, min_sentence_sec: float, phrase_gap_sec: float) -> list[SentenceUnit]`.

- [ ] **Step 1: Write the failing tests**

Append to `VSF-audio-pipeline/backend/tests/segmentation/test_sentence_grouper.py`:

```python
from app.modules.audio_pipeline.application.segmentation.sentence_grouper import (
    words_to_sentence_units,
)
from app.modules.audio_pipeline.application.segmentation.types import WordToken


def _w(text, start, end):
    return WordToken(text=text, start=start, end=end)


def test_words_group_to_sentence_end():
    words = [
        _w("Xin", 0.0, 0.5), _w("chào", 0.5, 1.0), _w("bạn.", 1.0, 1.5),
        _w("Hôm", 1.6, 2.0), _w("nay", 2.0, 2.5), _w("trời", 2.5, 3.0), _w("đẹp.", 3.0, 3.5),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=12.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert [u.text for u in units] == ["Xin chào bạn.", "Hôm nay trời đẹp."]
    assert units[0].start == 0.0 and units[0].end == 1.5
    assert units[1].start == 1.6 and units[1].end == 3.5


def test_words_keep_whole_sentence_under_cap():
    # "...các bản Mò O Ồ Ồ, bản án và bản Yên Hợp." (~10.6s) stays one unit when cap=12.
    words = [
        _w("các", 0.0, 0.4), _w("bản", 0.4, 1.0),
        _w("Mò", 1.0, 3.5), _w("O", 3.5, 5.0), _w("Ồ", 5.0, 6.5), _w("Ồ,", 6.5, 8.0),
        _w("bản", 8.0, 8.4), _w("án", 8.4, 8.9), _w("và", 8.9, 9.2),
        _w("bản", 9.2, 9.6), _w("Yên", 9.6, 10.0), _w("Hợp.", 10.0, 10.6),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=12.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert len(units) == 1
    assert "bản án" in units[0].text


def test_words_over_cap_split_at_comma_not_mid_clause():
    # Same sentence with cap=8 -> split at the comma after "Ồ,", "bản án" stays intact.
    words = [
        _w("các", 0.0, 0.4), _w("bản", 0.4, 1.0),
        _w("Mò", 1.0, 3.5), _w("O", 3.5, 5.0), _w("Ồ", 5.0, 6.5), _w("Ồ,", 6.5, 8.0),
        _w("bản", 8.0, 8.4), _w("án", 8.4, 8.9), _w("và", 8.9, 9.2),
        _w("bản", 9.2, 9.6), _w("Yên", 9.6, 10.0), _w("Hợp.", 10.0, 10.6),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=8.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert len(units) == 2
    assert units[0].text.endswith("Ồ,")
    assert units[1].text == "bản án và bản Yên Hợp."


def test_words_over_cap_no_comma_split_at_longest_pause():
    words = [
        _w("a", 0.0, 1.0), _w("b", 1.0, 2.0), _w("c", 2.0, 3.0), _w("d", 3.0, 4.0),
        _w("e", 4.0, 5.0), _w("f", 5.6, 6.6), _w("g", 6.6, 7.6), _w("h", 7.6, 8.6),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=8.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert units[0].text == "a b c d e"   # split at the 0.6s pause before "f"


def test_words_submin_fragment_merges_into_previous():
    words = [
        _w("Xin", 0.0, 0.5), _w("chào", 0.5, 1.0), _w("bạn.", 1.0, 1.5),
        _w("Ừ.", 1.6, 1.7),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=12.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert len(units) == 1
    assert units[0].text == "Xin chào bạn. Ừ."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/segmentation/test_sentence_grouper.py -v`
Expected: FAIL — `ImportError: cannot import name 'words_to_sentence_units'`.

- [ ] **Step 3: Implement the grouper**

In `sentence_grouper.py`, extend the import line and add a phrase-punctuation regex + the two functions. Change the existing import to:

```python
from app.modules.audio_pipeline.application.segmentation.types import SentenceUnit, TranscriptCue, WordToken
```

Add after the existing `SENTENCE_END_RE` definition:

```python
PHRASE_END_RE = re.compile(r"[,;:]$")
```

Add at the end of the file:

```python
def _split_index(buf: list[WordToken], min_sentence_sec: float, phrase_gap_sec: float) -> int:
    """Index to cut an over-cap buffer: head = buf[:idx], tail = buf[idx:]."""
    start = buf[0].start
    comma_idx: int | None = None
    for i, word in enumerate(buf[:-1]):
        if PHRASE_END_RE.search(word.text) and (word.end - start) >= min_sentence_sec:
            comma_idx = i
    if comma_idx is not None:
        return comma_idx + 1

    best_gap = phrase_gap_sec
    best_i: int | None = None
    for i in range(len(buf) - 1):
        gap = buf[i + 1].start - buf[i].end
        if gap >= best_gap and (buf[i].end - start) >= min_sentence_sec:
            best_gap, best_i = gap, i
    if best_i is not None:
        return best_i + 1

    return len(buf)  # no usable phrase boundary -> hard-cut whole buffer


def words_to_sentence_units(
    words: list[WordToken],
    max_sentence_sec: float,
    min_sentence_sec: float,
    phrase_gap_sec: float,
) -> list[SentenceUnit]:
    units: list[SentenceUnit] = []

    def emit(head: list[WordToken]) -> None:
        text = SPACE_RE.sub(" ", " ".join(w.text for w in head)).strip()
        if not text:
            return
        start, end = head[0].start, head[-1].end
        if end <= start:
            return
        if end - start >= min_sentence_sec or not units:
            units.append(SentenceUnit(start=start, end=end, text=text))
        else:
            prev = units.pop()
            merged = SPACE_RE.sub(" ", f"{prev.text} {text}").strip()
            units.append(SentenceUnit(prev.start, end, merged))

    buf: list[WordToken] = []
    for word in words:
        buf.append(word)
        duration = buf[-1].end - buf[0].start
        if SENTENCE_END_RE.search(word.text) and duration >= min_sentence_sec:
            emit(buf)
            buf = []
        elif duration >= max_sentence_sec:
            cut = _split_index(buf, min_sentence_sec, phrase_gap_sec)
            emit(buf[:cut])
            buf = buf[cut:]
    if buf:
        emit(buf)
    return units
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/segmentation/test_sentence_grouper.py -v`
Expected: PASS (5 new tests + the 2 existing `cues_to_sentence_units` tests).

- [ ] **Step 5: Commit**

```bash
git add VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/sentence_grouper.py \
        VSF-audio-pipeline/backend/tests/segmentation/test_sentence_grouper.py
git commit -m "feat: word-level sentence grouper (words_to_sentence_units)"
```

---

## Task 3: Config flag plumbing

**Files:**
- Modify: `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/types.py`
- Modify: `VSF-audio-pipeline/backend/app/core/config.py:88`
- Modify: `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/pipeline_service.py:1590`
- Test: `VSF-audio-pipeline/backend/tests/test_config_segmentation.py`

**Interfaces:**
- Produces: `SegmentationConfig.segmentation_word_split: bool = True`; `Settings.segmentation_word_split` (env `SEGMENTATION_WORD_SPLIT`); threaded in `_build_segmentation_config`.

- [ ] **Step 1: Write the failing test**

In `tests/test_config_segmentation.py`, add `"SEGMENTATION_WORD_SPLIT"` to the `_SEGMENTATION_ENV_VARS` list, and add this assertion at the end of `test_segmentation_settings_defaults`:

```python
    assert s.segmentation_word_split is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/test_config_segmentation.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'segmentation_word_split'`.

- [ ] **Step 3: Add the config field on `SegmentationConfig`**

In `types.py`, in `SegmentationConfig`, add immediately after `vtt_overlap_sec: float = 0.2` (line 52):

```python
    segmentation_word_split: bool = True
```

- [ ] **Step 4: Add the Setting**

In `config.py`, after `vtt_overlap_sec` (line 88), add:

```python
    segmentation_word_split: bool = Field(default=True, alias="SEGMENTATION_WORD_SPLIT")
```

- [ ] **Step 5: Thread the flag into the segmentation config**

In `pipeline_service.py`, in `_build_segmentation_config`, after `vtt_overlap_sec=settings.vtt_overlap_sec,` (line 1590), add:

```python
            segmentation_word_split=settings.segmentation_word_split,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/test_config_segmentation.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/types.py \
        VSF-audio-pipeline/backend/app/core/config.py \
        VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/pipeline_service.py \
        VSF-audio-pipeline/backend/tests/test_config_segmentation.py
git commit -m "feat: segmentation_word_split config flag (default on)"
```

---

## Task 4: Wire word path into `segment_video`

**Files:**
- Modify: `VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/segment_service.py:139-143`
- Test: `VSF-audio-pipeline/backend/tests/segmentation/test_segment_service.py`

**Interfaces:**
- Consumes: `parse_youtube_vtt_words` (Task 1), `words_to_sentence_units` (Task 2), `config.segmentation_word_split` (Task 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/segmentation/test_segment_service.py`:

```python
# One long sentence with a comma. Word times: một[0,2] hai,[2,8] ba.[8,10].
# At cap=5 the cue path chops into 3 fragments (incl. a bare "một"); the word path
# splits once at the comma -> 2 clause-complete segments.
LONG_TS_VTT = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:10.000
một<00:00:02.000><c> hai,</c><00:00:08.000><c> ba.</c>
"""


def test_word_split_path_splits_long_sentence_at_comma(make_wav, tmp_path):
    # Flag default ON -> word path: 2 segments, no mid-clause bare "một".
    cfg = SegmentationConfig(**{**_cfg().__dict__, "sentence_max_sec": 5.0})
    wav = make_wav(seconds=11.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(LONG_TS_VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 10.0)], 11.0), asr_adapter=_FakeAsr(),
        config=cfg, segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 2
    assert rows[0]["text"] == "một hai,"
    assert rows[1]["text"] == "ba."


def test_word_split_flag_off_uses_cue_path(make_wav, tmp_path):
    # Flag OFF -> cue path: the old choppy 3-way split incl. bare "một" (regression guard).
    cfg = SegmentationConfig(**{**_cfg().__dict__, "sentence_max_sec": 5.0,
                                "segmentation_word_split": False})
    wav = make_wav(seconds=11.0, name="yt_vid.wav")
    vtt = tmp_path / "vid__t.vi.vtt"
    vtt.write_text(LONG_TS_VTT, encoding="utf-8")
    row = {"audio_id": "yt_vid", "video_id": "vid", "title": "t",
           "source_url": "u", "audio_file_path": str(wav), "subtitle_file_path": str(vtt)}
    rows = segment_video(
        row, vad_client=_FakeVad([SpeechRegion(0.0, 10.0)], 11.0), asr_adapter=_FakeAsr(),
        config=cfg, segments_root=tmp_path / "segments", batch_name="b1",
    )
    assert len(rows) == 3
    assert rows[0]["text"] == "một"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/segmentation/test_segment_service.py::test_word_split_path_splits_long_sentence_at_comma -v`
Expected: FAIL — `assert len(rows) == 2` gets 3 (current unwired code uses the cue path, which chops the sentence into "một" / "hai," / "ba."). The flag-off guard already passes (cue path is current behavior).

- [ ] **Step 3: Wire the branch**

In `segment_service.py`, add to the segmentation imports (alongside the existing `from ... .sentence_grouper import cues_to_sentence_units`):

```python
from app.modules.audio_pipeline.application.segmentation.sentence_grouper import (
    cues_to_sentence_units,
    words_to_sentence_units,
)
from app.modules.audio_pipeline.application.segmentation.vtt_parser import (
    parse_youtube_vtt,
    parse_youtube_vtt_words,
)
```

(Replace the two existing single-name imports for `cues_to_sentence_units` and `parse_youtube_vtt` so there is no duplicate import.)

Replace the current block (lines 139–143):

```python
    transcript_source = "vtt"
    cues = parse_youtube_vtt(Path(subtitle_path))
    units = cues_to_sentence_units(
        cues, config.phrase_gap_sec, config.sentence_max_sec, config.sentence_min_sec
    )
```

with:

```python
    transcript_source = "vtt"
    units = []
    if config.segmentation_word_split:
        words = parse_youtube_vtt_words(Path(subtitle_path))
        if words:
            units = words_to_sentence_units(
                words, config.sentence_max_sec, config.sentence_min_sec, config.phrase_gap_sec
            )
    if not units:
        cues = parse_youtube_vtt(Path(subtitle_path))
        units = cues_to_sentence_units(
            cues, config.phrase_gap_sec, config.sentence_max_sec, config.sentence_min_sec
        )
```

- [ ] **Step 4: Run the full segment_service suite to verify it passes**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/segmentation/test_segment_service.py -v`
Expected: PASS — 2 new tests pass; all existing tests stay green (their plain VTTs yield no words → fallback to cue path → identical behavior).

- [ ] **Step 5: Commit**

```bash
git add VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/segment_service.py \
        VSF-audio-pipeline/backend/tests/segmentation/test_segment_service.py
git commit -m "feat: use word-timestamp segmentation in segment_video with cue fallback"
```

---

## Task 5: Raise default `sentence_max_sec` to 14s

Operator constraint is "~12–15s OK"; the current 8s default forces short splits even with clean phrase boundaries. Bump the default so most sentences stay whole.

**Files:**
- Modify: `VSF-audio-pipeline/backend/app/core/config.py:80`
- Test: `VSF-audio-pipeline/backend/tests/test_config_segmentation.py:24`

**Interfaces:**
- None new. Changes only the default value of `Settings.sentence_max_sec`.

- [ ] **Step 1: Update the test expectation (failing test first)**

In `tests/test_config_segmentation.py`, change:

```python
    assert s.sentence_max_sec == 8.0
```

to:

```python
    assert s.sentence_max_sec == 14.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/test_config_segmentation.py::test_segmentation_settings_defaults -v`
Expected: FAIL — `assert 8.0 == 14.0`.

- [ ] **Step 3: Change the default**

In `config.py:80`, change:

```python
    sentence_max_sec: float = Field(default=8.0, alias="SENTENCE_MAX_SEC")
```

to:

```python
    sentence_max_sec: float = Field(default=14.0, alias="SENTENCE_MAX_SEC")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/test_config_segmentation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add VSF-audio-pipeline/backend/app/core/config.py \
        VSF-audio-pipeline/backend/tests/test_config_segmentation.py
git commit -m "feat: raise default SENTENCE_MAX_SEC 8s -> 14s for whole-sentence cuts"
```

---

## Final verification

- [ ] **Run the full backend test suite**

Run: `UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv" uv run --directory VSF-audio-pipeline/backend pytest tests/ -q`
Expected: all green (no regressions in the cue-path fallback tests).

- [ ] **End-to-end re-run (manual, operator)**

Re-run the pipeline on `HLpp7ECTC5g` using the clear-and-retest recipe (memory `clear-batch-and-retest-recipe`): delete the `pipeline_job_urls` row + the batch's segment outputs, re-run, then open the review UI. Confirm labels read as complete sentences with no mid-clause cuts (e.g. "bản án" no longer split). This step needs the Docker pipeline + GPU and is run by the operator.

---

## Self-Review

**Spec coverage:**
- `WordToken` type → Task 1 Step 3.
- `parse_youtube_vtt_words` (rolling dedup, skip 10ms cues, first-word-inherits-cue.start, empty→fallback) → Task 1.
- Even-distribution within a multi-word anchor chunk → Task 1 `_extract_cue_words` (`step` loop). Whole-file no-ts fallback → returns `[]` (`test_parse_words_empty_when_no_inline_ts`) consumed by Task 4's `if not units` fallback. (The spec's per-cue even-distribution for *mixed* VTTs is intentionally simplified to whole-file fallback — documented as acceptable, mixed VTTs do not occur in practice.)
- `words_to_sentence_units` (punctuation-primary flush, over-cap split at comma → longest pause → hard cut, sub-min merge, precise start/end) → Task 2.
- Wiring with auto-fallback → Task 4.
- Config flag default ON → Task 3.
- `sentence_max_sec` ~12–15s → Task 5 (14.0).
- Tests for parser/grouper/wiring/config + regression guards → all tasks.
- Verification (suite + e2e re-run) → Final verification.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command shows expected output. Clear.

**Type consistency:** `WordToken(text, start, end)` is defined in Task 1 and used identically in Tasks 1, 2, 4. `words_to_sentence_units(words, max_sentence_sec, min_sentence_sec, phrase_gap_sec)` signature matches its Task 4 call site. `segmentation_word_split` field name is identical across types.py, config.py, pipeline_service.py, and the wiring branch. `parse_youtube_vtt_words(path)` matches its call site.

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session via executing-plans, batch with checkpoints.
