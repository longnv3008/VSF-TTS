"""Shared helpers for the offline pipeline entry-point scripts.

Small utilities used by both ``end_to_end_pipeline.py`` and
``segment_youtube_audio_with_vad_transcript.py``. Kept here so the two
scripts share a single implementation instead of duplicating it.
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path


def make_vad_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        sample_rate=args.sample_rate,
        chunk_ms=args.chunk_ms,
        model_chunk_ms=args.model_chunk_ms,
        context_ms=args.context_ms,
        reset_duration=args.reset_duration,
        threshold=args.threshold,
        negative_threshold=args.negative_threshold,
        min_volume=args.min_volume,
        start_secs=args.start_secs,
        stop_secs=args.stop_secs,
        merge_gap_secs=args.merge_gap_secs,
        min_speech_secs=args.min_speech_secs,
        refine_boundaries=args.refine_boundaries,
        refine_energy_db_below_peak=args.refine_energy_db_below_peak,
        refine_energy_min_rms=args.refine_energy_min_rms,
        refine_search_pad_ms=args.refine_search_pad_ms,
        refine_pad_ms=args.refine_pad_ms,
        refine_min_speech_ms=args.refine_min_speech_ms,
        refine_max_gap_ms=args.refine_max_gap_ms,
    )


def build_ffmpeg_cmd(
    src: Path,
    dst: Path,
    sample_rate: int,
    ffmpeg_bin: str,
    *,
    loudnorm: bool = False,
    loudnorm_i: float = -16.0,
    loudnorm_tp: float = -1.5,
    loudnorm_lra: float = 11.0,
) -> list[str]:
    """Dựng argv ffmpeg cho clean. ``loudnorm`` bật -> thêm chuẩn hóa âm lượng EBU R128."""
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn"]
    if loudnorm:
        cmd += ["-af", f"loudnorm=I={loudnorm_i}:TP={loudnorm_tp}:LRA={loudnorm_lra}"]
    cmd += ["-ac", "1", "-ar", str(sample_rate), "-sample_fmt", "s16", str(dst)]
    return cmd


def cut_wav_segment(src: Path, dst: Path, start_sec: float, end_sec: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as reader:
        params = reader.getparams()
        sample_rate = reader.getframerate()
        total_frames = reader.getnframes()
        start_frame = max(0, min(total_frames, int(round(start_sec * sample_rate))))
        end_frame = max(start_frame, min(total_frames, int(round(end_sec * sample_rate))))
        reader.setpos(start_frame)
        frames = reader.readframes(end_frame - start_frame)

    with wave.open(str(dst), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)
