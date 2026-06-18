from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from app.utils import get_logger

logger = get_logger(__name__)


def _split_command(command: str) -> list[str]:
    # Trên Windows shlex.split mặc định nuốt backslash; dùng posix=False + bỏ quote.
    if os.name == "nt":
        return [tok.strip('"') for tok in shlex.split(command, posix=False)]
    return shlex.split(command)


def separate_vocals(
    input_path: Path,
    out_dir: Path,
    *,
    command: str,
    model: str,
    device: str,
) -> Path:
    """Run Demucs (two-stems vocals) on ``input_path`` and return the vocal WAV.

    Demucs is invoked via a configurable command so it can live in a separate
    torch-enabled env; the backend env does not need torch installed. Separation
    runs on the full-quality raw audio. The vocal stem is downsampled to mono
    16k later by ``normalize_audio``.

    Output layout (Demucs default): ``out_dir/<model>/<input_stem>/vocals.wav``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    vocal = out_dir / model / input_path.stem / "vocals.wav"
    if vocal.exists():
        logger.info("step=vocal_separation | cached | file=%s", vocal)
        return vocal

    cmd = [
        *_split_command(command),
        "--two-stems",
        "vocals",
        "-n",
        model,
        "-d",
        device,
        "-o",
        str(out_dir),
        str(input_path),
    ]
    logger.info("step=vocal_separation | run=%s", " ".join(cmd))
    subprocess.run(cmd, check=True)
    if not vocal.exists():
        raise FileNotFoundError(f"demucs did not produce vocals: {vocal}")
    return vocal
