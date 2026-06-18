from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable


def ensure_dir(path: Path) -> Path:
    # Tạo thư mục nếu chưa có và trả lại path để gọi chain thuận tiện hơn.
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    # Nếu file chưa tồn tại thì trả mảng rỗng để pipeline không phải check thêm.
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    # Ghi đè toàn bộ CSV để output luôn đồng bộ với dữ liệu mới nhất.
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def slugify(value: str) -> str:
    # Chuẩn hóa chuỗi về dạng an toàn cho tên file.
    safe = re.sub(r"[^\w\-\.]+", "_", value.strip())
    safe = re.sub(r"_+", "_", safe)
    return safe.strip("._") or "unknown"
