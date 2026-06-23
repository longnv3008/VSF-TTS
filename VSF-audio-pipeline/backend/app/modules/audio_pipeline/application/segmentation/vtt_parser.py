from __future__ import annotations

import html
import re
from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.types import TranscriptCue, WordToken

TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})"
)
INLINE_TIMESTAMP_RE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>|<\d{2}:\d{2}\.\d{3}>")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
INLINE_TS_CAPTURE_RE = re.compile(r"<((?:\d{2}:)?\d{2}:\d{2}\.\d{3})>")


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


def _extract_cue_words(line: str, cue_start: float, cue_end: float) -> list[WordToken]:
    """Words from ONE timestamped caption line: the head (text before the first ts)
    shares cue_start, each `<ts>` marks the next word. Assumes YouTube's
    one-timestamped-line-per-cue rolling format. A cue with a second timestamped line
    would give that line's head cue_start too — words are still captured, only that
    head's start time is early; harmless for sentence-level cutting downstream.
    """
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
