from __future__ import annotations

import audioop
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SegmentAudioMetrics:
    rms: float
    peak: float
    active_ratio: float


@dataclass(frozen=True)
class SegmentQualityDecision:
    keep: bool
    label: str
    score: float
    reasons: tuple[str, ...]


def inspect_audio(
    wav_path: Path,
    *,
    active_rms_threshold: float = 0.015,
    chunk_ms: int = 200,
) -> SegmentAudioMetrics:
    with wave.open(str(wav_path), "rb") as reader:
        sample_rate = reader.getframerate()
        sample_width = reader.getsampwidth()
        channels = reader.getnchannels()
        chunk_frames = max(1, int(sample_rate * (chunk_ms / 1000.0)))
        max_value = float((1 << ((8 * sample_width) - 1)) - 1)
        rms_values: list[float] = []
        peak_values: list[float] = []

        while True:
            frames = reader.readframes(chunk_frames)
            if not frames:
                break
            if channels > 1:
                frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
            rms_values.append(audioop.rms(frames, sample_width) / max_value)
            peak_values.append(audioop.max(frames, sample_width) / max_value)

    if not rms_values:
        return SegmentAudioMetrics(rms=0.0, peak=0.0, active_ratio=0.0)

    active_chunks = sum(1 for value in rms_values if value >= active_rms_threshold)
    return SegmentAudioMetrics(
        rms=sum(rms_values) / len(rms_values),
        peak=max(peak_values),
        active_ratio=active_chunks / len(rms_values),
    )


def gate_audio(
    wav_path: Path,
    *,
    min_rms: float,
    min_peak: float,
    min_active_ratio: float,
    chunk_ms: int,
) -> SegmentQualityDecision:
    metrics = inspect_audio(wav_path, active_rms_threshold=min_rms, chunk_ms=chunk_ms)
    score = 1.0
    reasons: list[str] = []

    if metrics.rms < min_rms:
        score -= 0.45
        reasons.append("low_rms")
    if metrics.peak < min_peak:
        score -= 0.25
        reasons.append("low_peak")
    if metrics.active_ratio < min_active_ratio:
        score -= 0.45
        reasons.append("low_active_ratio")

    if reasons:
        label = "needs_review" if score >= 0.5 else "low_quality"
    else:
        label = "speech_clean"

    return SegmentQualityDecision(
        keep=score >= 0.5,
        label=label,
        score=max(0.0, round(score, 3)),
        reasons=tuple(reasons),
    )


def gate_text(
    text: str,
    *,
    duration_sec: float,
    min_tokens_per_sec: float,
    max_tokens_per_sec: float,
    min_tokens_for_long_segment: int,
    long_segment_sec: float,
) -> SegmentQualityDecision:
    cleaned = (text or "").strip()
    if not cleaned:
        return SegmentQualityDecision(
            keep=False,
            label="low_quality",
            score=0.0,
            reasons=("empty_transcript",),
        )

    reasons: list[str] = []
    score = 1.0
    token_count = len(cleaned.split())
    tokens_per_sec = token_count / max(duration_sec, 1e-6)

    if duration_sec >= long_segment_sec and token_count < min_tokens_for_long_segment:
        score -= 0.6
        reasons.append("too_few_tokens_for_duration")
    if tokens_per_sec < min_tokens_per_sec:
        score -= 0.35
        reasons.append("low_token_density")
    if tokens_per_sec > max_tokens_per_sec:
        score -= 0.35
        reasons.append("high_token_density")

    if reasons:
        label = "needs_review" if score >= 0.5 else "low_quality"
    else:
        label = "speech_clean"

    return SegmentQualityDecision(
        keep=score >= 0.5,
        label=label,
        score=max(0.0, round(score, 3)),
        reasons=tuple(reasons),
    )
