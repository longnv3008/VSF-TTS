"""Lớp lọc + chuẩn hóa text cho nhãn ASR/VTT (pure stdlib, dùng chung app + scripts).

Ba lớp phòng ngự chống "text rác / ảo giác" của ASR autoregressive (Whisper) khi gặp
khoảng lặng/nhiễu, theo research doc Toi_Uu_Hoa_Luong_ASR_SER_Vietnamese.md:
  1. Reject theo xác suất (no_speech_prob cao + avg_logprob thấp) -> rỗng.
  2. Blocklist exact-string các cụm ảo giác phổ biến (lời cảm ơn/đăng ký kênh...) -> rỗng.
  3. Phát hiện vòng lặp lặp cụm quá ngưỡng -> rỗng.
Cuối cùng chuẩn hóa quy ước VLSP (gộp acronym đánh vần, giữ tên riêng EN), bảo tồn dấu
thanh + dấu câu nội dung.

QUAN TRỌNG: module này CHỈ import stdlib (re, unicodedata) và KHÔNG import `app.*` để
scripts ở repo root (env không có torch/pydantic) import trực tiếp được:
    sys.path.insert(0, "<.../application/segmentation>"); import text_quality
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- #
# Seed data (mở rộng được)
# --------------------------------------------------------------------------- #

# Cụm ảo giác phổ biến (so khớp exact-string sau khi chuẩn hóa so sánh). Lower-case.
_BLOCKLIST_PHRASES = (
    "cảm ơn các bạn đã theo dõi",
    "cảm ơn các bạn đã xem video",
    "cảm ơn các bạn đã xem",
    "cảm ơn các bạn đã lắng nghe",
    "cảm ơn đã theo dõi",
    "hãy đăng ký kênh",
    "đừng quên đăng ký kênh",
    "nhớ đăng ký kênh",
    "hãy like và đăng ký kênh",
    "hãy nhấn like và đăng ký kênh",
    "hẹn gặp lại các bạn",
    "ghiền mì gõ",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
)

# Cụm promo kênh đủ ĐẶC TRƯNG để khớp SUBSTRING an toàn (gần như không có trong lời hát/nói
# thật). Khác _BLOCKLIST_PHRASES (khớp exact): các cụm này drop CẢ KHI có chữ thừa quanh nó —
# bắt hallucination kiểu "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"
# mà exact-match bỏ lọt. Lower-case canonical (chuẩn hóa khi so khớp).
_PROMO_SUBSTRINGS = (
    "đăng ký kênh",
    "subscribe cho kênh",
    "ghiền mì gõ",
    "la la school",
    "bỏ lỡ những video",
    "nhấn chuông",
    "like và đăng ký",
)

# Acronym đánh vần -> viết liền (VLSP). Lower-case canonical.
_ACRONYMS = ("nato", "fifa", "asean", "wto", "fbi", "atm", "usb", "gdp", "wifi")

# Tên riêng EN phổ biến: giữ chữ Latin gốc, không phiên âm. lower-case key -> canonical.
_EN_PROPER_NOUNS = {
    "youtube": "YouTube",
    "facebook": "Facebook",
    "tiktok": "TikTok",
    "google": "Google",
    "instagram": "Instagram",
}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

# Acronym đánh vần: các chữ cái cách nhau bằng >=1 dấu cách/chấm/gạch (KHÔNG khớp dạng
# đã viết liền sẵn -> giữ nguyên case dạng liền). Vd: "n a t o", "n.a.t.o", "n-a-t-o".
_ACRONYM_RES = tuple(
    (re.compile(r"\b" + r"[\s.\-]+".join(list(a)) + r"\b", re.IGNORECASE), a)
    for a in _ACRONYMS
)
_EN_RES = tuple(
    (re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE), v)
    for k, v in _EN_PROPER_NOUNS.items()
)


def _norm_compare(text: str) -> str:
    """Chuẩn hóa để so khớp blocklist: NFC + casefold + bỏ dấu câu + gom whitespace."""
    s = unicodedata.normalize("NFC", str(text)).casefold()
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


_BLOCKLIST_NORM = frozenset(_norm_compare(p) for p in _BLOCKLIST_PHRASES)
_PROMO_NORM = tuple(_norm_compare(p) for p in _PROMO_SUBSTRINGS)


def is_blocklisted(text: str) -> bool:
    """True nếu text (sau chuẩn hóa) trùng KHỚP TOÀN BỘ một cụm ảo giác.

    Khớp toàn bộ (không phải substring) để câu thật chứa cụm này vẫn được giữ.
    """
    if not text:
        return False
    return _norm_compare(text) in _BLOCKLIST_NORM


def has_promo_marker(text: str) -> bool:
    """True nếu text CHỨA (substring) một cụm promo kênh đặc trưng (`_PROMO_SUBSTRINGS`).

    Khác `is_blocklisted` (exact): bắt hallucination promo có chữ thừa quanh cụm. Các cụm
    này đủ đặc trưng để khớp substring không giết câu thật (vd "đăng ký kênh", "ghiền mì gõ").
    """
    if not text:
        return False
    norm = _norm_compare(text)
    return any(p in norm for p in _PROMO_NORM)


def collapse_repetition(text: str, max_repeat: int = 6) -> str:
    """Cắt run token lặp liên tiếp xuống tối đa `max_repeat` bản (giữ từ thật)."""
    if not text:
        return ""
    out: list[str] = []
    run_token: str | None = None
    run_len = 0
    for tok in text.split():
        if tok == run_token:
            run_len += 1
        else:
            run_token = tok
            run_len = 1
        if run_len <= max_repeat:
            out.append(tok)
    return " ".join(out)


def has_excessive_repetition(text: str, limit: int = 10) -> bool:
    """True nếu có 1 token lặp liên tiếp QUÁ `limit` lần (vòng lặp ảo giác)."""
    if not text:
        return False
    run_token: str | None = None
    run_len = 0
    for tok in text.split():
        if tok == run_token:
            run_len += 1
        else:
            run_token = tok
            run_len = 1
        if run_len > limit:
            return True
    return False


def normalize_vlsp(text: str) -> str:
    """Chuẩn hóa quy ước VLSP, bảo tồn dấu thanh + dấu câu nội dung.

    - Gộp acronym đánh vần ("n a t o" -> "nato").
    - Giữ tên riêng EN ở dạng Latin canonical ("youtube" -> "YouTube").
    - Gom whitespace. KHÔNG lowercase, KHÔNG bỏ dấu câu (text thường giữ nguyên).
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    for pattern, repl in _ACRONYM_RES:
        s = pattern.sub(repl, s)
    for pattern, repl in _EN_RES:
        s = pattern.sub(repl, s)
    return _WS_RE.sub(" ", s).strip()


def clean_transcript(
    text: str | None,
    *,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
    no_speech_max: float = 0.6,
    logprob_min: float = -1.0,
    repetition_limit: int = 10,
) -> str:
    """Áp 3 lớp lọc rồi chuẩn hóa. Trả "" nếu phân đoạn bị loại.

    Reject-by-prob cần CẢ no_speech_prob > no_speech_max VÀ avg_logprob < logprob_min
    (đồng thời) để tránh loại nhầm giọng nói thật mà model thiếu tự tin.
    """
    if not text or not text.strip():
        return ""
    if (
        no_speech_prob is not None
        and avg_logprob is not None
        and no_speech_prob > no_speech_max
        and avg_logprob < logprob_min
    ):
        return ""
    if is_blocklisted(text) or has_promo_marker(text):
        return ""
    if has_excessive_repetition(text, limit=repetition_limit):
        return ""
    return normalize_vlsp(text)
