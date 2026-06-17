"""
Run the cloned VSF-audio-pipeline backend as a direct file-based crawler.

This helper is meant to be executed through the cloned repo's backend env:

  uv run --project external_repos/VSF-audio-pipeline/backend python scripts/run_vsf_github_crawl.py ...

It avoids FastAPI/Postgres and calls AudioPipelineService directly:
  crawl_youtube -> normalize_audio -> segment_and_label -> build_segment_metadata

segment_and_label needs a Triton VAD server (VAD_GRPC_URL) and faster-whisper
(ASR_MODEL/ASR_DEVICE) for the ASR fallback when subtitles are missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def read_urls(urls: list[str], urls_file: Path | None) -> list[str]:
    values = [url.strip() for url in urls if url.strip()]
    if urls_file:
        values.extend(
            line.strip()
            for line in urls_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return values


def set_runtime_env(args: argparse.Namespace) -> None:
    os.environ["APP_ENV"] = "local"
    os.environ["STORAGE_ROOT"] = str(args.storage_root)
    os.environ["RAW_YOUTUBE_DIR"] = str(args.raw_dir)
    os.environ["PROCESSED_AUDIO_DIR"] = str(args.processed_audio_dir)
    os.environ["SEGMENTS_DIR"] = str(args.segments_dir)
    os.environ["METADATA_DIR"] = str(args.metadata_dir)
    os.environ["LOG_DIR"] = str(args.log_dir)
    os.environ["TELEGRAM_LOG_ENABLED"] = str(args.telegram_log_enabled).lower()

    if args.vad_grpc_url:
        os.environ["VAD_GRPC_URL"] = args.vad_grpc_url
    if args.asr_model:
        os.environ["ASR_MODEL"] = args.asr_model
    if args.asr_device:
        os.environ["ASR_DEVICE"] = args.asr_device
    if args.cookie_file:
        os.environ["YT_DLP_COOKIE_FILE"] = str(args.cookie_file)
    if args.cookie_backup_file:
        os.environ["YT_DLP_COOKIE_BACKUP_FILE"] = str(args.cookie_backup_file)
    if args.proxy_backups:
        os.environ["YT_DLP_PROXY_BACKUPS"] = args.proxy_backups
    if args.crawl_min_delay_sec is not None:
        os.environ["CRAWL_MIN_DELAY_SEC"] = str(args.crawl_min_delay_sec)
    if args.crawl_max_delay_sec is not None:
        os.environ["CRAWL_MAX_DELAY_SEC"] = str(args.crawl_max_delay_sec)
    if args.crawl_url_retry_limit is not None:
        os.environ["CRAWL_URL_RETRY_LIMIT"] = str(args.crawl_url_retry_limit)

    os.environ["DEMUCS_ENABLED"] = str(args.demucs_enabled).lower()
    if args.demucs_command:
        os.environ["DEMUCS_COMMAND"] = args.demucs_command
    if args.demucs_model:
        os.environ["DEMUCS_MODEL"] = args.demucs_model
    if args.demucs_device:
        os.environ["DEMUCS_DEVICE"] = args.demucs_device
    if args.separated_audio_dir:
        os.environ["DEMUCS_SEPARATED_DIR"] = str(args.separated_audio_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VSF GitHub crawler without the API server.")
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--urls-file", type=Path)
    parser.add_argument("--batch-name", default="batch_001")
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--processed-audio-dir", type=Path, required=True)
    parser.add_argument("--segments-dir", type=Path, required=True)
    parser.add_argument("--metadata-dir", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--cookie-backup-file", type=Path)
    parser.add_argument("--proxy-backups", default="")
    parser.add_argument("--crawl-min-delay-sec", type=float)
    parser.add_argument("--crawl-max-delay-sec", type=float)
    parser.add_argument("--crawl-url-retry-limit", type=int)
    parser.add_argument("--vad-grpc-url", default="")
    parser.add_argument("--asr-model", default="")
    parser.add_argument("--asr-device", default="")
    parser.add_argument("--telegram-log-enabled", action="store_true")
    parser.add_argument("--demucs-enabled", action="store_true")
    parser.add_argument("--demucs-command", default="")
    parser.add_argument("--demucs-model", default="")
    parser.add_argument("--demucs-device", default="")
    parser.add_argument("--separated-audio-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_dir = args.repo_dir.resolve()
    backend_dir = repo_dir / "backend"
    sys.path.insert(0, str(backend_dir))
    set_runtime_env(args)

    from app.modules.audio_pipeline.api.schemas import normalize_youtube_video_url
    from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService

    raw_urls = read_urls(args.url, args.urls_file)
    urls = []
    seen = set()
    for raw_url in raw_urls:
        normalized = normalize_youtube_video_url(raw_url)
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)

    if not urls:
        raise ValueError("No valid YouTube URLs provided.")

    for path in [
        args.storage_root,
        args.raw_dir,
        args.processed_audio_dir,
        args.segments_dir,
        args.metadata_dir,
        args.log_dir,
        args.summary_json.parent,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    service = AudioPipelineService()
    source_rows = service.crawl_youtube(urls, batch_name=args.batch_name)
    source_rows = service.separate_vocals(source_rows, batch_name=args.batch_name)
    processed_rows = service.normalize_audio(source_rows, batch_name=args.batch_name)
    segment_rows = service.segment_and_label(processed_rows, batch_name=args.batch_name)
    manifest_path = service.build_segment_metadata(segment_rows, batch_name=args.batch_name)

    summary = {
        "batch_name": args.batch_name,
        "url_count": len(urls),
        "source_count": len(source_rows),
        "processed_count": len(processed_rows),
        "segment_count": len(segment_rows),
        "processed_audio_dir": str(args.processed_audio_dir.resolve()),
        "segments_dir": str(args.segments_dir.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "processed_rows": processed_rows,
    }
    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
