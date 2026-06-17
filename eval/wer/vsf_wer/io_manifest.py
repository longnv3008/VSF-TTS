"""Đọc manifest segment + config video. Lọc 3 video target, sửa đường WAV.

Manifest: external_repos/VSF-audio-pipeline/data/metadata/batch_001_segments.csv
Cột dùng: video_id, segment_id, segment_file, text, transcript_source, start, end, duration, title.
Hypothesis = cột `text` (= nội dung file .txt label), không cần đọc 113 file lẻ.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# vsf_wer/io_manifest.py -> wer -> eval -> TTS (repo root)
REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_DIR = REPO_ROOT / "external_repos" / "VSF-audio-pipeline"
MANIFEST = PIPELINE_DIR / "data" / "metadata" / "batch_001_segments.csv"

WER_DIR = Path(__file__).resolve().parents[1]  # eval/wer
CONFIG_DIR = WER_DIR / "config"
VIDEOS_CFG = CONFIG_DIR / "videos.txt"
NON_LYRIC_CFG = CONFIG_DIR / "non_lyric.txt"
LYRICS_DIR = WER_DIR / "data" / "lyrics"
WORKSHEETS_DIR = WER_DIR / "data" / "worksheets"
REPORTS_DIR = WER_DIR / "reports"


@dataclass
class VideoCfg:
    video_id: str
    source: str       # vtt | asr
    title: str


@dataclass
class Segment:
    video_id: str
    segment_id: str
    source: str
    start: float
    end: float
    duration: float
    text: str         # hypothesis (label do pipeline tạo)
    wav_path: str


def load_videos(path: str | Path = VIDEOS_CFG) -> list[VideoCfg]:
    """Đọc config/videos.txt: dòng `video_id,source,title` (bỏ dòng trống/'#')."""
    out: list[VideoCfg] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(",", 2)
        if len(parts) < 2:
            continue
        vid, src = parts[0].strip(), parts[1].strip()
        title = parts[2].strip() if len(parts) > 2 else ""
        out.append(VideoCfg(vid, src, title))
    return out


def resolve_wav(raw: str) -> str:
    """Sửa đường WAV manifest (/app/data/... hoặc /data/...) -> đường repo thật."""
    raw = raw.replace("\\", "/")
    key = "data/processed/"
    idx = raw.find(key)
    if idx == -1:
        return raw
    return str(PIPELINE_DIR / raw[idx:])


def load_segments(
    video_ids: list[str],
    manifest: str | Path = MANIFEST,
) -> dict[str, list[Segment]]:
    """Trả dict video_id -> list[Segment] đã sort theo segment_id."""
    wanted = set(video_ids)
    by_video: dict[str, list[Segment]] = {v: [] for v in video_ids}
    with open(manifest, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            vid = row["video_id"]
            if vid not in wanted:
                continue

            def _f(key: str) -> float:
                try:
                    return float(row.get(key) or 0)
                except ValueError:
                    return 0.0

            by_video[vid].append(
                Segment(
                    video_id=vid,
                    segment_id=row["segment_id"],
                    source=row.get("transcript_source", ""),
                    start=_f("start"),
                    end=_f("end"),
                    duration=_f("duration"),
                    text=row.get("text", "") or "",
                    wav_path=resolve_wav(row.get("segment_file", "")),
                )
            )
    for v in by_video:
        by_video[v].sort(key=lambda s: s.segment_id)
    return by_video
