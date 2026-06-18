from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SentenceUnit:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float


@dataclass(frozen=True)
class AlignedSegment:
    start: float
    end: float
    text: str
    transcript_status: str  # "ready" | "missing"
    vad_status: str         # "aligned" | "no_overlap" | "speech_region"


@dataclass(frozen=True)
class SegmentationConfig:
    chunk_ms: int
    threshold: float
    min_volume: float
    start_secs: float
    stop_secs: float
    sentence_max_sec: float
    sentence_min_sec: float
    phrase_gap_sec: float
    pad_sec: float
    min_segment_sec: float
    boundary_slack_sec: float
    merge_gap_sec: float
