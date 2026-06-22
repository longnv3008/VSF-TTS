"""Đo mức nhiễu nền (noise floor) của file audio raw để route Demucs.

``auto`` mode: file nhiễu cao -> tách vocal bằng Demucs; file sạch -> chỉ ffmpeg.
Raw crawl thường là webm/m4a/opus (không phải WAV) nên dùng ffmpeg ``astats``
thay vì đọc PCM trực tiếp. Hàm parse tách riêng để test không cần ffmpeg.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# astats in ra "Noise floor dB: <value>" cho từng kênh rồi Overall (match cuối = overall).
# Giá trị có thể là số thực hoặc "-inf" (file im lặng tuyệt đối).
_NOISE_FLOOR_RE = re.compile(r"Noise floor dB:\s*(-?inf|-?\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_noise_floor_db(stderr: str) -> float:
    """Lấy noise floor (dB) từ stderr của ffmpeg astats. Match cuối = section Overall."""
    matches = _NOISE_FLOOR_RE.findall(stderr)
    if not matches:
        raise ValueError("astats output missing 'Noise floor dB'")
    return float(matches[-1])


def measure_noise_floor_db(audio_path: Path, ffmpeg_bin: str = "ffmpeg") -> float:
    """Chạy ffmpeg astats trên ``audio_path`` (bất kỳ format) -> noise floor dB.

    Raise nếu ffmpeg không có hoặc không parse được -> caller fallback an toàn.
    """
    if not shutil.which(ffmpeg_bin):
        raise RuntimeError("ffmpeg not available for noise probe")
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-i",
        str(audio_path),
        "-af",
        "astats",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return parse_noise_floor_db(result.stderr)
