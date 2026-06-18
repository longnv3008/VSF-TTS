#!/usr/bin/env python
"""Đo tác động hardening text-quality trên label i724 (nguồn ASR) — KHÔNG cần re-run ASR.

So sánh:
  - BEFORE: label gốc pipeline đã lưu (cột `text` trong manifest).
  - AFTER : áp `clean_transcript` (đã vá blocklist promo-substring) lên CHÍNH label đó.

Vì lớp text-quality là TẤT ĐỊNH trên text, đây là before/after THẬT cho phần text-layer
(blocklist + promo-substring + repetition + normalize). KHÔNG bao gồm reject-by-prob (cần
no_speech_prob/avg_logprob live của faster-whisper — chỉ đo được khi re-run pipeline).

Chỉ số (đúng cho dữ liệu TTS — seg-WER không phản ánh được vì label rỗng vẫn = deletion):
  - usable      : số label pipeline phát ra dùng được (text != "" => transcript_status ready)
  - mislabel    : label NON-rỗng nhưng segment có lời thật (n_ref>=3) mà 0 từ đúng => POISON
  - spurious    : label NON-rỗng trên segment KHÔNG có lời (ref rỗng) => rác
  - precision   : (usable đúng) / (usable)  — usable đúng = label non-rỗng có >=1 từ đúng
  - seg-WER (usable, micro): chỉ trên label non-rỗng có ref>0 (chất lượng phần GIỮ LẠI)

Chạy:  python eval/wer/measure_hardening.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

WER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WER_DIR))

from score import norm_ref, read_references  # noqa: E402  (tái dùng logic sentinel/instrumental)
from vsf_wer import io_manifest as io  # noqa: E402
from vsf_wer import wer as W  # noqa: E402
from vsf_wer.normalize import load_non_lyric, normalize, tokens  # noqa: E402

VIDEO = "i724lraI93s"

# nạp text_quality (pure stdlib) theo đường dẫn — chạy từ repo root nên không bị types.py shadow
_TQ = (
    WER_DIR.parents[1]
    / "VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/segmentation/text_quality.py"
)
_spec = importlib.util.spec_from_file_location("text_quality", _TQ)
tq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tq)


def analyze(segs, refs, non_lyric, transform):
    """transform(raw_label) -> label pipeline phát. Trả dict chỉ số."""
    usable = usable_correct = mislabel = spurious = 0
    kept = []  # Counts cho label non-rỗng, n_ref>0 (seg-WER phần giữ lại)
    poison_ids = []
    for s in segs:
        emitted = transform(s.text)  # text pipeline thực sự ghi ra
        is_emitted = bool(emitted.strip())
        hyp_n = normalize(emitted, level="normalized", non_lyric=non_lyric)
        ref_n = norm_ref(refs.get(s.segment_id, ""), non_lyric, "normalized")
        c = W.align(tokens(ref_n), tokens(hyp_n))
        if is_emitted:
            usable += 1
            if c.n_ref >= 3 and c.cor == 0:
                mislabel += 1
                poison_ids.append(s.segment_id)
            elif c.n_ref == 0:
                spurious += 1
            if c.n_ref > 0:
                kept.append(c)
                if c.cor > 0:
                    usable_correct += 1
    precision = (usable_correct / usable) if usable else float("nan")
    seg_wer = W.micro_average(kept) if kept else float("nan")
    return {
        "usable": usable,
        "mislabel": mislabel,
        "spurious": spurious,
        "precision": precision,
        "seg_wer_usable": seg_wer,
        "poison_ids": poison_ids,
    }


def pct(x):
    return "—" if x != x else f"{x * 100:.1f}%"


def main() -> int:
    non_lyric = load_non_lyric(io.NON_LYRIC_CFG)
    segs = io.load_segments([VIDEO]).get(VIDEO, [])
    refs = read_references(VIDEO) or {}
    if not segs:
        print(f"LỖI: không thấy segment {VIDEO} trong manifest {io.MANIFEST}", file=sys.stderr)
        return 1

    before = analyze(segs, refs, non_lyric, transform=lambda t: t)
    after = analyze(segs, refs, non_lyric, transform=lambda t: tq.clean_transcript(t))

    print(f"=== Tác động hardening text-layer trên {VIDEO} ({len(segs)} segment) ===\n")
    hdr = f"{'chỉ số':<26}{'BEFORE':>10}{'AFTER':>10}"
    print(hdr)
    print("-" * len(hdr))
    print(f"{'usable label (emitted)':<26}{before['usable']:>10}{after['usable']:>10}")
    print(f"{'mislabel (POISON)':<26}{before['mislabel']:>10}{after['mislabel']:>10}")
    print(f"{'spurious (rác no-ref)':<26}{before['spurious']:>10}{after['spurious']:>10}")
    print(f"{'precision label usable':<26}{pct(before['precision']):>10}{pct(after['precision']):>10}")
    print(f"{'seg-WER (label giữ lại)':<26}{pct(before['seg_wer_usable']):>10}{pct(after['seg_wer_usable']):>10}")
    print(f"\npoison segment bị diệt: {sorted(set(before['poison_ids']) - set(after['poison_ids']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
