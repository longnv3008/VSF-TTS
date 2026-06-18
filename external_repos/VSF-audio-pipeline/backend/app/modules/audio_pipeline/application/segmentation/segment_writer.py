from __future__ import annotations

import wave
from pathlib import Path


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
