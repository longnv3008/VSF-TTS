from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, perf_counter, sleep
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings
from app.modules.audio_pipeline.application import crawl_errors
from app.modules.audio_pipeline.application.exceptions import BatchAbortError, SkipUrlError, format_function_error
from app.modules.audio_pipeline.application.segmentation.asr_adapter import FasterWhisperAdapter
from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
    REVIEW_FIELDS,
    SEGMENT_METADATA_FIELDS,
)
from app.modules.audio_pipeline.application.segmentation.segment_service import segment_video
from app.modules.audio_pipeline.application.separation.demucs_separator import (
    separate_vocals as demucs_separate_vocals,
)
from app.modules.audio_pipeline.application.separation.noise_probe import measure_noise_floor_db
from app.modules.audio_pipeline.application.segmentation.llm_judge import (
    LlmJudgeAdapter,
    NullJudgeAdapter,
    OllamaJudgeAdapter,
)
from app.modules.audio_pipeline.application.segmentation.music_detect import DEFAULT_MUSIC_KEYWORDS
from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vad_local_client import OnnxVadClient
from app.modules.audio_pipeline.application.stage_timing import (
    SegmentTimingSink,
    close_timing,
    open_timing,
)
from app.utils import get_logger, send_telegram_log
from app.utils.filesystem import ensure_dir, read_csv, write_csv

logger = get_logger(__name__)


def _music_keywords(extra_csv: str) -> tuple[str, ...]:
    """Default keywords + keyword bổ sung (CSV env), casefold + bỏ rỗng."""
    extras = tuple(k.strip() for k in extra_csv.split(",") if k.strip())
    return DEFAULT_MUSIC_KEYWORDS + extras


def build_normalize_cmd(
    raw_file: Path,
    output_file: Path,
    *,
    sample_rate: int,
    mono: bool,
    loudnorm: bool = False,
    loudnorm_i: float = -16.0,
    loudnorm_tp: float = -1.5,
    loudnorm_lra: float = 11.0,
) -> list[str]:
    """Dựng argv ffmpeg để normalize audio về format thống nhất.

    ``loudnorm`` bật -> thêm filter EBU R128 (chuẩn hóa âm lượng), không chỉ đổi format.
    Tách riêng để test được command mà không chạy ffmpeg.
    """
    cmd = ["ffmpeg", "-y", "-i", str(raw_file)]
    if loudnorm:
        cmd += ["-af", f"loudnorm=I={loudnorm_i}:TP={loudnorm_tp}:LRA={loudnorm_lra}"]
    cmd += [
        "-ac",
        "1" if mono else "2",
        "-ar",
        str(sample_rate),
        "-sample_fmt",
        "s16",
        str(output_file),
    ]
    return cmd


_CRAWL_LOCK = threading.Lock()
_CRAWL_STATE_LOCK = threading.Lock()
_PROXY_STATE_LOCK = threading.Lock()
_TELEGRAM_DEDUP_LOCK = threading.Lock()
_LAST_CRAWL_FINISHED_AT = 0.0
_PROXY_RUNTIME_STATE: dict[str, dict[str, float | int]] = {}
_TELEGRAM_SENT_KEYS: set[tuple[str, str, str, str]] = set()


@dataclass(frozen=True)
class _ProxyConfig:
    name: str
    url: str | None
    priority: int


@dataclass(frozen=True)
class _CookieConfig:
    name: str
    path: Path


class _YtdlpLogger:
    # Nhận warning/error trực tiếp từ yt-dlp để gắn thêm URL vào log của app.
    def __init__(self, job_id: int | None, batch_name: str | None, url: str) -> None:
        self.job_id = job_id
        self.batch_name = batch_name
        self.url = url
        self.last_error_message: str | None = None

    def debug(self, message: str) -> None:
        # yt-dlp đẩy cả progress qua debug; bỏ qua để terminal không bị spam.
        if message.startswith("[debug]") or message.startswith("[download]"):
            return
        logger.info("step=crawl_audio | url=%s", self.url)

    def warning(self, message: str) -> None:
        logger.warning("step=crawl_audio | url=%s | error=%s", self.url, message)
        if crawl_errors.is_cookie_related_message(message):
            AudioPipelineService._notify_telegram_once(
                dedup_key=("cookie_warning", str(self.job_id or ""), self.url, str(message).strip()),
                message="YouTube cookie warning",
                job_id=self.job_id,
                batch_name=self.batch_name,
                url=self.url,
                step="crawl_audio",
                status="warning",
                error=message,
            )

    def error(self, message: str) -> None:
        self.last_error_message = str(message).strip() or None
        logger.error("step=crawl_audio | url=%s | error=%s", self.url, message)
        if crawl_errors.is_cookie_related_message(message):
            AudioPipelineService._notify_telegram_once(
                dedup_key=("cookie_error", str(self.job_id or ""), self.url, str(message).strip()),
                message="YouTube cookie error",
                job_id=self.job_id,
                batch_name=self.batch_name,
                url=self.url,
                step="crawl_audio",
                status="failed",
                error=message,
            )


def _build_progress_hook(job_id: int | None, batch_name: str | None, url: str):
    # yt-dlp gọi hook này liên tục khi tải file; mình chỉ log ở các mốc 10%.
    last_progress = {"value": -1}

    def hook(data: dict[str, Any]) -> None:
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = int((downloaded / total) * 100) if total else -1
            if percent >= 0 and percent // 10 != last_progress["value"] // 10:
                last_progress["value"] = percent
                logger.info("step=crawl_audio | url=%s", url)
        elif status == "finished":
            logger.info("step=crawl_audio | url=%s", url)

    return hook


class AudioPipelineService:
    # Service này xử lý toàn bộ pipeline file-based: crawl, normalize, cắt câu + label segment, metadata.
    def __init__(self) -> None:
        self.raw_dir = ensure_dir(settings.raw_youtube_dir)
        self.processed_dir = ensure_dir(settings.processed_audio_dir)
        self.metadata_dir = ensure_dir(settings.metadata_dir)
        self.segments_dir = ensure_dir(settings.segments_dir)
        self.separated_dir = ensure_dir(settings.separated_audio_dir)

    @staticmethod
    def _notify_telegram(
        message: str,
        *,
        job_id: int | None = None,
        batch_name: str | None = None,
        url: str | None = None,
        video_id: str | None = None,
        step: str | None = None,
        status: str | None = None,
        **context: Any,
    ) -> None:
        # Gom format Telegram vào một chỗ để mọi step gửi cùng cấu trúc.
        send_telegram_log(
            message,
            job_id=job_id or "",
            batch_name=batch_name or "",
            url=url or "",
            video_id=video_id or "",
            step=step or "",
            status=status or "",
            **context,
        )

    @staticmethod
    def _notify_telegram_once(
        *,
        dedup_key: tuple[str, str, str, str],
        message: str,
        job_id: int | None = None,
        batch_name: str | None = None,
        url: str | None = None,
        video_id: str | None = None,
        step: str | None = None,
        status: str | None = None,
        **context: Any,
    ) -> None:
        with _TELEGRAM_DEDUP_LOCK:
            if dedup_key in _TELEGRAM_SENT_KEYS:
                return
            _TELEGRAM_SENT_KEYS.add(dedup_key)

        AudioPipelineService._notify_telegram(
            message,
            job_id=job_id,
            batch_name=batch_name,
            url=url,
            video_id=video_id,
            step=step,
            status=status,
            **context,
        )

    def _notify_url_stage(
        self,
        *,
        message: str,
        job_id: int | None,
        batch_name: str | None,
        url: str,
        video_id: str | None = None,
        step: str,
        status: str,
        **context: Any,
    ) -> None:
        stage_labels = {
            "demucs": "Demucs",
            "vad": "VAD",
            "asr": "ASR",
            "segment_output": "Output",
            "segment_and_label": "Segment",
        }
        status_labels = {
            "started": "bắt đầu",
            "completed": "xong",
            "failed": "lỗi",
        }
        stage_text = stage_labels.get(step, step.upper())
        status_text = status_labels.get(status, status)
        lines = [f"{stage_text} {status_text}", f"URL: {url}"]
        if video_id:
            lines.append(f"Video ID: {video_id}")
        if step == "vad" and status == "completed":
            if "region_count" in context:
                lines.append(f"Speech regions: {context['region_count']}")
        if step == "asr" and status == "completed":
            if "segment_count" in context and "ready_count" in context:
                lines.append(
                    f"ASR ready: {context['ready_count']}/{context['segment_count']}"
                )
        if step == "segment_output" and status == "completed":
            if "segment_count" in context and "ready_count" in context:
                lines.append(
                    f"Segments: {context['ready_count']}/{context['segment_count']} ready"
                )
            if "missing_count" in context:
                lines.append(f"Missing: {context['missing_count']}")
        if status == "failed" and "error" in context:
            lines.append(f"Lỗi: {context['error']}")
        if step == "demucs" and status == "completed":
            if context.get("backend") == "demucs":
                lines.append("Bộ lọc nhạc: demucs")
            elif context.get("backend") == "ffmpeg":
                lines.append("Bộ lọc nhạc: ffmpeg")
            if "reason" in context:
                lines.append(f"Lý do: {context['reason']}")

        send_telegram_log("\n".join(lines))

    @staticmethod
    def _should_use_demucs_for_row(row: dict[str, str]) -> tuple[bool, str]:
        mode = settings.resolved_demucs_mode
        if mode == "off":
            return False, "demucs_mode=off"
        if mode == "on":
            return True, "demucs_mode=on"
        # auto: đo noise floor của raw -> nhiễu cao thì Demucs, sạch thì chỉ ffmpeg.
        raw_path = (row.get("raw_file_path") or "").strip()
        try:
            floor_db = measure_noise_floor_db(Path(raw_path))
        except Exception as exc:
            logger.warning("step=noise_probe | path=%s | error=%s", raw_path, exc)
            return False, "auto_noise_unknown"
        if floor_db >= settings.demucs_noise_floor_db:
            return True, f"auto_noise_high({floor_db:.1f}dB)"
        return False, f"auto_noise_low({floor_db:.1f}dB)"

    @staticmethod
    def _log_crawl(event: str, **context: Any) -> None:
        parts = [f"crawl:{event}"]
        for key, value in context.items():
            if value is None or value == "":
                continue
            parts.append(f"{key}={value}")
        logger.info(" | ".join(parts))

    @staticmethod
    def _log_crawl_warning(event: str, **context: Any) -> None:
        parts = [f"crawl:{event}"]
        for key, value in context.items():
            if value is None or value == "":
                continue
            parts.append(f"{key}={value}")
        logger.warning(" | ".join(parts))

    @staticmethod
    def _format_proxy_label(proxy_url: str) -> str:
        parsed = urlsplit(proxy_url)
        if not parsed.scheme or not parsed.hostname:
            return "invalid-proxy"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"

    @staticmethod
    def _get_configured_proxies() -> list[_ProxyConfig]:
        proxies: list[_ProxyConfig] = [_ProxyConfig(name="direct", url=None, priority=0)]
        for index, proxy_url in enumerate(settings.resolved_yt_dlp_proxy_backups, start=1):
            proxies.append(_ProxyConfig(name=f"backup_{index}", url=proxy_url, priority=index))
        return proxies

    @staticmethod
    def _sync_proxy_runtime_state(proxies: list[_ProxyConfig]) -> None:
        with _PROXY_STATE_LOCK:
            active_names = {proxy.name for proxy in proxies}
            for proxy in proxies:
                _PROXY_RUNTIME_STATE.setdefault(
                    proxy.name,
                    {
                        "cooldown_until": 0.0,
                        "consecutive_failures": 0,
                    },
                )
            stale_names = [name for name in _PROXY_RUNTIME_STATE if name not in active_names]
            for name in stale_names:
                _PROXY_RUNTIME_STATE.pop(name, None)

    @staticmethod
    def _pick_proxy(
        proxies: list[_ProxyConfig],
        *,
        preferred_name: str | None = None,
        exclude_names: set[str] | None = None,
    ) -> _ProxyConfig | None:
        if not proxies:
            return None

        exclude_names = exclude_names or set()
        now = monotonic()
        available: list[_ProxyConfig] = []
        with _PROXY_STATE_LOCK:
            for proxy in proxies:
                state = _PROXY_RUNTIME_STATE.get(proxy.name, {})
                if proxy.name in exclude_names:
                    continue
                if float(state.get("cooldown_until", 0.0)) <= now:
                    available.append(proxy)

        if not available:
            return None

        if preferred_name:
            for proxy in available:
                if proxy.name == preferred_name:
                    return proxy
        return available[0]

    def _wait_for_proxy_availability(self, proxies: list[_ProxyConfig], *, job_id: int | None, batch_name: str | None) -> None:
        if not proxies:
            return

        while True:
            proxy = self._pick_proxy(proxies)
            if proxy is not None:
                return

            with _PROXY_STATE_LOCK:
                cooldown_targets = [
                    float(_PROXY_RUNTIME_STATE.get(proxy_item.name, {}).get("cooldown_until", 0.0))
                    for proxy_item in proxies
                ]
            next_ready_at = min(cooldown_targets) if cooldown_targets else monotonic()
            wait_sec = max(0.0, next_ready_at - monotonic())
            if wait_sec <= 0:
                return

            self._log_crawl("wait_proxy", batch=batch_name, job_id=job_id, sleep_sec=f"{wait_sec:.2f}")
            if wait_sec >= 30:
                self._notify_telegram(
                    "YouTube proxy cooldown",
                    job_id=job_id,
                    batch_name=batch_name,
                    step="crawl_audio",
                    status="waiting",
                    sleep_sec=round(wait_sec, 2),
                )
            sleep(wait_sec)

    @staticmethod
    def _mark_proxy_success(proxy_name: str) -> None:
        with _PROXY_STATE_LOCK:
            state = _PROXY_RUNTIME_STATE.setdefault(proxy_name, {"cooldown_until": 0.0, "consecutive_failures": 0})
            state["consecutive_failures"] = 0

    def _mark_proxy_rate_limited(
        self,
        proxy: _ProxyConfig,
        *,
        job_id: int | None,
        batch_name: str | None,
        url: str,
        attempt: int,
        error: str,
    ) -> None:
        cooldown_until = monotonic() + max(60.0, settings.crawl_block_cooldown_sec)
        with _PROXY_STATE_LOCK:
            state = _PROXY_RUNTIME_STATE.setdefault(proxy.name, {"cooldown_until": 0.0, "consecutive_failures": 0})
            state["cooldown_until"] = cooldown_until
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1

        self._log_crawl_warning(
            "proxy_cooldown",
            batch=batch_name,
            job_id=job_id,
            url=url,
            attempt=attempt,
            proxy=proxy.name,
            sleep_sec=f"{max(0.0, cooldown_until - monotonic()):.2f}",
            error=error,
        )
        self._notify_telegram(
            "YouTube proxy rate limited",
            job_id=job_id,
            batch_name=batch_name,
            url=url,
            step="crawl_audio",
            status="cooldown",
            attempt=attempt,
            proxy=proxy.name,
            cooldown_sec=round(max(0.0, cooldown_until - monotonic()), 2),
            error=error,
        )

    def _notify_proxy_switch(
        self,
        *,
        from_proxy: _ProxyConfig,
        to_proxy: _ProxyConfig | None,
        job_id: int | None,
        batch_name: str | None,
        url: str,
        attempt: int,
        reason: str,
    ) -> None:
        next_route = to_proxy.name if to_proxy else "none"
        next_addr = self._format_proxy_label(to_proxy.url) if to_proxy and to_proxy.url else ("direct" if to_proxy else "none")
        self._log_crawl_warning(
            "proxy_switch",
            batch=batch_name,
            job_id=job_id,
            url=url,
            attempt=attempt,
            from_proxy=from_proxy.name,
            to_proxy=next_route,
            reason=reason,
        )
        self._notify_telegram(
            "YouTube proxy switched",
            job_id=job_id,
            batch_name=batch_name,
            url=url,
            step="crawl_audio",
            status="failover",
            attempt=attempt,
            from_proxy=from_proxy.name,
            from_proxy_addr=self._format_proxy_label(from_proxy.url) if from_proxy.url else "direct",
            to_proxy=next_route,
            to_proxy_addr=next_addr,
            reason=reason,
        )

    def _notify_proxy_runtime(
        self,
        *,
        job_id: int | None,
        batch_name: str | None,
        configured_cookies: list[_CookieConfig],
        active_cookie: _CookieConfig | None,
        proxies: list[_ProxyConfig],
    ) -> None:
        proxy_backup_count = max(0, len(proxies) - 1)
        cookie_status = "guest"
        cookie_path = ""
        active_cookie_name = "guest"
        if active_cookie is not None:
            cookie_status = "loaded"
            cookie_path = str(active_cookie.path)
            active_cookie_name = active_cookie.name
        elif configured_cookies:
            cookie_status = "missing"
            cookie_path = ",".join(str(cookie.path) for cookie in configured_cookies)

        self._notify_telegram(
            "YouTube crawl runtime config",
            job_id=job_id,
            batch_name=batch_name,
            step="crawl_audio",
            status="started",
            cookie_status=cookie_status,
            active_cookie=active_cookie_name,
            cookie_file=cookie_path,
            proxy_backup_count=proxy_backup_count,
        )

    @staticmethod
    def _get_configured_cookies() -> list[_CookieConfig]:
        cookies: list[_CookieConfig] = []
        primary = settings.resolved_yt_dlp_cookie_file
        backup = settings.resolved_yt_dlp_cookie_backup_file
        if primary is not None:
            cookies.append(_CookieConfig(name="primary", path=primary))
        if backup is not None:
            cookies.append(_CookieConfig(name="backup", path=backup))
        return cookies

    def _notify_cookie_switch(
        self,
        *,
        from_cookie: _CookieConfig,
        to_cookie: _CookieConfig | None,
        job_id: int | None,
        batch_name: str | None,
        url: str,
        attempt: int,
        reason: str,
    ) -> None:
        next_cookie = to_cookie.name if to_cookie else "none"
        self._log_crawl_warning(
            "cookie_switch",
            batch=batch_name,
            job_id=job_id,
            url=url,
            attempt=attempt,
            from_cookie=from_cookie.name,
            to_cookie=next_cookie,
            reason=reason,
        )
        self._notify_telegram(
            "YouTube cookie switched",
            job_id=job_id,
            batch_name=batch_name,
            url=url,
            step="crawl_audio",
            status="retrying",
            attempt=attempt,
            from_cookie=from_cookie.name,
            from_cookie_file=str(from_cookie.path),
            to_cookie=next_cookie,
            to_cookie_file=str(to_cookie.path) if to_cookie else "",
            reason=reason,
        )

    def _notify_proxy_error(
        self,
        *,
        proxy: _ProxyConfig,
        job_id: int | None,
        batch_name: str | None,
        url: str,
        attempt: int,
        error: str,
    ) -> None:
        self._notify_telegram(
            "YouTube proxy error",
            job_id=job_id,
            batch_name=batch_name,
            url=url,
            step="crawl_audio",
            status="warning",
            attempt=attempt,
            proxy=proxy.name,
            proxy_addr=self._format_proxy_label(proxy.url) if proxy.url else "direct",
            error=error,
        )

    @staticmethod
    def _get_first_available_cookie(configured_cookies: list[_CookieConfig]) -> _CookieConfig | None:
        return next((cookie for cookie in configured_cookies if cookie.path.exists() and cookie.path.is_file()), None)

    @staticmethod
    def _get_soundfile_module():
        # Import lười để API vẫn boot được ngay cả khi worker deps chưa có trong env hiện tại.
        import soundfile as sf

        return sf

    @staticmethod
    def _get_ytdlp_modules():
        # Import lười để chỉ lúc crawl mới cần yt-dlp thực sự có mặt.
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        return YoutubeDL, DownloadError

    @staticmethod
    def _resolve_subtitle_file(raw_file: Path) -> Path | None:
        # Tìm file subtitle mà yt-dlp có thể đã tải kèm với audio gốc.
        subtitle_suffixes = (".vtt", ".srt", ".json3")
        candidates = sorted(raw_file.parent.glob(f"{raw_file.stem}*"))
        for candidate in candidates:
            if candidate == raw_file or candidate.suffix.lower() not in subtitle_suffixes:
                continue
            return candidate
        return None

    def _sleep_between_urls(self, index: int, total: int, *, job_id: int | None, batch_name: str | None) -> None:
        min_delay = max(0.0, settings.crawl_min_delay_sec)
        max_delay = max(min_delay, settings.crawl_max_delay_sec)
        if max_delay <= 0:
            return
        delay = random.uniform(min_delay, max_delay)
        self._log_crawl("wait_url", batch=batch_name, job_id=job_id, item=f"{index}/{total}", sleep_sec=f"{delay:.2f}")
        sleep(delay)

    def _sleep_before_next_job(self, *, job_id: int | None, batch_name: str | None) -> None:
        global _LAST_CRAWL_FINISHED_AT

        cooldown = max(0.0, settings.crawl_job_cooldown_sec)
        if cooldown <= 0:
            return

        with _CRAWL_STATE_LOCK:
            elapsed = monotonic() - _LAST_CRAWL_FINISHED_AT if _LAST_CRAWL_FINISHED_AT else cooldown
            wait_sec = max(0.0, cooldown - elapsed)

        if wait_sec <= 0:
            return

        self._log_crawl("wait_job", batch=batch_name, job_id=job_id, sleep_sec=f"{wait_sec:.2f}")
        if wait_sec >= 30:
            self._notify_telegram(
                "YouTube crawl cooldown",
                job_id=job_id,
                batch_name=batch_name,
                step="crawl_audio",
                status="waiting",
                sleep_sec=round(wait_sec, 2),
            )
        sleep(wait_sec)

    def _note_crawl_finished(self) -> None:
        global _LAST_CRAWL_FINISHED_AT
        with _CRAWL_STATE_LOCK:
            _LAST_CRAWL_FINISHED_AT = monotonic()

    @staticmethod
    def _resolve_audio_file(prepared_path: Path) -> Path | None:
        # yt-dlp có thể đổi phần mở rộng sau download, nên cần dò file audio thật sự trên disk.
        audio_suffixes = {".m4a", ".wav", ".opus", ".ogg", ".webm", ".mp4", ".aac", ".flac", ".mp3"}
        candidates = sorted(prepared_path.parent.glob(f"{prepared_path.stem}*"))
        for candidate in candidates:
            if candidate.suffix.lower() not in audio_suffixes:
                continue
            if candidate.is_file():
                return candidate.resolve()
        return prepared_path.resolve() if prepared_path.exists() and prepared_path.is_file() else None

    def crawl_youtube(self, urls: list[str], job_id: int | None = None, batch_name: str | None = None) -> list[dict[str, str]]:
        try:
            rows: list[dict[str, str]] = []
            cookie_file = settings.resolved_yt_dlp_cookie_file
            configured_cookies = self._get_configured_cookies()
            initial_cookie = self._get_first_available_cookie(configured_cookies)
            # self._notify_telegram(
            #     "YouTube crawl batch started",
            #     job_id=job_id,
            #     batch_name=batch_name,
            #     step="crawl_audio",
            #     status="started",
            #     url_count=len(urls),
            # )
            self._log_crawl("batch_start", batch=batch_name, job_id=job_id, url_count=len(urls))

            options = {
                "format": "bestaudio/best",
                "ignoreerrors": True,
                "noplaylist": True,
                "outtmpl": str(self.raw_dir / "%(id)s__%(title).120B.%(ext)s"),
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["vi"],
                "subtitlesformat": "vtt/json3/best",
                "restrictfilenames": True,
                "windowsfilenames": True,
                "quiet": False,
                "no_warnings": False,
                "noprogress": True,
                "retries": 3,
                "fragment_retries": 3,
                "extractor_retries": 3,
                "socket_timeout": 20,
            }
            if cookie_file:
                if cookie_file.exists() and cookie_file.is_file():
                    self._log_crawl("cookies_ok", batch=batch_name, job_id=job_id, cookie_file=str(cookie_file))
                elif initial_cookie is None:
                    self._log_crawl_warning(
                        "cookies_missing",
                        batch=batch_name,
                        job_id=job_id,
                        cookie_file=str(cookie_file),
                    )
                    self._notify_telegram(
                        "yt-dlp cookies missing",
                        job_id=job_id,
                        batch_name=batch_name,
                        step="crawl_audio",
                        status="warning",
                        cookie_file=str(cookie_file),
                    )

            proxies = self._get_configured_proxies()
            self._sync_proxy_runtime_state(proxies)
            if proxies:
                self._log_crawl("proxy_failover_on", batch=batch_name, job_id=job_id, proxy_count=len(proxies))
            self._notify_proxy_runtime(
                job_id=job_id,
                batch_name=batch_name,
                configured_cookies=configured_cookies,
                active_cookie=initial_cookie,
                proxies=proxies,
            )

            YoutubeDL, DownloadError = self._get_ytdlp_modules()
            with _CRAWL_LOCK:
                self._log_crawl("lock_ok", batch=batch_name, job_id=job_id)
                self._sleep_before_next_job(job_id=job_id, batch_name=batch_name)
                active_proxy = self._pick_proxy(proxies, preferred_name="direct") if proxies else None
                if proxies and active_proxy is None:
                    self._wait_for_proxy_availability(proxies, job_id=job_id, batch_name=batch_name)
                    active_proxy = self._pick_proxy(proxies, preferred_name="direct")
                for index, url in enumerate(urls, start=1):
                    # Mỗi URL được crawl độc lập; lỗi một URL sẽ abort cả batch hiện tại.
                    if index > 1:
                        self._sleep_between_urls(index, len(urls), job_id=job_id, batch_name=batch_name)

                    self._log_crawl("url_start", batch=batch_name, job_id=job_id, item=f"{index}/{len(urls)}", url=url)
                    self._notify_telegram(
                        "YouTube URL crawl started",
                        job_id=job_id,
                        batch_name=batch_name,
                        url=url,
                        step="crawl_audio",
                        status="started",
                        url_index=f"{index}/{len(urls)}",
                    )

                    last_error: Exception | None = None
                    info: dict[str, Any] | None = None
                    ydl_filename_resolver = None
                    attempt = 0
                    active_cookie = self._get_first_available_cookie(configured_cookies)
                    tried_cookie_names: set[str] = set()
                    guest_cookie_tried = False
                    route_failovers = 0
                    route_failover_budget = max(1, settings.crawl_url_retry_limit, len(proxies))
                    route_network_retries: dict[str, int] = {}
                    blocked_routes_for_url: set[str] = set()
                    while True:
                        attempt += 1
                        url_options = dict(options)
                        ydl_logger = _YtdlpLogger(job_id, batch_name, url)
                        url_options["logger"] = ydl_logger
                        url_options["progress_hooks"] = [_build_progress_hook(job_id, batch_name, url)]
                        if active_cookie is not None:
                            url_options["cookiefile"] = str(active_cookie.path)
                        else:
                            url_options.pop("cookiefile", None)
                        if proxies and active_proxy is None:
                            self._wait_for_proxy_availability(proxies, job_id=job_id, batch_name=batch_name)
                            active_proxy = self._pick_proxy(proxies, preferred_name="direct")
                        if active_proxy and active_proxy.url:
                            url_options["proxy"] = active_proxy.url
                            self._log_crawl(
                                "proxy_pick",
                                batch=batch_name,
                                job_id=job_id,
                                item=f"{index}/{len(urls)}",
                                attempt=attempt,
                                proxy=active_proxy.name,
                                proxy_addr=self._format_proxy_label(active_proxy.url),
                            )
                        elif active_proxy:
                            self._log_crawl(
                                "proxy_pick",
                                batch=batch_name,
                                job_id=job_id,
                                item=f"{index}/{len(urls)}",
                                attempt=attempt,
                                proxy=active_proxy.name,
                                proxy_addr="direct",
                            )
                        url_started_at = perf_counter()

                        try:
                            with YoutubeDL(url_options) as ydl:
                                ydl_filename_resolver = ydl
                                info = ydl.extract_info(url, download=True)
                            entries = [info] if info and "entries" not in info else [entry for entry in (info or {}).get("entries", []) if entry]
                            self._log_crawl(
                                "url_done",
                                batch=batch_name,
                                job_id=job_id,
                                item=f"{index}/{len(urls)}",
                                url=url,
                                entry_count=len(entries),
                                sec=f"{perf_counter() - url_started_at:.2f}",
                            )
                            self._notify_telegram(
                                "YouTube URL crawl completed",
                                job_id=job_id,
                                batch_name=batch_name,
                                url=url,
                                step="crawl_audio",
                                status="completed",
                                entry_count=len(entries),
                                duration_sec=round(perf_counter() - url_started_at, 2),
                                    url_index=f"{index}/{len(urls)}",
                                )
                            if active_proxy:
                                self._mark_proxy_success(active_proxy.name)
                            break
                        except DownloadError as exc:
                            last_error = exc
                            blocked = crawl_errors.is_rate_limited_error(exc)
                            route_name = active_proxy.name if active_proxy else "direct"
                            self._log_crawl_warning(
                                "retry",
                                url=url,
                                attempt=attempt,
                                blocked=blocked,
                                error=str(exc),
                            )
                            if crawl_errors.is_cookie_related_message(str(exc)):
                                self._notify_telegram_once(
                                    dedup_key=(
                                        "cookie_warning",
                                        str(job_id or ""),
                                        url,
                                        str(exc).strip(),
                                    ),
                                    message="YouTube cookie warning",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    step="crawl_audio",
                                    status="warning",
                                    attempt=attempt,
                                    error=str(exc),
                                )
                            if crawl_errors.is_cookie_invalid_message(str(exc)) and active_cookie is not None:
                                tried_cookie_names.add(active_cookie.name)
                                next_cookie = next(
                                    (
                                        cookie
                                        for cookie in configured_cookies
                                        if cookie.name not in tried_cookie_names and cookie.path.exists() and cookie.path.is_file()
                                    ),
                                    None,
                                )
                                if next_cookie is not None:
                                    previous_cookie = active_cookie
                                    active_cookie = next_cookie
                                    self._notify_cookie_switch(
                                        from_cookie=previous_cookie,
                                        to_cookie=active_cookie,
                                        job_id=job_id,
                                        batch_name=batch_name,
                                        url=url,
                                        attempt=attempt,
                                        reason=str(exc),
                                    )
                                    delay = min(5.0, crawl_errors.compute_retry_delay(attempt, False))
                                    self._log_crawl_warning(
                                        "retry_wait",
                                        url=url,
                                        attempt=attempt,
                                        mode="cookie_failover",
                                        route=route_name,
                                        sleep_sec=f"{delay:.2f}",
                                    )
                                    sleep(delay)
                                    continue
                                if not guest_cookie_tried:
                                    previous_cookie = active_cookie
                                    active_cookie = None
                                    guest_cookie_tried = True
                                    self._notify_cookie_switch(
                                        from_cookie=previous_cookie,
                                        to_cookie=None,
                                        job_id=job_id,
                                        batch_name=batch_name,
                                        url=url,
                                        attempt=attempt,
                                        reason=f"{exc} | fallback=guest",
                                    )
                                    delay = min(5.0, crawl_errors.compute_retry_delay(attempt, False))
                                    self._log_crawl_warning(
                                        "retry_wait",
                                        url=url,
                                        attempt=attempt,
                                        mode="cookie_guest_fallback",
                                        route=route_name,
                                        sleep_sec=f"{delay:.2f}",
                                    )
                                    sleep(delay)
                                    continue
                                raise SkipUrlError(step="crawl_audio", failed_url=url, cause=exc) from exc
                            if crawl_errors.is_skippable_download_error(exc):
                                raise SkipUrlError(step="crawl_audio", failed_url=url, cause=exc) from exc
                            if crawl_errors.is_auth_hard_fail_message(str(exc)):
                                raise SkipUrlError(step="crawl_audio", failed_url=url, cause=exc) from exc
                            if blocked and active_proxy:
                                failed_proxy = active_proxy
                                blocked_routes_for_url.add(failed_proxy.name)
                                self._mark_proxy_rate_limited(
                                    failed_proxy,
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    attempt=attempt,
                                    error=str(exc),
                                )
                                next_proxy = self._pick_proxy(
                                    proxies,
                                    preferred_name="direct",
                                    exclude_names=blocked_routes_for_url,
                                )
                                if next_proxy is None:
                                    if len(blocked_routes_for_url) >= len(proxies):
                                        raise BatchAbortError(
                                            step="crawl_audio",
                                            failed_url=url,
                                            remaining_urls=urls[index:],
                                            cause=exc,
                                        ) from exc
                                    self._wait_for_proxy_availability(proxies, job_id=job_id, batch_name=batch_name)
                                    next_proxy = self._pick_proxy(
                                        proxies,
                                        preferred_name="direct",
                                        exclude_names=blocked_routes_for_url,
                                    )
                                active_proxy = next_proxy
                                self._notify_proxy_switch(
                                    from_proxy=failed_proxy,
                                    to_proxy=active_proxy,
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    attempt=attempt,
                                    reason=str(exc),
                                )
                                route_failovers += 1
                                if route_failovers >= route_failover_budget and active_proxy is None:
                                    raise BatchAbortError(
                                        step="crawl_audio",
                                        failed_url=url,
                                        remaining_urls=urls[index:],
                                        cause=exc,
                                    ) from exc
                            elif crawl_errors.is_transient_network_error(exc):
                                network_retries = route_network_retries.get(route_name, 0)
                                if active_proxy and active_proxy.name != "direct":
                                    self._notify_proxy_error(
                                        proxy=active_proxy,
                                        job_id=job_id,
                                        batch_name=batch_name,
                                        url=url,
                                        attempt=attempt,
                                        error=str(exc),
                                    )
                                if network_retries >= 1:
                                    raise BatchAbortError(
                                        step="crawl_audio",
                                        failed_url=url,
                                        remaining_urls=urls[index:],
                                        cause=exc,
                                    ) from exc
                                route_network_retries[route_name] = network_retries + 1
                            else:
                                raise BatchAbortError(
                                    step="crawl_audio",
                                    failed_url=url,
                                    remaining_urls=urls[index:],
                                    cause=exc,
                                ) from exc

                            delay = crawl_errors.compute_retry_delay(attempt, blocked)
                            retry_mode = "failover" if blocked else "same_route"
                            self._log_crawl_warning(
                                "retry_wait",
                                url=url,
                                attempt=attempt,
                                mode=retry_mode,
                                route=route_name,
                                sleep_sec=f"{delay:.2f}",
                            )
                            if blocked:
                                self._notify_telegram(
                                    "YouTube crawl rate limited",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    step="crawl_audio",
                                    status="retrying",
                                    attempt=attempt,
                                    sleep_sec=round(delay, 2),
                                    error=str(exc),
                                )
                            else:
                                self._notify_telegram(
                                    "YouTube crawl network retry",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    step="crawl_audio",
                                    status="retrying",
                                    attempt=attempt,
                                    route=route_name,
                                    sleep_sec=round(delay, 2),
                                    error=str(exc),
                                )
                            sleep(delay)
                        except Exception as exc:
                            last_error = exc
                            blocked = crawl_errors.is_rate_limited_error(exc)
                            route_name = active_proxy.name if active_proxy else "direct"
                            logger.exception(
                                "crawl:error | url=%s | attempt=%s | blocked=%s | error=%s",
                                url,
                                attempt,
                                blocked,
                                format_function_error("crawl_youtube", exc),
                            )
                            if crawl_errors.is_cookie_related_message(str(exc)):
                                self._notify_telegram_once(
                                    dedup_key=(
                                        "cookie_error",
                                        str(job_id or ""),
                                        url,
                                        format_function_error("crawl_youtube", exc),
                                    ),
                                    message="YouTube cookie error",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    step="crawl_audio",
                                    status="failed",
                                    attempt=attempt,
                                    error=format_function_error("crawl_youtube", exc),
                                )
                            if crawl_errors.is_cookie_invalid_message(str(exc)) and active_cookie is not None:
                                tried_cookie_names.add(active_cookie.name)
                                next_cookie = next(
                                    (
                                        cookie
                                        for cookie in configured_cookies
                                        if cookie.name not in tried_cookie_names and cookie.path.exists() and cookie.path.is_file()
                                    ),
                                    None,
                                )
                                if next_cookie is not None:
                                    previous_cookie = active_cookie
                                    active_cookie = next_cookie
                                    self._notify_cookie_switch(
                                        from_cookie=previous_cookie,
                                        to_cookie=active_cookie,
                                        job_id=job_id,
                                        batch_name=batch_name,
                                        url=url,
                                        attempt=attempt,
                                        reason=format_function_error("crawl_youtube", exc),
                                    )
                                    delay = min(5.0, crawl_errors.compute_retry_delay(attempt, False))
                                    self._log_crawl_warning(
                                        "retry_wait",
                                        url=url,
                                        attempt=attempt,
                                        mode="cookie_failover",
                                        route=route_name,
                                        sleep_sec=f"{delay:.2f}",
                                    )
                                    sleep(delay)
                                    continue
                                if not guest_cookie_tried:
                                    previous_cookie = active_cookie
                                    active_cookie = None
                                    guest_cookie_tried = True
                                    self._notify_cookie_switch(
                                        from_cookie=previous_cookie,
                                        to_cookie=None,
                                        job_id=job_id,
                                        batch_name=batch_name,
                                        url=url,
                                        attempt=attempt,
                                        reason=f"{format_function_error('crawl_youtube', exc)} | fallback=guest",
                                    )
                                    delay = min(5.0, crawl_errors.compute_retry_delay(attempt, False))
                                    self._log_crawl_warning(
                                        "retry_wait",
                                        url=url,
                                        attempt=attempt,
                                        mode="cookie_guest_fallback",
                                        route=route_name,
                                        sleep_sec=f"{delay:.2f}",
                                    )
                                    sleep(delay)
                                    continue
                                raise SkipUrlError(step="crawl_audio", failed_url=url, cause=exc) from exc
                            if crawl_errors.is_skippable_download_error(exc):
                                raise SkipUrlError(step="crawl_audio", failed_url=url, cause=exc) from exc
                            if crawl_errors.is_auth_hard_fail_message(str(exc)):
                                raise SkipUrlError(step="crawl_audio", failed_url=url, cause=exc) from exc
                            if blocked and active_proxy:
                                failed_proxy = active_proxy
                                blocked_routes_for_url.add(failed_proxy.name)
                                self._mark_proxy_rate_limited(
                                    failed_proxy,
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    attempt=attempt,
                                    error=format_function_error("crawl_youtube", exc),
                                )
                                next_proxy = self._pick_proxy(
                                    proxies,
                                    preferred_name="direct",
                                    exclude_names=blocked_routes_for_url,
                                )
                                if next_proxy is None:
                                    if len(blocked_routes_for_url) >= len(proxies):
                                        raise BatchAbortError(
                                            step="crawl_audio",
                                            failed_url=url,
                                            remaining_urls=urls[index:],
                                            cause=exc,
                                        ) from exc
                                    self._wait_for_proxy_availability(proxies, job_id=job_id, batch_name=batch_name)
                                    next_proxy = self._pick_proxy(
                                        proxies,
                                        preferred_name="direct",
                                        exclude_names=blocked_routes_for_url,
                                    )
                                active_proxy = next_proxy
                                self._notify_proxy_switch(
                                    from_proxy=failed_proxy,
                                    to_proxy=active_proxy,
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    attempt=attempt,
                                    reason=format_function_error("crawl_youtube", exc),
                                )
                                route_failovers += 1
                                if route_failovers >= route_failover_budget and active_proxy is None:
                                    raise BatchAbortError(
                                        step="crawl_audio",
                                        failed_url=url,
                                        remaining_urls=urls[index:],
                                        cause=exc,
                                    ) from exc
                            elif crawl_errors.is_transient_network_error(exc):
                                network_retries = route_network_retries.get(route_name, 0)
                                if active_proxy and active_proxy.name != "direct":
                                    self._notify_proxy_error(
                                        proxy=active_proxy,
                                        job_id=job_id,
                                        batch_name=batch_name,
                                        url=url,
                                        attempt=attempt,
                                        error=format_function_error("crawl_youtube", exc),
                                    )
                                if network_retries >= 1:
                                    raise BatchAbortError(
                                        step="crawl_audio",
                                        failed_url=url,
                                        remaining_urls=urls[index:],
                                        cause=exc,
                                    ) from exc
                                route_network_retries[route_name] = network_retries + 1
                            else:
                                raise BatchAbortError(
                                    step="crawl_audio",
                                    failed_url=url,
                                    remaining_urls=urls[index:],
                                    cause=exc,
                                ) from exc

                            delay = crawl_errors.compute_retry_delay(attempt, blocked)
                            retry_mode = "failover" if blocked else "same_route"
                            self._log_crawl_warning(
                                "retry_wait",
                                url=url,
                                attempt=attempt,
                                mode=retry_mode,
                                route=route_name,
                                sleep_sec=f"{delay:.2f}",
                            )
                            if blocked:
                                self._notify_telegram(
                                    "YouTube crawl blocked",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    step="crawl_audio",
                                    status="retrying",
                                    attempt=attempt,
                                    sleep_sec=round(delay, 2),
                                    error=format_function_error("crawl_youtube", exc),
                                )
                            else:
                                self._notify_telegram(
                                    "YouTube crawl network retry",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    step="crawl_audio",
                                    status="retrying",
                                    attempt=attempt,
                                    route=route_name,
                                    sleep_sec=round(delay, 2),
                                    error=format_function_error("crawl_youtube", exc),
                                )
                            sleep(delay)

                    if info is None or ydl_filename_resolver is None:
                        if last_error is None:
                            fallback_message = (
                                ydl_logger.last_error_message
                                if "ydl_logger" in locals()
                                else None
                            ) or "yt-dlp returned no result"
                            last_error = RuntimeError(fallback_message)
                        raise BatchAbortError(
                            step="crawl_audio",
                            failed_url=url,
                            remaining_urls=urls[index:],
                            cause=last_error,
                        )

                    entries = [info] if info and "entries" not in info else [entry for entry in (info or {}).get("entries", []) if entry]
                    for entry in entries:
                        try:
                            # Chuẩn hóa kết quả yt-dlp thành row nội bộ cho các step sau dùng.
                            requested_downloads = entry.get("requested_downloads") or []
                            filepath = entry.get("filepath")
                            if not filepath and requested_downloads:
                                filepath = requested_downloads[0].get("filepath")
                            if not filepath:
                                filepath = ydl_filename_resolver.prepare_filename(entry)
                            raw_file = self._resolve_audio_file(Path(filepath))
                            if raw_file is None:
                                self._log_crawl_warning("file_missing", url=url, video_id=entry.get("id", ""))
                                raise SkipUrlError(
                                    step="crawl_audio",
                                    failed_url=url,
                                    cause=FileNotFoundError(f"Downloaded audio missing after postprocess: {filepath}"),
                                )
                            subtitle_file = self._resolve_subtitle_file(raw_file)
                            if subtitle_file is None or subtitle_file.suffix.lower() != ".vtt":
                                video_id = str(entry.get("id", "")).strip()
                                self._log_crawl_warning("subtitle_missing", url=url, video_id=video_id)
                                self._notify_telegram(
                                    "YouTube subtitle missing",
                                    job_id=job_id,
                                    batch_name=batch_name,
                                    url=url,
                                    video_id=video_id,
                                    step="crawl_audio",
                                    status="skipped",
                                    reason="missing_vtt",
                                )
                                raise SkipUrlError(
                                    step="crawl_audio",
                                    failed_url=url,
                                    cause=FileNotFoundError(
                                        f"No .vtt subtitle downloaded for video_id={video_id or 'unknown'}",
                                    ),
                                )

                            row = {
                                "video_id": str(entry.get("id", "")).strip(),
                                "title": str(entry.get("title", "")).strip(),
                                "source_url": str(entry.get("webpage_url") or url).strip(),
                                "duration_sec": str(entry.get("duration") or "").strip(),
                                "raw_file_path": str(raw_file),
                                "subtitle_file_path": str(subtitle_file) if subtitle_file else "",
                            }
                            self._log_crawl("saved", url=url, video_id=row["video_id"])
                            rows.append(row)
                        except BatchAbortError:
                            raise
                        except SkipUrlError:
                            raise
                        except Exception as exc:
                            logger.exception("step=crawl_audio | url=%s | error=%s", url, format_function_error("crawl_youtube", exc))
                            raise BatchAbortError(
                                step="crawl_audio",
                                failed_url=url,
                                remaining_urls=urls[index:],
                                cause=exc,
                            ) from exc
                self._note_crawl_finished()

            logger.info("step=crawl_audio")
            return rows
        except BatchAbortError:
            self._note_crawl_finished()
            raise
        except SkipUrlError:
            self._note_crawl_finished()
            raise
        except Exception as exc:
            self._note_crawl_finished()
            logger.exception("step=crawl_audio | error=%s", format_function_error("crawl_youtube", exc))
            self._notify_telegram(
                "YouTube crawl batch failed",
                job_id=job_id,
                batch_name=batch_name,
                step="crawl_audio",
                status="failed",
                error=format_function_error("crawl_youtube", exc),
            )
            raise

    def separate_vocals(
        self,
        source_rows: list[dict[str, str]],
        job_id: int | None = None,
        batch_id: int | None = None,
        batch_name: str | None = None,
    ) -> list[dict[str, str]]:
        # Tách vocal bằng Demucs trên raw trước normalize. Tắt -> trả nguyên rows.
        if settings.resolved_demucs_mode == "off":
            return source_rows

        outputs: list[dict[str, str]] = []
        for row in source_rows:
            current_url = row.get("source_url", "")
            video_id = row.get("video_id", "")
            raw_path = row.get("raw_file_path", "")
            raw_file = Path(raw_path)
            use_demucs, reason = self._should_use_demucs_for_row(row)
            if not raw_file.exists() or not raw_file.is_file():
                logger.warning("step=vocal_separation | missing raw | url=%s", current_url)
                outputs.append(row)
                continue
            if not use_demucs:
                new_row = dict(row)
                new_row["audio_filter_backend"] = "ffmpeg"
                new_row["audio_filter_reason"] = reason
                outputs.append(new_row)
                self._notify_url_stage(
                    message="Audio filter selected",
                    job_id=job_id,
                    batch_name=batch_name,
                    url=current_url,
                    video_id=video_id,
                    step="demucs",
                    status="completed",
                    backend="ffmpeg",
                    reason=reason,
                )
                logger.info(
                    "step=vocal_separation | url=%s | skipped demucs | backend=ffmpeg | reason=%s",
                    current_url,
                    reason,
                )
                continue
            # Demucs là sub-stage nặng nhất -> đo riêng (live running -> completed/failed).
            handle = open_timing(
                job_id, batch_id, "vocal_separation",
                sub_stage="demucs", video_id=video_id, url=current_url,
            )
            self._notify_url_stage(
                message="URL stage started",
                job_id=job_id,
                batch_name=batch_name,
                url=current_url,
                video_id=video_id,
                step="demucs",
                status="started",
                reason=reason,
            )
            try:
                vocal = demucs_separate_vocals(
                    raw_file,
                    self.separated_dir,
                    command=settings.demucs_command,
                    model=settings.demucs_model,
                    device=settings.demucs_device,
                )
            except Exception as exc:
                # Per-file fallback: keep raw so normalize/segment still run; never abort batch.
                close_timing(handle, status="failed")
                self._notify_url_stage(
                    message="URL stage failed",
                    job_id=job_id,
                    batch_name=batch_name,
                    url=current_url,
                    video_id=video_id,
                    step="demucs",
                    status="failed",
                    error=format_function_error("separate_vocals", exc),
                )
                logger.warning(
                    "step=vocal_separation | url=%s | demucs failed, using raw | error=%s",
                    current_url,
                    format_function_error("separate_vocals", exc),
                )
                outputs.append(row)
                continue
            close_timing(handle, status="completed")
            self._notify_url_stage(
                message="URL stage completed",
                job_id=job_id,
                batch_name=batch_name,
                url=current_url,
                video_id=video_id,
                step="demucs",
                status="completed",
                output_file=str(vocal),
                backend="demucs",
                reason=reason,
            )

            # Trỏ raw_file_path sang vocal stem để normalize_audio hạ 16k vocal.
            # Xóa raw gốc cho tiết kiệm disk (Demucs đã dùng xong).
            raw_file.unlink(missing_ok=True)
            new_row = dict(row)
            new_row["original_raw_file_path"] = raw_path
            new_row["raw_file_path"] = str(vocal)
            new_row["audio_filter_backend"] = "demucs"
            new_row["audio_filter_reason"] = reason
            outputs.append(new_row)
            logger.info("step=vocal_separation | url=%s | vocal=%s", current_url, vocal)
        return outputs

    def normalize_audio(
        self,
        source_rows: list[dict[str, str]],
        sample_rate: int = 16000,
        mono: bool = True,
        job_id: int | None = None,
        batch_name: str | None = None,
    ) -> list[dict[str, str]]:
        # Pipeline hiện phụ thuộc ffmpeg để convert audio về format thống nhất.
        if not shutil.which("ffmpeg"):
            raise RuntimeError("normalize_audio: ffmpeg is not installed or unavailable in PATH")

        sf = self._get_soundfile_module()
        outputs: list[dict[str, str]] = []
        try:
            for index, row in enumerate(source_rows):
                try:
                    # Nếu một file raw không convert được thì dừng batch để giữ thứ tự xử lý.
                    current_url = row.get("source_url", "")
                    remaining_urls = [item.get("source_url", "").strip() for item in source_rows[index + 1 :] if item.get("source_url", "").strip()]
                    raw_path = row.get("raw_file_path", "")
                    raw_file = Path(raw_path)
                    if not raw_file.exists() or not raw_file.is_file():
                        logger.warning("step=normalize_audio | url=%s", row.get("source_url", ""))
                        raise BatchAbortError(
                            step="normalize_audio",
                            failed_url=current_url,
                            remaining_urls=remaining_urls,
                            cause=FileNotFoundError(f"Raw audio file missing: {raw_file}"),
                        )
                    video_id = row.get("video_id", "").strip() or raw_file.stem.split("__", 1)[0]
                    output_file = self.processed_dir / f"yt_{video_id}.wav"
                    logger.info("step=normalize_audio | url=%s", row.get("source_url", ""))
                    command = build_normalize_cmd(
                        raw_file,
                        output_file,
                        sample_rate=sample_rate,
                        mono=mono,
                        loudnorm=settings.loudnorm_enabled,
                        loudnorm_i=settings.loudnorm_i,
                        loudnorm_tp=settings.loudnorm_tp,
                        loudnorm_lra=settings.loudnorm_lra,
                    )
                    result = subprocess.run(command, capture_output=True, text=True, check=False)
                    if result.returncode != 0:
                        logger.warning("step=normalize_audio | url=%s | error=%s", row.get("source_url", ""), result.stderr.strip())
                        raise BatchAbortError(
                            step="normalize_audio",
                            failed_url=current_url,
                            remaining_urls=remaining_urls,
                            cause=RuntimeError(result.stderr.strip() or f"ffmpeg return code {result.returncode}"),
                        )

                    # Kiểm tra file output có audio hợp lệ trước khi đưa sang bước tiếp theo.
                    info = sf.info(str(output_file))
                    if info.frames <= 0:
                        output_file.unlink(missing_ok=True)
                        logger.warning("step=normalize_audio | url=%s", row.get("source_url", ""))
                        raise BatchAbortError(
                            step="normalize_audio",
                            failed_url=current_url,
                            remaining_urls=remaining_urls,
                            cause=ValueError(f"Normalize audio produced empty file: {output_file}"),
                        )
                    raw_file.unlink(missing_ok=True)
                    # Convert xong thì xóa raw để tiết kiệm disk, chỉ giữ wav chuẩn hóa.
                    outputs.append(
                        {
                            "audio_id": output_file.stem,
                            "video_id": row.get("video_id", video_id),
                            "title": row.get("title", ""),
                            "source_url": row.get("source_url", ""),
                            "audio_file_path": str(output_file),
                            "subtitle_file_path": row.get("subtitle_file_path", ""),
                            "duration_sec": str(round(info.frames / info.samplerate, 3) if info.samplerate else 0),
                            "sample_rate": str(info.samplerate),
                            "channels": str(info.channels),
                            "format": "wav",
                        }
                    )
                    logger.info("step=normalize_audio | url=%s | video_id=%s", row.get("source_url", ""), video_id)
                except BatchAbortError:
                    raise
                except Exception as exc:
                    logger.exception(
                        "step=normalize_audio | url=%s | error=%s",
                        row.get("source_url", ""),
                        format_function_error("normalize_audio", exc),
                    )
                    raise BatchAbortError(
                        step="normalize_audio",
                        failed_url=row.get("source_url", ""),
                        remaining_urls=[item.get("source_url", "").strip() for item in source_rows[index + 1 :] if item.get("source_url", "").strip()],
                        cause=exc,
                    ) from exc
        except BatchAbortError:
            raise
        except Exception as exc:
            logger.exception("step=normalize_audio | error=%s", format_function_error("normalize_audio", exc))
            self._notify_telegram(
                "Normalize batch failed",
                job_id=job_id,
                batch_name=batch_name,
                step="normalize_audio",
                status="failed",
                error=format_function_error("normalize_audio", exc),
            )
            raise
        return outputs

    def _build_segmentation_config(self) -> SegmentationConfig:
        return SegmentationConfig(
            chunk_ms=settings.vad_chunk_ms,
            threshold=settings.vad_threshold,
            min_volume=settings.vad_min_volume,
            start_secs=settings.vad_start_secs,
            stop_secs=settings.vad_stop_secs,
            sentence_max_sec=settings.sentence_max_sec,
            sentence_min_sec=settings.sentence_min_sec,
            phrase_gap_sec=settings.phrase_gap_sec,
            use_vtt_transcript=settings.use_vtt_transcript,
            pad_sec=settings.segment_pad_sec,
            min_segment_sec=settings.segment_min_sec,
            boundary_slack_sec=settings.segment_boundary_slack_sec,
            merge_gap_sec=settings.segment_merge_gap_sec,
            vtt_overlap_sec=settings.vtt_overlap_sec,
            segmentation_word_split=settings.segmentation_word_split,
            quality_gate_enabled=settings.quality_gate_enabled,
            quality_gate_min_rms=settings.quality_gate_min_rms,
            quality_gate_min_peak=settings.quality_gate_min_peak,
            quality_gate_min_active_ratio=settings.quality_gate_min_active_ratio,
            quality_gate_chunk_ms=settings.quality_gate_chunk_ms,
            quality_gate_min_tokens_per_sec=settings.quality_gate_min_tokens_per_sec,
            quality_gate_max_tokens_per_sec=settings.quality_gate_max_tokens_per_sec,
            quality_gate_long_segment_sec=settings.quality_gate_long_segment_sec,
            quality_gate_min_tokens_for_long_segment=settings.quality_gate_min_tokens_for_long_segment,
            wer_gate_enabled=settings.wer_gate_enabled,
            wer_gate_max=settings.wer_gate_max,
            wer_gate_skip_music=settings.wer_gate_skip_music,
            wer_gate_music_keywords=_music_keywords(settings.wer_gate_music_keywords),
        )

    def _build_segment_dependencies(self):
        # Tách riêng để test có thể inject fake VAD/ASR.
        config = self._build_segmentation_config()
        vad_client = OnnxVadClient(model_path=settings.vad_model_path, config=config)
        asr_adapter = FasterWhisperAdapter(
            model_name=settings.asr_model,
            device=settings.asr_device,
            beam_size=settings.asr_beam_size,
            no_speech_threshold=settings.asr_no_speech_threshold,
            logprob_min=settings.asr_logprob_min,
            vad_filter=settings.asr_vad_filter,
        )
        if settings.wer_gate_llm_judge_enabled:
            judge_adapter: LlmJudgeAdapter = OllamaJudgeAdapter(
                url=settings.wer_gate_llm_judge_url,
                model=settings.wer_gate_llm_judge_model,
                timeout=settings.wer_gate_llm_judge_timeout,
            )
        else:
            judge_adapter = NullJudgeAdapter()
        return vad_client, asr_adapter, judge_adapter

    def segment_and_label(
        self,
        processed_rows: list[dict[str, str]],
        job_id: int | None = None,
        batch_id: int | None = None,
        batch_name: str | None = None,
    ) -> list[dict]:
        config = self._build_segmentation_config()
        vad_client, asr_adapter, judge_adapter = self._build_segment_dependencies()
        batch = batch_name or "batch_001"
        all_rows: list[dict] = []
        for index, row in enumerate(processed_rows):
            current_url = row.get("source_url", "")
            video_id = row.get("video_id", "")
            remaining_urls = [
                item.get("source_url", "").strip()
                for item in processed_rows[index + 1:]
                if item.get("source_url", "").strip()
            ]
            # Sink ghi sub-stage vad/cut/asr cho video này (None job_id -> no-op an toàn).
            timing_sink = SegmentTimingSink(
                job_id=job_id,
                batch_id=batch_id,
                video_id=row.get("video_id", ""),
                url=current_url,
            )
            try:
                logger.info("step=segment_and_label | url=%s", current_url)
                def _stage_notifier(*, stage: str, status: str, **context: Any) -> None:
                    self._notify_url_stage(
                        message="URL stage updated",
                        job_id=job_id,
                        batch_name=batch_name,
                        url=current_url,
                        video_id=video_id,
                        step=stage,
                        status=status,
                        **context,
                    )

                rows = segment_video(
                    row,
                    vad_client=vad_client,
                    asr_adapter=asr_adapter,
                    judge_adapter=judge_adapter,
                    config=config,
                    segments_root=self.segments_dir,
                    batch_name=batch,
                    timing_sink=timing_sink,
                    stage_notifier=_stage_notifier,
                )
                if not rows:
                    logger.warning("step=segment_and_label | url=%s | no_segments", current_url)
                else:
                    ready_count = sum(1 for item in rows if item.get("transcript_status") == "ready")
                    missing_count = len(rows) - ready_count
                    self._notify_url_stage(
                        message="URL output ready",
                        job_id=job_id,
                        batch_name=batch_name,
                        url=current_url,
                        video_id=video_id,
                        step="segment_output",
                        status="completed",
                        segment_count=len(rows),
                        ready_count=ready_count,
                        missing_count=missing_count,
                    )
                all_rows.extend(rows)
            except Exception as exc:
                self._notify_url_stage(
                    message="URL stage failed",
                    job_id=job_id,
                    batch_name=batch_name,
                    url=current_url,
                    video_id=video_id,
                    step="segment_and_label",
                    status="failed",
                    error=format_function_error("segment_and_label", exc),
                )
                logger.exception(
                    "step=segment_and_label | url=%s | error=%s",
                    current_url,
                    format_function_error("segment_and_label", exc),
                )
                raise BatchAbortError(
                    step="segment_and_label",
                    failed_url=current_url,
                    remaining_urls=remaining_urls,
                    cause=exc,
                ) from exc
        logger.info("step=segment_and_label")
        return all_rows

    def build_segment_metadata(
        self,
        segment_rows: list[dict],
        job_id: int | None = None,
        batch_name: str | None = None,
    ) -> Path:
        batch = batch_name or "batch_001"
        csv_path = self.metadata_dir / f"{batch}_segments.csv"

        existing = read_csv(csv_path)
        merged: dict[str, dict] = {
            row.get("segment_id", f"row_{i}"): row for i, row in enumerate(existing)
        }
        for row in segment_rows:
            segment_id = row["segment_id"]
            prev = merged.get(segment_id, {})
            new_row = {key: row.get(key, "") for key in SEGMENT_METADATA_FIELDS}
            # Giữ lại dữ liệu review người dùng đã điền khi pipeline chạy lại.
            for review_field in REVIEW_FIELDS:
                if prev.get(review_field):
                    new_row[review_field] = prev[review_field]
            if not new_row["review_status"] and new_row["quality_label"] == "needs_review":
                new_row["review_status"] = "pending"
            merged[segment_id] = new_row

        write_csv(csv_path, SEGMENT_METADATA_FIELDS, merged.values())

        jsonl_path = csv_path.with_suffix(".jsonl")
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in merged.values():
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        logger.info("step=build_segment_metadata")
        return csv_path
