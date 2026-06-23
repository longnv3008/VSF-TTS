# Word-timestamp sentence segmentation — design

**Date:** 2026-06-23
**Status:** approved
**Scope:** Improve VTT→segment cutting so labels are complete sentences, not mid-clause
fragments. Independent; ships alone behind a config flag (default ON, auto-fallback).

## Problem

Manual WER review shows labels are often truncated or meaningless ("câu cụt ngủn / không
có nghĩa"), e.g. a single sentence

> sinh sống ở các bản Mò O Ồ Ồ, bản Ón và bản Yên Hợp.

gets chopped into two segments `"m o ồ ồ, bản"` + `"án và bản Yên hợp."` — cut in the
middle of the clause "bản án". WER improved (separate effort) but choppy cuts remain.

### Root cause (3 layers)

1. `vtt_parser.parse_youtube_vtt` discards the inline **word-level timestamps** present in
   YouTube rolling captions (`<00:00:15.120><c> chào</c>`, stripped at
   `vtt_parser.py:39`). Only approximate, overlapping rolling-cue start/end survive.
2. `sentence_grouper.cues_to_sentence_units` flushes **hard on elapsed TIME** at
   `sentence_max_sec` (default 8.0s), regardless of clause boundary
   (`sentence_grouper.py:67`, `:78`). A slowly-spoken proper name ("Mò O Ồ Ồ" over ~8s)
   gets isolated; the next clause "bản án" gets split across the flush.
3. Sentence-end punctuation flush (`. ! ? …`) loses to the time cap: the cap pre-empts the
   flush before the sentence can close.

## Goal

Cut at sentence boundaries using precise word timing. Operator constraint: TTS training
tolerates segments up to ~12–15s, so **most sentences stay whole**; only sentences longer
than the cap are split, at a natural phrase boundary (comma, else longest pause), never
mid-clause.

## Approach

Add a parallel word-timestamp path; keep the existing cue-level parser + grouper untouched
as fallback (rollback-friendly, no deletion). Wire-up auto-falls-back when a VTT carries no
inline timestamps.

```
parse_youtube_vtt_words(vtt) → list[WordToken]      # NEW (alongside parse_youtube_vtt)
words_to_sentence_units(...)  → list[SentenceUnit]   # NEW (alongside cues_to_sentence_units)
align_units_to_vad(...)       → AlignedSegment        # UNCHANGED
```

## New type — `types.py`

```python
@dataclass(frozen=True)
class WordToken:
    text: str
    start: float
    end: float
```

## New unit — `vtt_parser.parse_youtube_vtt_words(path) -> list[WordToken]`

Reconstruct a single word→time stream across all cues:

- Per cue, take only the **timestamped tail line** (the line containing inline
  `<hh:mm:ss.mmm><c> word</c>` markers — the line currently being "typed").
- Text before the first marker = the first new word(s); their `start` = cue.start.
- Each subsequent word's `start` = its leading inline timestamp.
- Word `end` = next word's `start`; last word in the cue → cue.end.
- The tiny 10ms display-only cues (plain text, no inline ts) contribute no new words and
  are skipped — rolling-caption dedup happens naturally (carried prefix has no ts).
- **Fallback inside a cue:** a cue with words but no inline ts → distribute
  cue.start→cue.end evenly across its words (keeps the stream usable for mixed VTTs).

`parse_youtube_vtt` (cue-level) is kept unchanged for the fallback path.

## New unit — `sentence_grouper.words_to_sentence_units(words, max_sentence_sec, min_sentence_sec, phrase_gap_sec) -> list[SentenceUnit]`

Walk the word stream, accumulate into a sentence buffer. `start` = first word's start,
`end` = last word's end.

Flush priority:

1. **Sentence end (primary):** current word matches `SENTENCE_END_RE` (`. ! ? …`) and
   buffer duration ≥ `min_sentence_sec` → flush.
2. **Over cap (split):** buffer duration would exceed `max_sentence_sec` → split.
   - Split at the **last comma** (`,`) inside the buffer if the resulting head ≥
     `min_sentence_sec`;
   - else split at the **longest inter-word pause** in the buffer (operator choice);
   - else (no usable point) cut at the current word (last resort).
   - The remainder carries forward into the next sentence.

A long pause inside a sentence does **not** force a flush on its own (avoids reintroducing
choppy cuts) — `phrase_gap_sec` only ranks candidate split points when over the cap. A
fragment shorter than `min_sentence_sec` is merged into the previous unit (same rule as the
existing grouper).

`cues_to_sentence_units` is kept unchanged for the fallback path.

## Wiring — `segment_video` (`segment_service.py`)

```python
if config.segmentation_word_split:
    words = parse_youtube_vtt_words(Path(subtitle_path))
    if words:
        units = words_to_sentence_units(
            words, config.sentence_max_sec, config.sentence_min_sec, config.phrase_gap_sec
        )
    else:
        units = cues_to_sentence_units(...)   # current call, unchanged
else:
    units = cues_to_sentence_units(...)
```

Empty word stream (VTT has zero inline timestamps anywhere) → fall back to the cue path.
Downstream `align_units_to_vad` + `_apply_vtt_overlap` are unchanged; precise units mean
VAD now only nudges edges.

## Config

`SegmentationConfig` (`types.py`) + Settings (`core/config.py`), threaded through
`pipeline_service.py` like existing flags:

- `segmentation_word_split: bool = True` — default ON; auto-fallback when no word ts.

## Edge cases

- Manual VTT / no inline ts → per-cue even distribution, or whole-file fallback to the cue
  path. No crash, degrades to current behavior.
- Numbers ending a sentence ("...năm 2026.") carry a period → correctly flush. Mid-sentence
  number-with-period false positives are rare in VN news text and already possible today.
- First word of a cue (no leading inline ts) correctly inherits cue.start.

## Tests

- `test_vtt_parser.py`: `parse_youtube_vtt_words` yields correct `(text, start, end)` per
  word from a rolling-caption snippet; skips 10ms display cues; first-word-inherits-start;
  even-distribution fallback for a no-ts cue.
- `test_sentence_grouper.py`: `words_to_sentence_units` groups to sentence end; keeps a
  clause whole (regression fixture from the real "bản án" case → "bản án" in one unit);
  splits an over-cap no-comma sentence at the longest pause; merges sub-min fragment;
  precise start/end.
- Existing `cues_to_sentence_units` / `parse_youtube_vtt` tests stay green (fallback path
  preserved) — regression guard for old behavior.
- `segment_service`: flag OFF → cue path used (regression guard).

## Verification

- `uv run pytest tests/` green (Windows env recipe: memory `run-backend-tests-windows`).
- Re-run pipeline on `HLpp7ECTC5g` (clear recipe: memory `clear-batch-and-retest-recipe` —
  delete `pipeline_job_urls` row + segment outputs), inspect review UI: no mid-clause cuts,
  labels read as complete sentences.
