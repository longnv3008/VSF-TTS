# WER gate normalize — design

**Date:** 2026-06-23
**Status:** approved
**Scope:** Sub-project #1 of the WER-reduction effort (decomposed). Independent; ships alone.

## Problem

Runtime WER gate (`wer_gate.segment_wer`) compares VTT (reference) vs ASR (hypothesis)
at segment level. On music/sung audio the measured WER is inflated by formatting noise:
VTT markup (`[âm nhạc]`, `>>`) and ad-lib runs (`la la la`, `oh oh`) count as token
errors. Manual review (memory: `wer-review-result-yzwertg7uvs`) showed the gate over-flags
at ~83% while VTT is only ~25% off vs a human listener. Gate is OFF by default partly
because the measurement is untrustworthy.

The full Vietnamese normalize already exists in two places — `eval/wer/vsf_wer/normalize.py`
(offline, with non-lyric blocklist) and `wer_canonical.normalize` (backend, markup-strip +
ad-lib collapse). But `wer_gate.segment_wer` uses the weakest tokenizer of the three: only
lowercase + punctuation strip. No markup removal, no ad-lib collapse.

## Goal

Gate measures WER on fully normalized text so spurious formatting/non-lyric errors stop
inflating it. No change to gate policy, threshold, default-OFF, or review routing.

## Change

1. `wer_gate.segment_wer` calls `wer_canonical.normalize(text, level="normalized",
   keep_diacritics=True)` on both reference and hypothesis before tokenizing + Levenshtein.
2. Import `normalize` (and reuse `tokens`) from `wer_canonical` — same backend, same
   `segmentation` package. Drop the local `_tokens` / `_PUNCT_RE`.
3. Keep the `ref empty -> 0.0` rule (can't gate without a reference).

## Non-goals (YAGNI)

- No non-lyric blocklist (needs a data file; defer until proven necessary).
- Do not touch `eval/wer` (separate uv project, offline report).
- No change to keep/review decision, threshold, or default-OFF.

## Units / boundaries

`wer_gate` = "measure one segment's WER for the gate". Sole dependency:
`wer_canonical.normalize`. Testable in isolation — no ASR, no pipeline.

## Tests

- Existing `tests/segmentation/test_wer_gate.py` (5 cases, already-clean strings) stay green.
- Add: `"[âm nhạc] xin chào"` vs `"xin chào"` → WER 0.0 (markup stripped).
- Add: ad-lib collapse — `"la la la xin chào"` reference behaves per canonical normalize.
- Add: diacritics preserved (phonemic) — `"lá"` vs `"la"` is still a substitution.

## Verification

`uv run pytest tests/segmentation/test_wer_gate.py` green; full backend suite stays green
(see memory `run-backend-tests-windows` for Windows env recipe).
