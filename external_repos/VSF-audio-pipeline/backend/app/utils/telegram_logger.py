from __future__ import annotations

import json
import threading
from typing import Any
from urllib import error, parse, request

from app.core.config import settings
from app.utils.dev_logger import get_logger

logger = get_logger(__name__)
_telegram_send_state = threading.local()
_TELEGRAM_MAX_TEXT_LENGTH = 3800


def telegram_log_enabled() -> bool:
    return bool(
        settings.telegram_log_enabled
        and settings.telegram_bot_token.strip()
        and settings.telegram_chat_id.strip()
    )


def send_telegram_log(message: str, **context: Any) -> bool:
    """Gui mot log message len Telegram Bot API neu da cau hinh."""
    if getattr(_telegram_send_state, "active", False):
        return False
    if not telegram_log_enabled():
        logger.info("Telegram log skipped | reason=not_configured | message=%s", message)
        return False

    text = _build_message(message, context)
    payload = parse.urlencode(
        {
            "chat_id": settings.telegram_chat_id,
            "text": text,
        }
    ).encode("utf-8")
    endpoint = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    req = request.Request(endpoint, data=payload, method="POST")

    try:
        _telegram_send_state.active = True
        with request.urlopen(req, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body)
            ok = bool(data.get("ok"))
            if not ok:
                logger.warning("Telegram log failed | response=%s", response_body)
            return ok
    except error.URLError as exc:
        logger.warning("Telegram log failed | error=%s", exc)
        return False
    except Exception as exc:
        logger.warning("Telegram log unexpected failure | error=%s", exc)
        return False
    finally:
        _telegram_send_state.active = False


def _build_message(message: str, context: dict[str, Any]) -> str:
    if not context:
        return _truncate_message(message)

    context_text = "\n".join(f"- {key}: {value}" for key, value in context.items())
    return _truncate_message(f"{message}\n{context_text}")


def _truncate_message(text: str) -> str:
    if len(text) <= _TELEGRAM_MAX_TEXT_LENGTH:
        return text
    return f"{text[:_TELEGRAM_MAX_TEXT_LENGTH - 3]}..."
