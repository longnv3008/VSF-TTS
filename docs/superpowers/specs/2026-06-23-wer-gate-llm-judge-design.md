# WER gate — LLM judge corrects ASR hypothesis — design

**Date:** 2026-06-23
**Status:** approved
**Scope:** Sub-project #3 of the WER-reduction effort. Independent; ships alone.

## Problem & framing

The notebook recipes (#3 judge-editor, #4 GFD) assume ASR generates the transcript. This
pipeline does NOT: labels come only from VTT (CLAUDE.md hard rule — "no ASR transcript
fallback"); ASR is used solely as the optional WER gate comparator (off by default). So an
LLM cannot touch the label.

Chosen purpose: the LLM corrects the gate's **ASR hypothesis** (Vietnamese spelling /
homophone errors) before it is compared to the VTT reference, so the gate's measured WER is
closer to the truth and flags fewer good labels. ASR stays a gate-only comparator; the VTT
label is never modified.

Honest ROI: low — the gate is OFF by default and per-segment LLM calls are heavy. This is
strictly opt-in and defaults OFF, so it cannot regress existing behavior.

## New unit: `segmentation/llm_judge.py`

```python
class LlmJudgeAdapter(Protocol):
    def correct(self, text: str) -> str: ...

class NullJudgeAdapter:      # returns text unchanged; default, no network
    def correct(self, text: str) -> str: return text

class OllamaJudgeAdapter:    # HTTP to an Ollama server
    def correct(self, text: str) -> str: ...
```

`OllamaJudgeAdapter` POSTs to Ollama `/api/generate` via httpx (already a transitive dep)
with a conservative prompt: fix Vietnamese spelling/homophone errors, preserve meaning,
return only the corrected sentence; `temperature` 0, `stream` false.

**Fail-open:** any timeout, connection error, non-200, or empty/unparseable response →
return the original `text` and log a warning. The LLM must never block or break the
pipeline. Empty input → return "" without a call.

## Wiring in `segment_video`

- New parameter `judge_adapter: LlmJudgeAdapter = NullJudgeAdapter()`.
- Inside the existing gate block (already guarded by `wer_gate_enabled and not
  skip_wer_gate and quality.keep and text`): after `hyp = asr_adapter.transcribe(seg_wav)`,
  apply `hyp = judge_adapter.correct(hyp)` before `segment_wer(text, hyp)`.
- No new control flow outside the gate block.

## Config

`core/config.py` (Settings) + `segmentation/types.py` (SegmentationConfig) + threaded in
`pipeline_service._build_segmentation_config` / `_build_segment_dependencies`:

- `WER_GATE_LLM_JUDGE_ENABLED: bool = False`
- `WER_GATE_LLM_JUDGE_URL: str = "http://localhost:11434"`
- `WER_GATE_LLM_JUDGE_MODEL: str = "qwen2.5:7b"`
- `WER_GATE_LLM_JUDGE_TIMEOUT: float = 30.0`

`_build_segment_dependencies` returns a judge: `OllamaJudgeAdapter(...)` when enabled, else
`NullJudgeAdapter()`. It is passed through to `segment_video`.

## Tests

- `NullJudgeAdapter.correct` returns input unchanged; empty → "".
- `OllamaJudgeAdapter.correct`: stubbed httpx 200 with a corrected sentence → returns it;
  httpx raises / non-200 → returns original (fail-open); empty input → "" without call.
- `segment_video`: with a fake judge that rewrites the hyp to match the VTT, gate does NOT
  flag (WER 0); without the judge (Null) the same divergent ASR DOES flag. No real HTTP.

## Verification

`uv run pytest tests/` green (new llm_judge + segment_service suites); full backend suite
green (Windows env recipe: memory `run-backend-tests-windows`). Default OFF — no behavior
change unless `WER_GATE_LLM_JUDGE_ENABLED=true`.
