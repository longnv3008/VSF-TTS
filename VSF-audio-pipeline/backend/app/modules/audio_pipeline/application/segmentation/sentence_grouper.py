from __future__ import annotations

import re

from app.modules.audio_pipeline.application.segmentation.types import SentenceUnit, TranscriptCue

SPACE_RE = re.compile(r"\s+")
SENTENCE_END_RE = re.compile(r"[.!?。！？…]+[\"')\]]*$")


def _is_sentence_start_char(char: str) -> bool:
    return char.isalpha() and char == char.upper()


def _split_text_on_sentence_boundaries(text: str) -> list[str]:
    normalized = SPACE_RE.sub(" ", text).strip()
    if not normalized:
        return []

    parts: list[str] = []
    start = 0
    index = 0
    while index < len(normalized):
        if normalized[index] not in ".!?。！？…":
            index += 1
            continue

        boundary = index + 1
        while boundary < len(normalized) and normalized[boundary] in "\"')]}":
            boundary += 1
        lookahead = boundary
        while lookahead < len(normalized) and normalized[lookahead].isspace():
            lookahead += 1

        if lookahead < len(normalized) and _is_sentence_start_char(normalized[lookahead]):
            part = normalized[start:boundary].strip()
            if part:
                parts.append(part)
            start = lookahead
            index = lookahead
            continue

        index = boundary

    tail = normalized[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def split_sentence_cues(cues: list[TranscriptCue]) -> list[TranscriptCue]:
    split: list[TranscriptCue] = []
    for cue in cues:
        parts = _split_text_on_sentence_boundaries(cue.text)
        if len(parts) < 2:
            split.append(cue)
            continue

        token_starts: list[float] = []
        for chunk_start, chunk_text in cue.timed_text:
            token_starts.extend([chunk_start] * len(chunk_text.split()))

        if len(token_starts) == len(cue.text.split()):
            cursor = 0
            for index, part in enumerate(parts):
                part_token_count = len(part.split())
                part_start = token_starts[cursor]
                cursor += part_token_count
                part_end = cue.end if cursor >= len(token_starts) else token_starts[cursor]
                split.append(TranscriptCue(start=part_start, end=part_end, text=part))
            continue

        weights = [max(1, len(part.split())) for part in parts]
        total_weight = sum(weights)
        cursor_time = cue.start
        for index, (part, weight) in enumerate(zip(parts, weights)):
            if index == len(parts) - 1:
                part_end = cue.end
            else:
                part_end = cursor_time + ((cue.end - cue.start) * weight / total_weight)
            split.append(TranscriptCue(start=cursor_time, end=part_end, text=part))
            cursor_time = part_end
    return split


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
    cues = split_sentence_cues(cues)
    cues = split_long_cues(cues, max_sentence_sec)
    units: list[SentenceUnit] = []
    words: list[str] = []
    start: float | None = None
    end: float | None = None
    hard_max_sentence_sec = max_sentence_sec * 1.5 if max_sentence_sec > 0 else 0.0

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
            if gap >= phrase_gap_sec or (hard_max_sentence_sec > 0 and duration >= hard_max_sentence_sec):
                flush()

        if start is None:
            start = cue.start
        words.append(cue.text)
        end = cue.end

        duration = end - start
        if SENTENCE_END_RE.search(cue.text) and duration >= min_sentence_sec:
            flush()
        elif hard_max_sentence_sec > 0 and duration >= hard_max_sentence_sec:
            flush()

    flush()
    return units
