#!/usr/bin/env python
"""Sinh worksheet chấm WER per-segment từ manifest.

Mỗi video -> data/worksheets/<video_id>_worksheet.csv với cột:
    segment_id, source, start, end, duration, wav_path, hypothesis, reference
Cột `reference` để TRỐNG -> user nghe wav_path rồi điền lời hát ĐÚNG của đoạn đó.
Đoạn thuần non-lyric (nhạc nền / quảng cáo) -> để trống reference.

KHÔNG ghi đè worksheet đã có (tránh mất công điền) trừ khi --force.

Chạy:
    python eval/wer/build_worksheets.py
    python eval/wer/build_worksheets.py --force
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# console Windows (cp1258...) không encode được dấu tiếng Việt -> ép UTF-8, không crash
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vsf_wer import io_manifest as io  # noqa: E402

COLUMNS = [
    "segment_id",
    "source",
    "start",
    "end",
    "duration",
    "wav_path",
    "hypothesis",
    "reference",
]


def write_worksheet(video_id: str, segments: list[io.Segment], force: bool) -> str:
    io.WORKSHEETS_DIR.mkdir(parents=True, exist_ok=True)
    out = io.WORKSHEETS_DIR / f"{video_id}_worksheet.csv"
    if out.exists() and not force:
        return f"SKIP (đã có, dùng --force để ghi đè): {out}  [{len(segments)} seg]"
    # utf-8-sig: Excel trên Windows mở tiếng Việt đúng
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for s in segments:
            w.writerow(
                [
                    s.segment_id,
                    s.source,
                    f"{s.start:.3f}",
                    f"{s.end:.3f}",
                    f"{s.duration:.3f}",
                    s.wav_path,
                    s.text,
                    "",  # reference: user điền
                ]
            )
    return f"WROTE {out}  [{len(segments)} seg]"


def main() -> int:
    ap = argparse.ArgumentParser(description="Sinh worksheet chấm WER per-segment")
    ap.add_argument("--force", action="store_true", help="ghi đè worksheet đã có")
    args = ap.parse_args()

    if not io.MANIFEST.exists():
        print(f"LỖI: không thấy manifest {io.MANIFEST}", file=sys.stderr)
        return 1

    videos = io.load_videos()
    by_video = io.load_segments([v.video_id for v in videos])

    total = 0
    for v in videos:
        segs = by_video.get(v.video_id, [])
        total += len(segs)
        print(f"[{v.video_id}] {v.source:3} {len(segs):3} seg  {v.title}")
        print("  " + write_worksheet(v.video_id, segs, args.force))

    print(f"\nTổng: {total} segment / {len(videos)} video")
    print(f"Worksheet ở: {io.WORKSHEETS_DIR}")
    print("Bước tiếp: nghe wav_path, điền cột `reference`, rồi chạy score.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
