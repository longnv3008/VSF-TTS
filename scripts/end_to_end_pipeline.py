"""
End-to-end offline audio pipeline.

Stages:
  1. Optional crawl command: write downloaded audio into --raw-dir.
  2. Optional Demucs (--demucs): separate vocals from the raw audio first.
  3. Clean audio: convert (the vocal stem when --demucs) to mono 16 kHz 16-bit PCM WAV.
  4. VAD: reuse the local VAD implementation to create speech/quiet regions.
  5. Label/export: cut speaking segments and write CSV/JSONL manifests.

This script is intentionally thin around the existing VAD code so a crawler
repo can be plugged in without changing the production VAD implementation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VAD_DIR = PROJECT_ROOT / "VAD"
VAD_MODEL_DIR = VAD_DIR / "models" / "vad" / "1"

sys.path.insert(0, str(VAD_DIR))

from batch_vad import MODEL_DIR, VADModel, run_vad_file  # noqa: E402
from demucs_env import demucs_available, resolve_demucs_cmd, split_command  # noqa: E402


AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".webm",
    ".mp4",
    ".mkv",
}


def _print(msg: str) -> None:
    print(msg, flush=True)


def stable_audio_name(path: Path, root: Path) -> str:
    rel = path.resolve().relative_to(root.resolve())
    stem = "__".join(rel.with_suffix("").parts)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)
    digest = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:8]
    return f"{safe}__{digest}.wav"


def collect_audio_files(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"raw dir does not exist: {raw_dir}")
    files = [
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return sorted(files)


def wav_is_clean(path: Path, sample_rate: int) -> bool:
    try:
        with wave.open(str(path), "rb") as wf:
            return (
                wf.getnchannels() == 1
                and wf.getsampwidth() == 2
                and wf.getframerate() == sample_rate
            )
    except wave.Error:
        return False


def convert_with_ffmpeg(src: Path, dst: Path, sample_rate: int, ffmpeg_bin: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-sample_fmt",
        "s16",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def separate_vocals(raw_files: list[Path], args: argparse.Namespace) -> dict[Path, Path]:
    """Run Demucs on each raw file (native SR), keep only the vocal stem.

    Returns a map raw_path -> vocals.wav. Demucs is invoked via a configurable
    command so it can live in a separate torch-enabled env (keeps the VAD env
    free of torch). Separation runs on the full-quality raw audio; the vocal is
    downsampled to mono 16k later by ``clean_audio_files``.
    """
    cmd_prefix = split_command(args.demucs_cmd)
    vocal_map: dict[Path, Path] = {}
    _print(f"[demucs] separating {len(raw_files)} file(s) with {args.demucs_model} ({args.demucs_device})")

    for src in raw_files:
        out_dir = args.vocals_dir / stable_audio_name(src, args.raw_dir).removesuffix(".wav")
        vocal = out_dir / args.demucs_model / src.stem / "vocals.wav"
        if vocal.exists() and not args.overwrite:
            vocal_map[src] = vocal
            _print(f"[demucs] cached: {src.name} -> {vocal.name}")
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            *cmd_prefix,
            "--two-stems",
            "vocals",
            "-n",
            args.demucs_model,
            "-d",
            args.demucs_device,
            "-o",
            str(out_dir),
            str(src),
        ]
        try:
            subprocess.run(cmd, check=True)
            if not vocal.exists():
                raise FileNotFoundError(f"demucs did not produce vocals: {vocal}")
        except Exception as exc:  # per-file fallback: clean step uses raw for this file
            _print(f"[demucs] FAILED on {src.name}: {type(exc).__name__}: {exc}; using raw audio for this file")
            continue
        vocal_map[src] = vocal
        _print(f"[demucs] separated: {src.name} -> {vocal.name}")

    return vocal_map


def clean_audio_files(args: argparse.Namespace, vocal_map: dict[Path, Path] | None = None) -> list[dict]:
    raw_files = collect_audio_files(args.raw_dir)
    _print(f"[clean] found {len(raw_files)} audio file(s) in {args.raw_dir}")
    cleaned = []

    for src in raw_files:
        # When Demucs is enabled, clean the vocal stem but keep ``src`` (raw) as
        # the manifest source and as the basis for the stable output name.
        source_audio = vocal_map.get(src, src) if vocal_map else src
        dst = args.clean_dir / stable_audio_name(src, args.raw_dir)
        if dst.exists() and not args.overwrite:
            status = "cached"
        elif source_audio.suffix.lower() == ".wav" and wav_is_clean(source_audio, args.sample_rate):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_audio, dst)
            status = "copied"
        else:
            convert_with_ffmpeg(source_audio, dst, args.sample_rate, args.ffmpeg)
            status = "converted"

        if not wav_is_clean(dst, args.sample_rate):
            raise ValueError(f"cleaned file is not mono 16k PCM WAV: {dst}")

        cleaned.append({"source": src, "cleaned": dst, "status": status})
        _print(f"[clean] {status}: {src.name} -> {dst.name}")

    return cleaned


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
        segment_pad_secs=args.segment_pad_secs,
        refine_boundaries=args.refine_boundaries,
        refine_energy_db_below_peak=args.refine_energy_db_below_peak,
        refine_energy_min_rms=args.refine_energy_min_rms,
        refine_search_pad_ms=args.refine_search_pad_ms,
        refine_pad_ms=args.refine_pad_ms,
        refine_min_speech_ms=args.refine_min_speech_ms,
        refine_max_gap_ms=args.refine_max_gap_ms,
    )


def cut_wav_segment(src: Path, dst: Path, start_sec: float, end_sec: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as reader:
        params = reader.getparams()
        sample_rate = reader.getframerate()
        start_frame = max(0, int(round(start_sec * sample_rate)))
        end_frame = max(start_frame, int(round(end_sec * sample_rate)))
        reader.setpos(min(start_frame, reader.getnframes()))
        frames = reader.readframes(max(0, min(end_frame, reader.getnframes()) - start_frame))

    with wave.open(str(dst), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)


def manifest_path(path: Path) -> str:
    return str(path.resolve())


def write_manifest(rows: list[dict], csv_path: Path, jsonl_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "segment_id",
        "label",
        "source_file",
        "cleaned_file",
        "segment_file",
        "start",
        "end",
        "duration",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_vad_and_label(cleaned: list[dict], args: argparse.Namespace) -> list[dict]:
    model = VADModel(
        model_path=str(args.model),
        chunk_ms=args.model_chunk_ms,
        context_ms=args.context_ms,
    )
    vad_args = make_vad_args(args)
    rows = []

    for item in cleaned:
        cleaned_path = item["cleaned"]
        source_path = item["source"]
        duration, regions = run_vad_file(model, cleaned_path, vad_args)
        speaking_regions = [region for region in regions if region["label"] == "speaking"]
        _print(
            f"[vad] {cleaned_path.name}: {len(speaking_regions)} speaking segment(s), {duration:.3f}s"
        )

        for idx, region in enumerate(speaking_regions, start=1):
            start = float(region["start"])
            end = float(region["end"])
            segment_id = f"{cleaned_path.stem}__seg{idx:04d}"
            segment_path = args.segments_dir / f"{segment_id}.wav"
            cut_wav_segment(cleaned_path, segment_path, start, end)
            rows.append(
                {
                    "segment_id": segment_id,
                    "label": "speaking",
                    "source_file": manifest_path(source_path),
                    "cleaned_file": manifest_path(cleaned_path),
                    "segment_file": manifest_path(segment_path),
                    "start": f"{start:.3f}",
                    "end": f"{end:.3f}",
                    "duration": f"{end - start:.3f}",
                }
            )

    return rows


def run_crawler(args: argparse.Namespace) -> None:
    if not args.crawler_cmd:
        return
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    _print(f"[crawl] running command in {args.crawler_cwd}: {args.crawler_cmd}")
    subprocess.run(args.crawler_cmd, cwd=args.crawler_cwd, shell=True, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run crawl -> clean -> VAD -> label pipeline.")
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "data" / "raw_audio")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_ROOT / "pipeline_runs" / "latest")
    parser.add_argument("--clean-dir", type=Path, default=None)
    parser.add_argument("--segments-dir", type=Path, default=None)
    parser.add_argument("--manifest-csv", type=Path, default=None)
    parser.add_argument("--manifest-jsonl", type=Path, default=None)
    parser.add_argument("--crawler-cmd", default="", help="Optional external crawler command.")
    parser.add_argument("--crawler-cwd", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--overwrite", action="store_true")

    parser.add_argument(
        "--demucs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Separate vocals with Demucs before clean/VAD (on by default; --no-demucs to skip).",
    )
    parser.add_argument(
        "--demucs-cmd",
        default=None,
        help="Demucs command. Default: auto-resolve .venv-demucs, else 'python -m demucs'.",
    )
    parser.add_argument("--demucs-model", default="htdemucs")
    parser.add_argument("--demucs-device", default="cpu", help="Demucs device: cpu or cuda.")
    parser.add_argument("--vocals-dir", type=Path, default=None)

    parser.add_argument("--model", type=Path, default=MODEL_DIR / "vad.onnx")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-ms", type=int, default=64)
    parser.add_argument("--model-chunk-ms", type=int, default=32)
    parser.add_argument("--context-ms", type=int, default=4)
    parser.add_argument("--reset-duration", type=float, default=5)
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--negative-threshold", type=float, default=None)
    parser.add_argument("--min-volume", type=float, default=0.6)
    parser.add_argument("--start-secs", type=float, default=0.1)
    parser.add_argument("--stop-secs", type=float, default=0.45)
    parser.add_argument("--merge-gap-secs", type=float, default=0.5)
    parser.add_argument("--min-speech-secs", type=float, default=0.08)
    parser.add_argument("--segment-pad-secs", type=float, default=0.12)
    parser.add_argument("--refine-boundaries", action="store_true")
    parser.add_argument("--refine-energy-db-below-peak", type=float, default=35.0)
    parser.add_argument("--refine-energy-min-rms", type=float, default=1e-4)
    parser.add_argument("--refine-search-pad-ms", type=float, default=700.0)
    parser.add_argument("--refine-pad-ms", type=float, default=0.0)
    parser.add_argument("--refine-min-speech-ms", type=float, default=64.0)
    parser.add_argument("--refine-max-gap-ms", type=float, default=160.0)

    args = parser.parse_args()
    args.clean_dir = args.clean_dir or args.work_dir / "clean_wav"
    args.vocals_dir = args.vocals_dir or args.work_dir / "vocals"
    args.segments_dir = args.segments_dir or args.work_dir / "segments"
    args.manifest_csv = args.manifest_csv or args.work_dir / "labels.csv"
    args.manifest_jsonl = args.manifest_jsonl or args.work_dir / "labels.jsonl"
    return args


def resolve_and_probe_demucs(args: argparse.Namespace) -> None:
    """Resolve the Demucs command and probe once. Disable on unavailable.

    Keeps the run-level "auto on, fall back to raw" decision in one place. After
    this returns, ``args.demucs_cmd`` is the resolved command and ``args.demucs``
    reflects whether separation will actually run.
    """
    if not args.demucs:
        return
    args.demucs_cmd = resolve_demucs_cmd(args.demucs_cmd, PROJECT_ROOT)
    if not demucs_available(args.demucs_cmd):
        _print(f"[demucs] unavailable ({args.demucs_cmd}); falling back to raw audio")
        args.demucs = False


def main() -> int:
    args = parse_args()
    run_crawler(args)
    resolve_and_probe_demucs(args)
    vocal_map = separate_vocals(collect_audio_files(args.raw_dir), args) if args.demucs else None
    cleaned = clean_audio_files(args, vocal_map)
    rows = run_vad_and_label(cleaned, args)
    write_manifest(rows, args.manifest_csv, args.manifest_jsonl)
    _print(f"[done] wrote {len(rows)} segment label(s)")
    _print(f"[done] csv:   {args.manifest_csv}")
    _print(f"[done] jsonl: {args.manifest_jsonl}")
    _print(f"[done] wavs:  {args.segments_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
