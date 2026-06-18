from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from app.core.config import settings
from app.modules.audio_pipeline.api.schemas import normalize_youtube_video_url
from app.modules.audio_pipeline.application.job_service import PipelineJobService
from app.utils import get_logger
from app.utils.filesystem import ensure_dir

logger = get_logger(__name__)


@dataclass(frozen=True)
class DiscoveryQuerySet:
    queries: list[str]
    query_source: str
    signals: tuple[str, ...]
    total_query_count: int
    window_start: int


class DiscoveryService:
    # Service tìm URL YouTube mới theo query tiếng Việt để tự tạo batch tiếp theo.
    _TOPIC_HEADER_VALUES = {"keyword", "keywords", "topic", "topics"}
    _BASE_VIETNAMESE_SIGNALS = (
        "viet nam",
        "việt nam",
        "tieng viet",
        "tiếng việt",
        "giong mien trung",
        "giọng miền trung",
        "giong mien tay",
        "giọng miền tây",
        "giong mien nam",
        "giọng miền nam",
        "giong hue",
        "giọng huế",
        "giong quang nam",
        "giọng quảng nam",
        "giong nghe an",
        "giọng nghệ an",
        "giong ha tinh",
        "giọng hà tĩnh",
        "noi chuyen",
        "nói chuyện",
        "tro chuyen",
        "trò chuyện",
        "phong van",
        "phỏng vấn",
        "toa dam",
        "tọa đàm",
        "radio",
        "podcast",
        "talkshow",
        "bai giang",
        "bài giảng",
        "truyen ke",
        "truyện kể",
        "sach noi",
        "sách nói",
        "review",
        "vlog",
    )

    def __init__(self, job_service: PipelineJobService) -> None:
        self.job_service = job_service

    @staticmethod
    def _unique_preserve_order(values: list[str]) -> list[str]:
        unique_values: list[str] = []
        seen_values: set[str] = set()
        for value in values:
            normalized = value.strip()
            if not normalized:
                continue
            dedupe_key = normalized.casefold()
            if dedupe_key in seen_values:
                continue
            seen_values.add(dedupe_key)
            unique_values.append(normalized)
        return unique_values

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.strip().casefold())
        return normalized

    @classmethod
    def _is_topic_header(cls, value: str) -> bool:
        return cls._normalize_text(value) in cls._TOPIC_HEADER_VALUES

    @classmethod
    def _extract_query_signals(cls, queries: list[str]) -> tuple[str, ...]:
        signal_candidates: list[str] = list(cls._BASE_VIETNAMESE_SIGNALS)
        for query in queries:
            normalized_query = cls._normalize_text(query)
            if not normalized_query:
                continue
            signal_candidates.append(normalized_query)
            signal_candidates.extend(
                token
                for token in normalized_query.split(" ")
                if len(token) >= 4 and token not in {"tiếng", "viet", "việt", "nam"}
            )

        unique_signals = cls._unique_preserve_order(signal_candidates)
        # Ưu tiên phrase dài hơn để match chắc hơn trước khi rơi về token ngắn.
        unique_signals.sort(key=lambda item: (-len(item), item))
        return tuple(unique_signals)

    @staticmethod
    def _load_cursor(path: Path) -> int:
        if not path.exists() or not path.is_file():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return 0
        raw_cursor = payload.get("cursor", 0) if isinstance(payload, dict) else 0
        return int(raw_cursor or 0)

    @staticmethod
    def _save_cursor(path: Path, cursor: int) -> None:
        ensure_dir(path.parent)
        path.write_text(json.dumps({"cursor": max(0, cursor)}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _select_query_window(self, queries: list[str]) -> tuple[list[str], int]:
        if not queries:
            return [], 0

        window_size = max(1, settings.discovery_query_window_size)
        if len(queries) <= window_size:
            return queries, 0

        cursor_path = settings.resolved_discovery_cursor_file
        start = self._load_cursor(cursor_path) % len(queries)
        selected = [queries[(start + offset) % len(queries)] for offset in range(window_size)]
        next_cursor = (start + window_size) % len(queries)
        self._save_cursor(cursor_path, next_cursor)
        logger.info(
            "discovery:query_window | total_query_count=%s | window_size=%s | start=%s | next_cursor=%s",
            len(queries),
            window_size,
            start,
            next_cursor,
        )
        return selected, start

    def _load_topic_file_queries(self) -> tuple[list[str], str | None]:
        topic_file = settings.resolved_discovery_topic_file
        if not topic_file:
            return [], None

        topic_path = topic_file if topic_file.is_absolute() else Path.cwd() / topic_file
        if not topic_path.exists() or not topic_path.is_file():
            logger.info("discovery:topic_file_skip | reason=missing | path=%s", topic_path)
            return [], str(topic_path)

        try:
            raw_lines = topic_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("discovery:topic_file_failed | path=%s | error=%s", topic_path, exc)
            return [], str(topic_path)

        queries = self._unique_preserve_order(
            [
                line
                for line in raw_lines
                if line.strip() and not self._is_topic_header(line)
            ]
        )
        logger.info("discovery:topic_file_loaded | path=%s | query_count=%s", topic_path, len(queries))
        return queries, str(topic_path)

    def get_query_set(self) -> DiscoveryQuerySet:
        file_queries, topic_path = self._load_topic_file_queries()
        if file_queries:
            all_queries = file_queries
            query_source = f"file:{topic_path}"
        else:
            all_queries = self._unique_preserve_order(settings.resolved_discovery_search_queries)
            query_source = "env"

        queries, window_start = self._select_query_window(all_queries)
        return DiscoveryQuerySet(
            queries=queries,
            query_source=query_source,
            signals=self._extract_query_signals(queries),
            total_query_count=len(all_queries),
            window_start=window_start,
        )

    def get_search_queries(self) -> tuple[list[str], str]:
        query_set = self.get_query_set()
        return query_set.queries, query_set.query_source

    @staticmethod
    def _get_ytdlp_modules():
        from yt_dlp import YoutubeDL

        return YoutubeDL

    @staticmethod
    def _score_entry_match(entry: dict[str, Any], query: str, signals: tuple[str, ...]) -> int:
        text = " ".join(
            [
                str(entry.get("title", "")),
                str(entry.get("description", "")),
                str(entry.get("channel", "")),
                str(entry.get("uploader", "")),
                query,
            ]
        )
        haystack = DiscoveryService._normalize_text(text)
        score = 0
        for signal in signals:
            if signal and signal in haystack:
                score += max(1, min(len(signal.split()), 3))
        return score

    def discover_urls(self, *, limit: int) -> list[str]:
        query_set = self.get_query_set()
        queries = query_set.queries
        query_source = query_set.query_source
        if not queries or limit <= 0:
            logger.info(
                "discovery:skip | reason=no_queries_or_limit | limit=%s | query_source=%s",
                limit,
                query_source,
            )
            return []

        YoutubeDL = self._get_ytdlp_modules()
        per_query = max(1, limit // max(1, len(queries)))
        options = {
            "quiet": False,
            "no_warnings": False,
            "extract_flat": True,
            "skip_download": True,
            "playlist_items": f"1:{max(limit, per_query)}",
        }

        discovered_urls: list[str] = []
        seen_urls: set[str] = set()
        logger.info(
            "discovery:start | query_count=%s | total_query_count=%s | window_start=%s | signal_count=%s | limit=%s | query_source=%s",
            len(queries),
            query_set.total_query_count,
            query_set.window_start,
            len(query_set.signals),
            limit,
            query_source,
        )

        with YoutubeDL(options) as ydl:
            for query in queries:
                remaining = limit - len(discovered_urls)
                if remaining <= 0:
                    break
                search_size = max(1, min(remaining, per_query))
                search_ref = f"ytsearch{search_size}:{query}"
                logger.info("discovery:query | query=%s | search_size=%s", query, search_size)
                try:
                    info = ydl.extract_info(search_ref, download=False)
                except Exception as exc:
                    logger.warning("discovery:query_failed | query=%s | error=%s", query, exc)
                    continue

                entries = [entry for entry in (info or {}).get("entries", []) if entry]
                logger.info("discovery:query_done | query=%s | result_count=%s", query, len(entries))
                for entry in entries:
                    if len(discovered_urls) >= limit:
                        break
                    match_score = self._score_entry_match(entry, query, query_set.signals)
                    if match_score <= 0:
                        continue
                    raw_url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
                    if not raw_url:
                        continue
                    if raw_url and not raw_url.startswith("http"):
                        raw_url = f"https://www.youtube.com/watch?v={raw_url}"
                    try:
                        normalized_url = normalize_youtube_video_url(raw_url)
                    except ValueError:
                        continue
                    if normalized_url in seen_urls:
                        continue
                    video_id = normalized_url.split("v=", 1)[-1]
                    if self.job_service.has_active_video_id(video_id):
                        continue
                    seen_urls.add(normalized_url)
                    discovered_urls.append(normalized_url)
                    logger.info(
                        "discovery:url_selected | query=%s | video_id=%s | match_score=%s",
                        query,
                        video_id,
                        match_score,
                    )

        logger.info(
            "discovery:done | discovered_url_count=%s | limit=%s | query_source=%s",
            len(discovered_urls),
            limit,
            query_source,
        )
        return discovered_urls
