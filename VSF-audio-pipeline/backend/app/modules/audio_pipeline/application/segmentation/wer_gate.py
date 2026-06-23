"""WER gate: so ASR (hypothesis) với VTT (reference) ở mức từng segment.

Dùng để QA alignment sau khi bỏ ASR fallback — segment có WER cao nghĩa là
caption VTT lệch tiếng nói thật -> flag review. Token-WER (Levenshtein) trên text
đã chuẩn hóa qua wer_canonical.normalize (markup-strip + collapse ad-lib, giữ dấu)
để markup/ad-lib trong VTT không phồng WER giả. Báo cáo offline canonical vẫn ở eval/wer.
"""

from __future__ import annotations

from app.modules.audio_pipeline.application.segmentation.wer_canonical import normalize, tokens


def _tokens(text: str) -> list[str]:
    """Token mức từ trên text đã chuẩn hóa (markup-strip + collapse ad-lib, giữ dấu)."""
    return tokens(normalize(text, level="normalized", keep_diacritics=True))


def _edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein mức token (sub/del/ins cost = 1)."""
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        ri = ref[i - 1]
        for j in range(1, m + 1):
            sub_cost = 0 if ri == hyp[j - 1] else 1
            curr[j] = min(prev[j - 1] + sub_cost, prev[j] + 1, curr[j - 1] + 1)
        prev = curr
    return prev[m]


def segment_wer(reference: str, hypothesis: str) -> float:
    """WER = (S+D+I)/N theo token. ref rỗng -> 0.0 (không gate được)."""
    ref = _tokens(reference)
    hyp = _tokens(hypothesis)
    if not ref:
        return 0.0
    return _edit_distance(ref, hyp) / len(ref)
