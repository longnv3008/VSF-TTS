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
NON_TIMESTAMP_TAG_RE = re.compile(r"<(?!/?\d{2}:\d{2}(?::\d{2})?\.\d{3}>)[^>]+>")
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


def extract_timed_text(raw_line: str, cue_start: float) -> list[tuple[float, str]]:
    sanitized = html.unescape(NON_TIMESTAMP_TAG_RE.sub("", raw_line))
    timed_text: list[tuple[float, str]] = []
    cursor_time = cue_start
    cursor = 0

    for match in INLINE_TIMESTAMP_RE.finditer(sanitized):
        segment = SPACE_RE.sub(" ", sanitized[cursor:match.start()]).strip()
        if segment:
            timed_text.append((cursor_time, segment))
        cursor_time = parse_timecode(match.group()[1:-1])
        cursor = match.end()

    tail = SPACE_RE.sub(" ", sanitized[cursor:]).strip()
    if tail:
        timed_text.append((cursor_time, tail))
    return timed_text


def trim_timed_text_prefix(
    timed_text: list[tuple[float, str]],
    prefix: str,
) -> list[tuple[float, str]]:
    prefix_words = prefix.split()
    if not prefix_words:
        return timed_text

    words_left = list(prefix_words)
    trimmed: list[tuple[float, str]] = []
    for start, chunk in timed_text:
        chunk_words = chunk.split()
        if not words_left:
            trimmed.append((start, chunk))
            continue

        consume = 0
        while (
            consume < len(chunk_words)
            and words_left
            and normalize_for_compare(chunk_words[consume]) == normalize_for_compare(words_left[0])
        ):
            consume += 1
            words_left.pop(0)

        if consume == len(chunk_words):
            continue
        if consume > 0:
            remaining = " ".join(chunk_words[consume:]).strip()
            if remaining:
                trimmed.append((start, remaining))
            continue
        trimmed.append((start, chunk))
    return trimmed


def _cue_timed_spans(cue: TranscriptCue) -> list[tuple[float, float, str]]:
    if cue.timed_text:
        spans: list[tuple[float, float, str]] = []
        for index, (chunk_start, chunk_text) in enumerate(cue.timed_text):
            chunk_end = cue.end if index == len(cue.timed_text) - 1 else cue.timed_text[index + 1][0]
            if chunk_end > chunk_start and chunk_text.strip():
                spans.append((chunk_start, chunk_end, chunk_text.strip()))
        return spans

    if cue.text.strip():
        return [(cue.start, cue.end, cue.text.strip())]
    return []


def extract_text_in_range(
    cues: list[TranscriptCue],
    start: float,
    end: float,
) -> str:
    parts: list[str] = []
    previous_norm = ""
    for cue in cues:
        if cue.end <= start or cue.start >= end:
            continue
        for span_start, span_end, chunk_text in _cue_timed_spans(cue):
            if span_end <= start or span_start >= end:
                continue
            normalized = normalize_for_compare(chunk_text)
            if normalized and normalized != previous_norm:
                parts.append(chunk_text)
                previous_norm = normalized
    return SPACE_RE.sub(" ", " ".join(parts)).strip()


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
        timed_lines: list[list[tuple[float, str]]] = []
        for raw_line in raw_lines:
            cleaned = clean_caption_text(raw_line)
            if not cleaned:
                continue
            if cleaned_lines and normalize_for_compare(cleaned) == normalize_for_compare(cleaned_lines[-1]):
                continue
            cleaned_lines.append(cleaned)
            timed_lines.append(extract_timed_text(raw_line, start))

        if previous_visible and len(cleaned_lines) > 1:
            if normalize_for_compare(cleaned_lines[0]) == normalize_for_compare(previous_visible):
                cleaned_lines = cleaned_lines[1:]
                timed_lines = timed_lines[1:]

        if not cleaned_lines:
            continue

        caption_text = SPACE_RE.sub(" ", " ".join(cleaned_lines)).strip()
        timed_text = [item for line in timed_lines for item in line]
        if previous_visible:
            stripped = strip_known_prefix(caption_text, previous_visible)
            if stripped != caption_text:
                timed_text = trim_timed_text_prefix(timed_text, previous_visible)
            caption_text = stripped

        if caption_text and normalize_for_compare(caption_text) != normalize_for_compare(previous_visible):
            cues.append(TranscriptCue(start=start, end=end, text=caption_text, timed_text=tuple(timed_text)))

        previous_visible = cleaned_lines[-1]

    return cues
