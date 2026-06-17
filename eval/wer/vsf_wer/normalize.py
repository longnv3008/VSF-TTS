"""Chuẩn hóa text tiếng Việt cho WER + lọc cụm non-lyric.

Hai mức (level):
    "raw"        : NFC -> lowercase -> bỏ dấu câu -> gom whitespace.
                   KHÔNG bỏ markup/non-lyric -> "[âm nhạc]" thành token "âm nhạc"
                   (cố ý: cho thấy rác làm phồng WER bao nhiêu).
    "normalized" : raw + bỏ markup [..]/>> + bỏ cụm non-lyric (blocklist) trước khi
                   strip dấu câu. Đây là headline.

Mặc định GIỮ dấu thanh (phonemic trong tiếng Việt). keep_diacritics=False cho biến thể
phụ (bỏ dấu) nếu cần báo cáo thêm.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# markup: [âm nhạc], [Vỗ tay], (Music) ... và marker hội thoại ">>"
_BRACKET_RE = re.compile(r"[\[\(][^\]\)]*[\]\)]")
_MARKER_RE = re.compile(r">>+|&gt;")
# giữ chữ (mọi ngôn ngữ) + số + khoảng trắng; bỏ phần còn lại (dấu câu, ký hiệu)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# âm tiết ad-lib không-lời: CHỈ xóa khi lặp >=2 token liên tiếp (tránh nuốt từ thật).
# Dấu thanh giữ nguyên nên "là/lả" KHÁC "la", "á" KHÁC "a" -> an toàn cho lời Việt.
_ADLIB = {"na", "la", "oh", "ohh", "ooh", "ooo", "hey", "ah", "uh", "yeah", "wo", "woah"}


def load_non_lyric(path: str | Path) -> list[str]:
    """Đọc blocklist cụm non-lyric. 1 dòng = 1 cụm; bỏ dòng trống và dòng '#'."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s.lower())
    # cụm dài lọc trước (tránh cụm ngắn ăn mất cụm dài)
    out.sort(key=len, reverse=True)
    return out


def strip_diacritics(text: str) -> str:
    """Bỏ dấu thanh + đ->d (biến thể phụ, không dùng mặc định)."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", no_marks)


def _collapse_adlib(text: str) -> str:
    """Xóa run >=2 token ad-lib liên tiếp (na na na, oh oh, la la la...)."""
    toks = text.split()
    out: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i] in _ADLIB:
            j = i
            while j < n and toks[j] in _ADLIB:
                j += 1
            if j - i >= 2:
                i = j
                continue
        out.append(toks[i])
        i += 1
    return " ".join(out)


def _remove_phrases(text: str, phrases: list[str]) -> str:
    """Bỏ cụm non-lyric khỏi chuỗi đã clean (token cách nhau 1 space).

    Khớp theo ranh giới token (space đầu/cuối) để 'na' không ăn vào 'nan'.
    text đã lowercase + bỏ dấu câu trước khi gọi.
    """
    s = f" {text} "
    for ph in phrases:
        ph_clean = _WS_RE.sub(" ", _PUNCT_RE.sub(" ", ph)).strip()
        if not ph_clean:
            continue
        s = re.sub(rf"(?<= ){re.escape(ph_clean)}(?= )", " ", s)
        s = _WS_RE.sub(" ", s)
    return s.strip()


def normalize(
    text: str,
    *,
    level: str = "normalized",
    non_lyric: list[str] | None = None,
    keep_diacritics: bool = True,
) -> str:
    """Trả chuỗi đã chuẩn hóa (token cách nhau 1 space)."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    s = s.lower()

    if level == "normalized":
        s = _BRACKET_RE.sub(" ", s)
        s = _MARKER_RE.sub(" ", s)

    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()

    if level == "normalized" and non_lyric:
        s = _remove_phrases(s, non_lyric)

    if level == "normalized":
        s = _collapse_adlib(s)

    if not keep_diacritics:
        s = strip_diacritics(s)

    return _WS_RE.sub(" ", s).strip()


def tokens(text: str) -> list[str]:
    """Token = âm tiết tách theo whitespace (chuẩn WER tiếng Việt)."""
    return text.split() if text else []


def chars(text: str) -> list[str]:
    """Ký tự cho CER (bỏ khoảng trắng)."""
    return [c for c in text if not c.isspace()]
