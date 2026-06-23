"""Chuẩn hóa transcript target cho fine-tune ASR (tiếng Việt).

Tự chứa (không import chéo eval/wer — project khác). NFC -> lowercase -> bỏ dấu câu ->
gom whitespace. GIỮ dấu thanh (phonemic trong tiếng Việt). Cùng phương pháp với
eval/wer/vsf_wer/normalize ở mức "raw".
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_target(text: str | None) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text)).lower()
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()
