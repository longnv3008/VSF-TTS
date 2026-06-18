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
