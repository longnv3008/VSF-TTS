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
