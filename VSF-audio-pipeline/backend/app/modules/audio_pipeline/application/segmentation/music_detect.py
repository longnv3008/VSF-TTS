"""Đoán video nhạc từ TITLE để bỏ qua WER gate.

Text VTT không phân biệt được nhạc vs nói (lời nhạc là text sạch, markup ratio = 0
trên các MV đã review). Title thì có tín hiệu ("Official MV", "ft.", "Lyrics"...).
Precision-first: thà miss video nhạc (gate vẫn chạy) hơn skip nhầm gate trên video nói.
keywords mở rộng được (operator thêm tên nghệ sĩ) để bắt title "song - artist".
"""

from __future__ import annotations

# Substring match (đã casefold). Khoảng trắng đầu " ft." tránh khớp "lift"/"craft".
DEFAULT_MUSIC_KEYWORDS: tuple[str, ...] = (
    "official mv",
    "music video",
    "lyric",
    "lyrics",
    "official audio",
    " ft.",
    " feat.",
    "m/v",
    "| official",
)


def is_music_title(title: str, *, keywords: tuple[str, ...]) -> bool:
    """True nếu title (casefold) chứa bất kỳ keyword nào (substring)."""
    if not title:
        return False
    low = title.casefold()
    return any(kw.casefold() in low for kw in keywords)
