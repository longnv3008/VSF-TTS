"""WER/CER core — Levenshtein mức token có backtrace (pure-Python, stdlib).

WER = (S + D + I) / N, N = số token reference.
    S substitution, D deletion (ref có, hyp thiếu), I insertion (hyp dư).
Trả cả danh sách op (alignment) để in ví dụ lỗi trong báo cáo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import nan

# op tags
EQUAL = "="
SUB = "S"
DEL = "D"
INS = "I"


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
        """Tỉ lệ lỗi; nan nếu N=0 (ref rỗng)."""
        return self.errors / self.n_ref if self.n_ref else nan

    @property
    def spurious(self) -> bool:
        """ref rỗng nhưng hyp có token -> label phát dư (non-lyric)."""
        return self.n_ref == 0 and self.ins > 0


def align(ref: list[str], hyp: list[str]) -> Counts:
    """Levenshtein DP + backtrace. cost sub=1 nếu khác (0 nếu bằng), ins=del=1."""
    n, m = len(ref), len(hyp)
    # d[i][j] = chi phí align ref[:i] với hyp[:j]; bt = hướng truy vết
    d = [[0] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
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
            up = d[i - 1][j] + 1   # deletion
            left = d[i][j - 1] + 1  # insertion
            best = min(diag, up, left)
            d[i][j] = best
            if best == diag:
                bt[i][j] = tag
            elif best == up:
                bt[i][j] = DEL
            else:
                bt[i][j] = INS

    # truy vết từ (n,m) về (0,0)
    c = Counts(n_ref=n)
    i, j = n, m
    ops_rev: list[tuple[str, str | None, str | None]] = []
    while i > 0 or j > 0:
        tag = bt[i][j]
        if tag in (EQUAL, SUB):
            r, h = ref[i - 1], hyp[j - 1]
            ops_rev.append((tag, r, h))
            if tag == EQUAL:
                c.cor += 1
            else:
                c.sub += 1
            i, j = i - 1, j - 1
        elif tag == DEL:
            ops_rev.append((DEL, ref[i - 1], None))
            c.dele += 1
            i -= 1
        else:  # INS
            ops_rev.append((INS, None, hyp[j - 1]))
            c.ins += 1
            j -= 1
    c.ops = list(reversed(ops_rev))
    return c


def micro_average(counts_list: list[Counts]) -> float:
    """WER micro = Σ errors / Σ N, chỉ tính trên các item có N>0."""
    tot_err = sum(c.errors for c in counts_list if c.n_ref > 0)
    tot_n = sum(c.n_ref for c in counts_list if c.n_ref > 0)
    return tot_err / tot_n if tot_n else nan


def format_alignment(ops, max_ops: int = 40) -> str:
    """In alignment dạng REF/HYP căn cột, đánh dấu S/D/I — cho ví dụ lỗi."""
    shown = ops[:max_ops]
    ref_row, hyp_row, tag_row = [], [], []
    for tag, r, h in shown:
        r = r if r is not None else "*"
        h = h if h is not None else "*"
        w = max(len(r), len(h))
        ref_row.append(r.ljust(w))
        hyp_row.append(h.ljust(w))
        tag_row.append((" " if tag == EQUAL else tag).ljust(w))
    suffix = " ..." if len(ops) > max_ops else ""
    return (
        "REF: " + " ".join(ref_row) + suffix + "\n"
        "HYP: " + " ".join(hyp_row) + suffix + "\n"
        "     " + " ".join(tag_row) + suffix
    )
