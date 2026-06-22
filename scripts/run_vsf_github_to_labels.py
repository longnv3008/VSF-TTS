"""
Complete integration:

  Crawl path:    VSF-audio-pipeline GitHub repo crawl -> normalize
                 -> segment_and_label (Triton VAD gRPC + ASR fallback)
                 -> build_segment_metadata (labeled speech segment manifest)

  --skip-crawl:  local offline VAD segmentation on already-produced audio
                 (end_to_end_pipeline.py, no Triton/ASR; labels only, no text)

The crawl path produces the manifest via the repo's in-repo segment pipeline,
so it needs a Triton VAD server (--vad-grpc-url) and faster-whisper
(--asr-model/--asr-device). VAD/segment tuning for the crawl path comes from the
repo .env; the --threshold/--min-volume/... knobs below apply to --skip-crawl.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demucs_env import demucs_available, resolve_demucs_cmd  # noqa: E402

DEFAULT_REPO_DIR = PROJECT_ROOT / "VSF-audio-pipeline"


def run_command(cmd: list[str], cwd: Path | None = None) -> None:
    print("[run] " + " ".join(str(item) for item in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def add_repeated_args(cmd: list[str], flag: str, values: list[str]) -> None:
    for value in values:
        cmd.extend([flag, value])


def run_github_pipeline(args: argparse.Namespace, processed_audio_dir: Path) -> None:
    helper = PROJECT_ROOT / "scripts" / "run_vsf_github_crawl.py"
    repo_dir = args.repo_dir.resolve()
    runtime_root = args.github_runtime_dir.resolve()
    cmd = [
        args.uv_bin,
        "run",
        "--project",
        str(repo_dir / "backend"),
        "python",
        str(helper),
        "--repo-dir",
        str(repo_dir),
        "--batch-name",
        args.batch_name,
        "--storage-root",
        str(runtime_root),
        "--raw-dir",
        str(args.github_raw_dir),
        "--processed-audio-dir",
        str(processed_audio_dir),
        "--segments-dir",
        str(args.github_segments_dir),
        "--metadata-dir",
        str(args.github_metadata_dir),
        "--log-dir",
        str(args.github_log_dir),
        "--summary-json",
        str(args.github_summary_json),
    ]
    if args.vad_grpc_url:
        cmd.extend(["--vad-grpc-url", args.vad_grpc_url])
    if args.asr_model:
        cmd.extend(["--asr-model", args.asr_model])
    if args.asr_device:
        cmd.extend(["--asr-device", args.asr_device])
    add_repeated_args(cmd, "--url", args.url)
    if args.urls_file:
        cmd.extend(["--urls-file", str(args.urls_file)])
    if args.cookie_file:
        cmd.extend(["--cookie-file", str(args.cookie_file)])
    if args.cookie_backup_file:
        cmd.extend(["--cookie-backup-file", str(args.cookie_backup_file)])
    if args.proxy_backups:
        cmd.extend(["--proxy-backups", args.proxy_backups])
    if args.crawl_min_delay_sec is not None:
        cmd.extend(["--crawl-min-delay-sec", str(args.crawl_min_delay_sec)])
    if args.crawl_max_delay_sec is not None:
        cmd.extend(["--crawl-max-delay-sec", str(args.crawl_max_delay_sec)])
    if args.crawl_url_retry_limit is not None:
        cmd.extend(["--crawl-url-retry-limit", str(args.crawl_url_retry_limit)])
    if args.telegram_log_enabled:
        cmd.append("--telegram-log-enabled")
    if args.demucs:
        cmd.append("--demucs-enabled")
        cmd.extend(["--demucs-command", args.demucs_cmd])
        cmd.extend(["--demucs-model", args.demucs_model])
        cmd.extend(["--demucs-device", args.demucs_device])
        cmd.extend(["--separated-audio-dir", str(args.github_separated_audio_dir)])

    run_command(cmd, cwd=repo_dir)


def run_local_vad(args: argparse.Namespace, processed_audio_dir: Path) -> None:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "end_to_end_pipeline.py"),
        "--raw-dir",
        str(processed_audio_dir),
        "--work-dir",
        str(args.vad_work_dir),
        "--threshold",
        str(args.threshold),
        "--min-volume",
        str(args.min_volume),
        "--start-secs",
        str(args.start_secs),
        "--stop-secs",
        str(args.stop_secs),
        "--merge-gap-secs",
        str(args.merge_gap_secs),
        "--min-speech-secs",
        str(args.min_speech_secs),
        "--segment-pad-secs",
        str(args.segment_pad_secs),
    ]
    if args.refine_boundaries:
        cmd.append("--refine-boundaries")
    if args.overwrite:
        cmd.append("--overwrite")
    if args.demucs:
        cmd.append("--demucs")
        cmd.extend(["--demucs-cmd", args.demucs_cmd])
        cmd.extend(["--demucs-model", args.demucs_model])
        cmd.extend(["--demucs-device", args.demucs_device])
    else:
        cmd.append("--no-demucs")
    run_command(cmd, cwd=PROJECT_ROOT)


def resolve_and_probe_demucs(args: argparse.Namespace) -> None:
    """Resolve the Demucs command and probe once; disable on unavailable.

    The wrapper is the single decision authority: the child end_to_end_pipeline.py
    now defaults Demucs ON, so the wrapper must forward an explicit on/off so the
    child never re-decides.
    """
    if not args.demucs:
        return
    args.demucs_cmd = resolve_demucs_cmd(args.demucs_cmd, PROJECT_ROOT)
    if not demucs_available(args.demucs_cmd):
        print(f"[demucs] unavailable ({args.demucs_cmd}); falling back to raw audio", flush=True)
        args.demucs = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GitHub VSF crawler and local VAD label pipeline.")
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--url", action="append", default=[], help="YouTube URL. Can be repeated.")
    parser.add_argument("--urls-file", type=Path, help="Text file with one YouTube URL per line.")
    parser.add_argument("--batch-name", default="batch_001")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_ROOT / "pipeline_runs" / "vsf_github_latest")
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--processed-audio-dir", type=Path)
    parser.add_argument("--uv-bin", default="uv")
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--cookie-backup-file", type=Path)
    parser.add_argument("--proxy-backups", default="")
    parser.add_argument("--crawl-min-delay-sec", type=float, default=2.0)
    parser.add_argument("--crawl-max-delay-sec", type=float, default=8.0)
    parser.add_argument("--crawl-url-retry-limit", type=int, default=4)
    parser.add_argument("--vad-grpc-url", default="", help="Triton VAD gRPC url for the crawl path.")
    parser.add_argument("--asr-model", default="", help="faster-whisper model for the crawl path ASR fallback.")
    parser.add_argument("--asr-device", default="", help="ASR device (cuda/cpu) for the crawl path.")
    parser.add_argument("--telegram-log-enabled", action="store_true")
    parser.add_argument("--overwrite", action="store_true")

    parser.add_argument(
        "--demucs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Separate vocals with Demucs before VAD (on by default; --no-demucs to skip).",
    )
    parser.add_argument("--demucs-cmd", default=None)
    parser.add_argument("--demucs-model", default="htdemucs")
    parser.add_argument("--demucs-device", default="cpu")

    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--min-volume", type=float, default=0.6)
    parser.add_argument("--start-secs", type=float, default=0.1)
    parser.add_argument("--stop-secs", type=float, default=0.45)
    parser.add_argument("--merge-gap-secs", type=float, default=0.5)
    parser.add_argument("--min-speech-secs", type=float, default=0.08)
    parser.add_argument("--segment-pad-secs", type=float, default=0.12)
    parser.add_argument("--refine-boundaries", action="store_true")

    args = parser.parse_args()
    args.work_dir = args.work_dir.resolve()
    args.github_runtime_dir = args.work_dir / "github_runtime"
    args.github_raw_dir = args.github_runtime_dir / "raw" / "youtube"
    args.github_processed_audio_dir = args.github_runtime_dir / "processed" / "audio"
    args.github_separated_audio_dir = args.github_runtime_dir / "processed" / "separated"
    args.github_segments_dir = args.github_runtime_dir / "processed" / "segments"
    args.github_metadata_dir = args.github_runtime_dir / "metadata"
    args.github_log_dir = args.work_dir / "github_logs"
    args.github_summary_json = args.work_dir / "github_summary.json"
    args.vad_work_dir = args.work_dir / "vad_labels"

    if args.skip_crawl and not args.processed_audio_dir:
        parser.error("--skip-crawl requires --processed-audio-dir")
    if not args.skip_crawl and not args.url and not args.urls_file:
        parser.error("Provide --url/--urls-file, or use --skip-crawl --processed-audio-dir")

    return args


def main() -> int:
    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    resolve_and_probe_demucs(args)

    if args.skip_crawl:
        # Offline path: local ONNX VAD on already-produced audio (no Triton/ASR).
        processed_audio_dir = args.processed_audio_dir.resolve()
        run_local_vad(args, processed_audio_dir)
        print(f"[done] labels: {args.vad_work_dir / 'labels.csv'}")
        print(f"[done] jsonl:  {args.vad_work_dir / 'labels.jsonl'}")
        print(f"[done] wavs:   {args.vad_work_dir / 'segments'}")
        return 0

    # Crawl path: the repo's in-repo segment pipeline produces the manifest.
    processed_audio_dir = args.github_processed_audio_dir.resolve()
    run_github_pipeline(args, processed_audio_dir)
    manifest_csv = args.github_metadata_dir / f"{args.batch_name}_segments.csv"
    manifest_jsonl = manifest_csv.with_suffix(".jsonl")
    print(f"[done] labels: {manifest_csv}")
    print(f"[done] jsonl:  {manifest_jsonl}")
    print(f"[done] wavs:   {args.github_segments_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
