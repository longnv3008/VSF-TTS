from __future__ import annotations

import re

from app.modules.audio_pipeline.application.segmentation.types import SentenceUnit, TranscriptCue, WordToken

SPACE_RE = re.compile(r"\s+")
SENTENCE_END_RE = re.compile(r"[.!?。！？…]+[\"')\]]*$")
PHRASE_END_RE = re.compile(r"[,;:]$")


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
