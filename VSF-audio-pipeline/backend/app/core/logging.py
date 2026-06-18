from __future__ import annotations

import asyncio
import logging
import sys
import threading
from pathlib import Path

from app.core.config import settings
from app.utils.telegram_logger import send_telegram_log, telegram_log_enabled


class TelegramErrorHandler(logging.Handler):
    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self._local = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("app.utils.telegram_logger"):
            return
        if not telegram_log_enabled():
            return
        if getattr(self._local, "active", False):
            return

        try:
            self._local.active = True
            message = self.format(record)
            send_telegram_log(
                "Backend error detected",
                logger_name=record.name,
                level=record.levelname,
                function=record.funcName,
                message=message,
            )
        except Exception:
            return
        finally:
            self._local.active = False


def _log_unhandled_exception(
    source: str,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return

    logging.getLogger("app.unhandled").error(
        "Unhandled exception | source=%s | error=%s",
        source,
        exc_value,
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def _install_exception_hooks() -> None:
    def _sys_hook(exc_type: type[BaseException], exc_value: BaseException, exc_traceback) -> None:
        _log_unhandled_exception("sys.excepthook", exc_type, exc_value, exc_traceback)

    sys.excepthook = _sys_hook

    if hasattr(threading, "excepthook"):
        def _thread_hook(args: threading.ExceptHookArgs) -> None:
            thread_name = args.thread.name if args.thread else "unknown"
            _log_unhandled_exception(f"thread:{thread_name}", args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_hook

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        exc = context.get("exception")
        if isinstance(exc, BaseException):
            _log_unhandled_exception("asyncio", type(exc), exc, exc.__traceback__)
            return

        logging.getLogger("app.unhandled").error(
            "Unhandled exception | source=asyncio | error=%s",
            context.get("message", "Unknown asyncio error"),
        )

    loop.set_exception_handler(_asyncio_exception_handler)


def configure_logging() -> None:
    # Ghi log ra cả terminal lẫn file để dễ debug local và giữ lịch sử chạy.
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "backend.log"

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(funcName)s | %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Nếu app đã có handler thì không add lại để tránh log bị lặp dòng.
    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)

        root_logger.addHandler(stream_handler)
        root_logger.addHandler(file_handler)

        if telegram_log_enabled():
            telegram_handler = TelegramErrorHandler(level=logging.ERROR)
            telegram_handler.setFormatter(formatter)
            root_logger.addHandler(telegram_handler)

    _install_exception_hooks()
