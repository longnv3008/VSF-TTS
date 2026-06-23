# WER gate — skip music videos (title heuristic) — design

**Date:** 2026-06-23
**Status:** approved
**Scope:** Sub-project #2 of the WER-reduction effort. Independent; ships alone.

## Problem

Manual review (memory `wer-review-result-yzwertg7uvs`, `WER_REVIEW_REPORT.md`) showed the
ASR WER gate over-flags sung/music content: on `yzWeRtg7UVs` the gate measured ~83% while
the VTT label was only ~25% off vs a human listener. Whisper `base` transcribes singing
poorly, so the gate punishes good-enough music labels.

We want music videos to bypass the WER gate so it can be turned on for speech without
nuking music segments.

## Why not text-based detection

A probe over 12 sample VTTs (markup density `[âm nhạc]`/`♪`, ad-lib token ratio) showed the
signal is dead on the target videos: all three reviewed music MVs (`yzWeRtg7UVs`,
`neCmEbI2VWg`, `ixdSsW5n2rI`) have markup_ratio = 0.000 and adlib_ratio ≈ 0 — identical to a
speech video (`aGr2kd7inhk`, "Con gái Quảng Trị nói chuyện"). Lyric VTTs are clean lyric
text, indistinguishable from speech by markup. Text-based auto-detection is not viable.

Video `title` IS available (yt-dlp `entry["title"]` → `processed_row["title"]`), and
separates on the real data ("... Official MV", "... ft. ..." vs "... nói chuyện ...").

## Goal

Detect music videos from their title and skip the WER gate for them. Precision-first:
better to miss a music video (gate still runs; gate is OFF by default anyway) than to
wrongly skip the gate on a speech video.

## New unit: `music_detect.py`

```python
def is_music_title(title: str, *, keywords: tuple[str, ...]) -> bool
```

Casefold the title, return True if any keyword appears as a substring. Pure, no
dependencies, tested in isolation.

Default keywords (precision-first):
`official mv`, `music video`, `lyric`, `lyrics`, `official audio`, ` ft.`, ` feat.`,
`m/v`, `| official`.

## Wiring in `segment_video`

- Compute once per video, before the segment loop:
  `is_music = config.wer_gate_skip_music and is_music_title(processed_row.get("title", ""), config.wer_gate_music_keywords)`
- The gate guard (currently `segment_service.py:193`) gains `and not is_music`.

## Config

In `segmentation/types.py` (`SegmentationConfig`) and `core/config.py` (Settings),
threaded through `pipeline_service.py` like the existing `wer_gate_*`:

- `wer_gate_skip_music: bool = True` — only has effect when the gate is enabled.
- `wer_gate_music_keywords: tuple[str, ...]` = the default list above. **Extensible** so an
  operator can add artist/channel names (e.g. `grey d`, `mck`) to catch bare
  "song - artist" titles that generic keywords miss. This is the escape hatch instead of a
  manual per-video flag.

## Known limitation

Titles like "toidaidot - GREY D" (the very video that motivated this) contain no generic
music keyword, so they are NOT caught by defaults — the operator must add the artist to
`wer_gate_music_keywords`. Accepted: precision-first, and the gate defaults OFF.

## Tests

- `is_music_title`: "... Official MV" / "... ft. ..." / "... Lyrics" → True;
  "Con gái Quảng Trị nói chuyện dễ thương" → False.
- Custom keyword `("grey d",)` → "toidaidot - GREY D" → True.
- `segment_service`: gate enabled + music title → ASR not called, no `wer_gate` flag.
- `segment_service`: gate enabled + `wer_gate_skip_music=False` → gate runs on music
  (regression guard for old behavior).

## Verification

`uv run pytest tests/` green (gate + segment_service suites); full backend suite green
(Windows env recipe: memory `run-backend-tests-windows`).
