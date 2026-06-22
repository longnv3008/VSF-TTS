"""Pure error-message classifiers for the YouTube crawl pipeline.

Extracted from ``pipeline_service.py``: stateless predicates that inspect
yt-dlp / network exception messages, plus the retry-delay helper. Keeping
them here lets the crawl orchestration code stay focused on control flow.
"""

from __future__ import annotations

import re

from app.core.config import settings

_RATE_LIMIT_SIGNALS = (
    "too many requests",
    "http error 429",
    "status code: 429",
    "sign in to confirm you're not a bot",
    "log in to confirm you're not a bot",
    "confirm you're not a bot",
    "this request has been blocked",
    "temporarily unavailable",
    "rate limit",
)
_SKIPPABLE_DOWNLOAD_ERROR_SIGNALS = (
    "http error 403",
    "forbidden",
    "unable to download video data",
)
_COOKIE_ERROR_PATTERNS = (
    r"\byoutube account cookies? (?:are|is) no longer valid\b",
    r"\bprovided youtube account cookies? (?:are|is) no longer valid\b",
    r"\bcookies? (?:are|is) no longer valid\b",
    r"\bcookies? expired\b",
    r"\bfailed to (?:load|decrypt) cookies?\b",
    r"\bcould not read cookies? file\b",
    r"\bno such file or directory.*cookies?\b",
    r"\bcookies? (?:from browser|database) could not be loaded\b",
)
_AUTH_HARD_FAIL_PATTERNS = (
    r"\buse --cookies-from-browser or --cookies for the authentication\b",
    r"\bthis video is private\b",
    r"\bprivate video\b",
    r"\bmembers-only\b",
    r"\bjoin this channel to get access\b",
    r"\bconfirm your age\b",
    r"\bage-restricted\b",
)
_COOKIE_ERROR_REGEXES = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _COOKIE_ERROR_PATTERNS)
_AUTH_HARD_FAIL_REGEXES = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _AUTH_HARD_FAIL_PATTERNS)
_NETWORK_ERROR_SIGNALS = (
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporary failure in name resolution",
    "name or service not known",
    "tls",
    "ssl",
    "proxy error",
    "proxyconnect",
    "incomplete read",
    "network is unreachable",
    "remote end closed connection",
)


def is_rate_limited_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(signal in message for signal in _RATE_LIMIT_SIGNALS)


def compute_retry_delay(attempt: int, blocked: bool) -> float:
    if blocked:
        base_delay = max(60.0, settings.crawl_block_cooldown_sec / 4)
        return min(settings.crawl_block_cooldown_sec, base_delay * attempt)
    return min(30.0, 5.0 * attempt)


def is_skippable_download_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(signal in message for signal in _SKIPPABLE_DOWNLOAD_ERROR_SIGNALS)


def is_cookie_related_message(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(message)).strip()
    return any(pattern.search(normalized) for pattern in _COOKIE_ERROR_REGEXES)


# Historically pipeline_service had two identically-implemented predicates
# (_is_cookie_related_message / _is_cookie_invalid_message). Keep both names.
is_cookie_invalid_message = is_cookie_related_message


def is_auth_hard_fail_message(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(message)).strip()
    return any(pattern.search(normalized) for pattern in _AUTH_HARD_FAIL_REGEXES)


def is_transient_network_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(signal in message for signal in _NETWORK_ERROR_SIGNALS)
