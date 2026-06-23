"""WER micro-average cho eval fine-tune ASR.

Token-WER (Levenshtein), tự chứa — cùng phương pháp eval/wer/vsf_wer/wer.py nhưng không
import chéo. Chuẩn hóa qua normalize_target trước khi token để khỏi phồng WER vì định dạng.
"""

from __future__ import annotations

from finetune_asr.text_norm import normalize_target


def _edit_distance(ref: list[str], hyp: list[str]) -> int:
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        ri = ref[i - 1]
        for j in range(1, m + 1):
            sub = 0 if ri == hyp[j - 1] else 1
            curr[j] = min(prev[j - 1] + sub, prev[j] + 1, curr[j - 1] + 1)
        prev = curr
    return prev[m]


def score_wer(references: list[str], hypotheses: list[str]) -> float:
    """Micro WER = tổng (S+D+I) / tổng token reference. ref rỗng bị bỏ khỏi mẫu số."""
    if len(references) != len(hypotheses):
        raise ValueError("references và hypotheses phải cùng độ dài")
    tot_err, tot_n = 0, 0
    for ref_s, hyp_s in zip(references, hypotheses):
        ref = normalize_target(ref_s).split()
        hyp = normalize_target(hyp_s).split()
        if not ref:
            continue
        tot_err += _edit_distance(ref, hyp)
        tot_n += len(ref)
    return tot_err / tot_n if tot_n else 0.0
