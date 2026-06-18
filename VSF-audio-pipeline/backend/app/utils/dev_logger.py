from __future__ import annotations

import logging
from pprint import pformat
from typing import Any


def get_logger(name: str) -> logging.Logger:
    # Trả về logger theo tên module để log có nguồn rõ ràng.
    return logging.getLogger(name)


def dev_log(label: str, data: Any | None = None) -> None:
    """Small helper for local terminal debugging during development."""
    if data is None:
        print(f"[DEV] {label}")
        return
    print(f"[DEV] {label}: {pformat(data)}")
