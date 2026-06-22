"""WER canonical tiếng Việt — port stdlib từ eval/wer/vsf_wer (normalize + wer).

Dùng cho manual WER review: so label `text` (hypothesis) với reference người nghe.
Token = âm tiết tách theo whitespace. Giữ dấu thanh (phonemic). Không import chéo
sang eval/wer (project riêng) — copy logic tối thiểu vào backend.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from math import nan

_BRACKET_RE = re.compile(r"[\[\(][^\]\)]*[\]\)]")
_MARKER_RE = re.compile(r">>+|&gt;")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_ADLIB = {"na", "la", "oh", "ohh", "ooh", "ooo", "hey", "ah", "uh", "yeah", "wo", "woah"}


def _collapse_adlib(text: str) -> str:
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


def normalize(text: str, *, level: str = "normalized", keep_diacritics: bool = True) -> str:
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text)).lower()
    if level == "normalized":
        s = _BRACKET_RE.sub(" ", s)
        s = _MARKER_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    if level == "normalized":
        s = _collapse_adlib(s)
    if not keep_diacritics:
        s = s.replace("đ", "d").replace("Đ", "D")
        decomposed = unicodedata.normalize("NFD", s)
        s = "".join(c for c in decomposed if not unicodedata.combining(c))
        s = unicodedata.normalize("NFC", s)
    return _WS_RE.sub(" ", s).strip()


def tokens(text: str) -> list[str]:
    return text.split() if text else []


EQUAL, SUB, DEL, INS = "=", "S", "D", "I"


@dataclass
class Counts:
    sub: int = 0
    dele: int = 0
    ins: int = 0
    cor: int = 0
    n_ref: int = 0
    ops: list[tuple[str, str | None, str | None]] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return self.sub + self.dele + self.ins

    @property
    def wer(self) -> float:
        return self.errors / self.n_ref if self.n_ref else nan

    @property
    def spurious(self) -> bool:
        return self.n_ref == 0 and self.ins > 0


def align(ref: list[str], hyp: list[str]) -> Counts:
    """Levenshtein DP + backtrace (sub=1 nếu khác, ins=del=1)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    bt: list[list[str | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
        bt[i][0] = DEL
    for j in range(1, m + 1):
        d[0][j] = j
        bt[0][j] = INS
    for i in range(1, n + 1):
        ri = ref[i - 1]
        for j in range(1, m + 1):
            if ri == hyp[j - 1]:
                sub_cost, tag = 0, EQUAL
            else:
                sub_cost, tag = 1, SUB
            diag = d[i - 1][j - 1] + sub_cost
            up = d[i - 1][j] + 1
            left = d[i][j - 1] + 1
            best = min(diag, up, left)
            d[i][j] = best
            bt[i][j] = tag if best == diag else (DEL if best == up else INS)

    c = Counts(n_ref=n)
    i, j = n, m
    ops_rev: list[tuple[str, str | None, str | None]] = []
    while i > 0 or j > 0:
        tag = bt[i][j]
        if tag in (EQUAL, SUB):
            ops_rev.append((tag, ref[i - 1], hyp[j - 1]))
            if tag == EQUAL:
                c.cor += 1
            else:
                c.sub += 1
            i, j = i - 1, j - 1
        elif tag == DEL:
            ops_rev.append((DEL, ref[i - 1], None))
            c.dele += 1
            i -= 1
        else:
            ops_rev.append((INS, None, hyp[j - 1]))
            c.ins += 1
            j -= 1
    c.ops = list(reversed(ops_rev))
    return c


def micro_average(counts_list: list[Counts]) -> float:
    tot_err = sum(c.errors for c in counts_list if c.n_ref > 0)
    tot_n = sum(c.n_ref for c in counts_list if c.n_ref > 0)
    return tot_err / tot_n if tot_n else nan
