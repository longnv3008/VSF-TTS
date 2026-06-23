from __future__ import annotations

from dataclasses import dataclass

from app.modules.audio_pipeline.application.segmentation.music_detect import DEFAULT_MUSIC_KEYWORDS


@dataclass(frozen=True)
class TranscriptCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class WordToken:
    text: str
    start: float
    end: float


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
    use_vtt_transcript: bool
    pad_sec: float
    min_segment_sec: float
    boundary_slack_sec: float
    merge_gap_sec: float
    vtt_overlap_sec: float = 0.2
    segmentation_word_split: bool = True
    quality_gate_enabled: bool = False
    quality_gate_min_rms: float = 0.015
    quality_gate_min_peak: float = 0.05
    quality_gate_min_active_ratio: float = 0.35
    quality_gate_chunk_ms: int = 200
    quality_gate_min_tokens_per_sec: float = 0.6
    quality_gate_max_tokens_per_sec: float = 6.0
    quality_gate_long_segment_sec: float = 2.5
    quality_gate_min_tokens_for_long_segment: int = 2
    wer_gate_enabled: bool = False
    wer_gate_max: float = 0.05
    wer_gate_skip_music: bool = True
    wer_gate_music_keywords: tuple[str, ...] = DEFAULT_MUSIC_KEYWORDS
