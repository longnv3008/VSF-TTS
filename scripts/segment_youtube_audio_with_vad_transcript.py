"""
Segment YouTube WAV files into transcript-aligned sentence/phrase clips.

Pipeline:
  WAV in processed/audio + YouTube WebVTT in raw/youtube
  -> parse and de-duplicate VTT captions
  -> group captions into sentence/phrase units
  -> run local VAD
  -> align transcript units to VAD regions
  -> export segment WAV, transcript TXT, labels, and summaries
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VAD_DIR = PROJECT_ROOT / "VAD"
sys.path.insert(0, str(VAD_DIR))

# Module dùng chung với app backend (pure stdlib, import file trực tiếp tránh kéo app.*).
TEXT_QUALITY_DIR = (
    PROJECT_ROOT
    / "VSF-audio-pipeline"
    / "backend"
    / "app"
    / "modules"
    / "audio_pipeline"
    / "application"
    / "segmentation"
)
sys.path.insert(0, str(TEXT_QUALITY_DIR))

from batch_vad import MODEL_DIR, VADModel, run_vad_file  # noqa: E402
from text_quality import has_promo_marker, is_blocklisted, normalize_vlsp  # noqa: E402


TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})"
)
INLINE_TIMESTAMP_RE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>|<\d{2}:\d{2}\.\d{3}>")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SENTENCE_END_RE = re.compile(r"[.!?。！？…]+[\"')\]]*$")


@dataclass(frozen=True)
class TranscriptCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SentenceUnit:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float


def _print(message: str) -> None:
    print(message, flush=True)


def parse_timecode(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"invalid WebVTT timecode: {value}")


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def clean_caption_text(line: str) -> str:
    line = INLINE_TIMESTAMP_RE.sub(" ", line)
    line = TAG_RE.sub(" ", line)
    line = html.unescape(line)
    return SPACE_RE.sub(" ", line).strip()


def normalize_for_compare(text: str) -> str:
    return SPACE_RE.sub(" ", text.casefold()).strip()


def strip_known_prefix(text: str, prefix: str) -> str:
    text_norm = normalize_for_compare(text)
    prefix_norm = normalize_for_compare(prefix)
    if not text_norm.startswith(prefix_norm):
        return text

    candidate = text[len(prefix) :].strip()
    if candidate:
        return candidate
    return text


def parse_youtube_vtt(path: Path) -> list[TranscriptCue]:
    text = read_text_with_fallback(path)
    lines = text.splitlines()
    cues: list[TranscriptCue] = []
    i = 0
    previous_visible = ""

    while i < len(lines):
        match = TIMESTAMP_RE.search(lines[i])
        if not match:
            i += 1
            continue

        start = parse_timecode(match.group("start"))
        end = parse_timecode(match.group("end"))
        i += 1

        raw_lines: list[str] = []
        while i < len(lines) and lines[i].strip():
            raw_lines.append(lines[i])
            i += 1

        cleaned_lines: list[str] = []
        for raw_line in raw_lines:
            cleaned = clean_caption_text(raw_line)
            if not cleaned:
                continue
            if cleaned_lines and normalize_for_compare(cleaned) == normalize_for_compare(cleaned_lines[-1]):
                continue
            cleaned_lines.append(cleaned)

        if previous_visible and len(cleaned_lines) > 1:
            if normalize_for_compare(cleaned_lines[0]) == normalize_for_compare(previous_visible):
                cleaned_lines = cleaned_lines[1:]

        if not cleaned_lines:
            continue

        caption_text = SPACE_RE.sub(" ", " ".join(cleaned_lines)).strip()
        if previous_visible:
            caption_text = strip_known_prefix(caption_text, previous_visible)

        if caption_text and normalize_for_compare(caption_text) != normalize_for_compare(previous_visible):
            cues.append(TranscriptCue(start=start, end=end, text=caption_text))

        previous_visible = cleaned_lines[-1]

    return cues


def cues_to_sentence_units(
    cues: list[TranscriptCue],
    phrase_gap_sec: float,
    max_sentence_sec: float,
    min_sentence_sec: float,
) -> list[SentenceUnit]:
    cues = split_long_cues(cues, max_sentence_sec)
    units: list[SentenceUnit] = []
    words: list[str] = []
    start: float | None = None
    end: float | None = None

    def flush() -> None:
        nonlocal words, start, end
        if start is None or end is None or not words:
            words = []
            start = None
            end = None
            return
        text = SPACE_RE.sub(" ", " ".join(words)).strip()
        if text and end > start:
            if end - start >= min_sentence_sec or not units:
                units.append(SentenceUnit(start=start, end=end, text=text))
            else:
                prev = units.pop()
                units.append(
                    SentenceUnit(
                        start=prev.start,
                        end=end,
                        text=SPACE_RE.sub(" ", f"{prev.text} {text}").strip(),
                    )
                )
        words = []
        start = None
        end = None

    for cue in cues:
        if start is not None and end is not None:
            gap = cue.start - end
            duration = end - start
            projected_duration = cue.end - start
            if (
                gap >= phrase_gap_sec
                or duration >= max_sentence_sec
                or projected_duration > max_sentence_sec
            ):
                flush()

        if start is None:
            start = cue.start
        words.append(cue.text)
        end = cue.end

        duration = end - start
        if SENTENCE_END_RE.search(cue.text) and duration >= min_sentence_sec:
            flush()
        elif duration >= max_sentence_sec:
            flush()

    flush()
    return units


def split_long_cues(cues: list[TranscriptCue], max_sentence_sec: float) -> list[TranscriptCue]:
    split: list[TranscriptCue] = []
    for cue in cues:
        duration = cue.end - cue.start
        words = cue.text.split()
        if duration > max_sentence_sec and len(words) < 2:
            split.append(
                TranscriptCue(
                    start=cue.start,
                    end=min(cue.end, cue.start + max_sentence_sec),
                    text=cue.text,
                )
            )
            continue
        if duration <= max_sentence_sec or len(words) < 2:
            split.append(cue)
            continue

        chunk_count = max(1, int(duration // max_sentence_sec) + 1)
        words_per_chunk = max(1, (len(words) + chunk_count - 1) // chunk_count)
        chunk_duration = duration / chunk_count

        for idx in range(chunk_count):
            chunk_words = words[idx * words_per_chunk : (idx + 1) * words_per_chunk]
            if not chunk_words:
                continue
            chunk_start = cue.start + idx * chunk_duration
            chunk_end = cue.end if idx == chunk_count - 1 else cue.start + (idx + 1) * chunk_duration
            split.append(
                TranscriptCue(
                    start=chunk_start,
                    end=chunk_end,
                    text=" ".join(chunk_words),
                )
            )
    return split


def audio_id_to_video_id(audio_id: str) -> str:
    return audio_id[3:] if audio_id.startswith("yt_") else audio_id


def build_vtt_index(vtt_dir: Path) -> dict[str, Path]:
    index: dict[str, list[Path]] = {}
    if not vtt_dir.exists():
        return {}
    for path in sorted(vtt_dir.glob("*.vtt")):
        video_id = path.name.split("__", 1)[0]
        index.setdefault(video_id, []).append(path)

    selected: dict[str, Path] = {}
    for video_id, paths in index.items():
        vi_paths = [path for path in paths if path.name.endswith(".vi.vtt")]
        selected[video_id] = sorted(vi_paths or paths)[0]
    return selected


def collect_audio_items(audio_dir: Path, vtt_dir: Path, limit: int | None) -> list[dict]:
    if not audio_dir.exists():
        raise FileNotFoundError(f"audio dir does not exist: {audio_dir}")
    vtt_index = build_vtt_index(vtt_dir)
    items = []
    for wav_path in sorted(audio_dir.glob("*.wav")):
        audio_id = wav_path.stem
        video_id = audio_id_to_video_id(audio_id)
        items.append(
            {
                "audio_id": audio_id,
                "video_id": video_id,
                "wav": wav_path,
                "vtt": vtt_index.get(video_id),
            }
        )
    if limit is not None:
        return items[:limit]
    return items


def make_vad_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        sample_rate=args.sample_rate,
        chunk_ms=args.chunk_ms,
        model_chunk_ms=args.model_chunk_ms,
        context_ms=args.context_ms,
        reset_duration=args.reset_duration,
        threshold=args.threshold,
        negative_threshold=args.negative_threshold,
        min_volume=args.min_volume,
        start_secs=args.start_secs,
        stop_secs=args.stop_secs,
        merge_gap_secs=args.merge_gap_secs,
        min_speech_secs=args.min_speech_secs,
        segment_pad_secs=args.segment_pad_secs,
        refine_boundaries=args.refine_boundaries,
        refine_energy_db_below_peak=args.refine_energy_db_below_peak,
        refine_energy_min_rms=args.refine_energy_min_rms,
        refine_search_pad_ms=args.refine_search_pad_ms,
        refine_pad_ms=args.refine_pad_ms,
        refine_min_speech_ms=args.refine_min_speech_ms,
        refine_max_gap_ms=args.refine_max_gap_ms,
    )


def run_vad_regions(model: VADModel, wav_path: Path, vad_args: argparse.Namespace) -> tuple[float, list[SpeechRegion]]:
    duration, labeled = run_vad_file(model, wav_path, vad_args)
    regions = [
        SpeechRegion(start=float(row["start"]), end=float(row["end"]))
        for row in labeled
        if row["label"] == "speaking" and float(row["end"]) > float(row["start"])
    ]
    return duration, regions


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge_regions(regions: list[SpeechRegion], max_gap_sec: float) -> list[SpeechRegion]:
    if not regions:
        return []
    merged = [regions[0]]
    for region in regions[1:]:
        previous = merged[-1]
        if region.start - previous.end <= max_gap_sec:
            merged[-1] = SpeechRegion(start=previous.start, end=max(previous.end, region.end))
        else:
            merged.append(region)
    return merged


def align_units_to_vad(
    units: list[SentenceUnit],
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    merge_gap_sec: float,
    min_segment_sec: float,
    boundary_slack_sec: float,
) -> list[dict]:
    rows: list[dict] = []
    for unit in units:
        overlapping = [
            region
            for region in vad_regions
            if overlap_seconds(unit.start, unit.end, region.start, region.end) > 0.0
        ]
        overlapping = merge_regions(overlapping, merge_gap_sec)
        if overlapping:
            vad_start = min(region.start for region in overlapping)
            vad_end = max(region.end for region in overlapping)
            start = vad_start if abs(vad_start - unit.start) <= boundary_slack_sec else unit.start
            end = vad_end if abs(vad_end - unit.end) <= boundary_slack_sec else unit.end
            vad_status = "aligned"
        else:
            start = unit.start
            end = unit.end
            vad_status = "no_overlap"

        start = max(0.0, start - pad_sec)
        end = min(duration, end + pad_sec)
        if end - start < min_segment_sec:
            continue
        rows.append(
            {
                "start": start,
                "end": end,
                "text": unit.text,
                "transcript_status": "ready",
                "vad_status": vad_status,
            }
        )
    return rows


def vad_only_rows(
    vad_regions: list[SpeechRegion],
    duration: float,
    pad_sec: float,
    min_segment_sec: float,
    max_segment_sec: float,
) -> list[dict]:
    rows: list[dict] = []
    for region in vad_regions:
        start = max(0.0, region.start - pad_sec)
        end = min(duration, region.end + pad_sec)
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + max_segment_sec) if max_segment_sec > 0 else end
            if chunk_end - cursor >= min_segment_sec:
                rows.append(
                    {
                        "start": cursor,
                        "end": chunk_end,
                        "text": "",
                        "transcript_status": "missing",
                        "vad_status": "speech_region",
                    }
                )
            cursor = chunk_end
    return rows


def cut_wav_segment(src: Path, dst: Path, start_sec: float, end_sec: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as reader:
        params = reader.getparams()
        sample_rate = reader.getframerate()
        total_frames = reader.getnframes()
        start_frame = max(0, min(total_frames, int(round(start_sec * sample_rate))))
        end_frame = max(start_frame, min(total_frames, int(round(end_sec * sample_rate))))
        reader.setpos(start_frame)
        frames = reader.readframes(end_frame - start_frame)

    with wave.open(str(dst), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def manifest_path(path: Path | None) -> str:
    return "" if path is None else str(path.resolve())


def prepare_out_dir(out_dir: Path, overwrite: bool) -> None:
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        return
    if not overwrite:
        return
    for child in (
        out_dir / "segments",
        out_dir / "transcripts",
        out_dir / "labels.csv",
        out_dir / "labels.jsonl",
        out_dir / "audio_summary.csv",
        out_dir / "missing_transcripts.csv",
    ):
        if child.is_dir():
            shutil.rmtree(child)
        elif child.exists():
            child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_outputs(
    out_dir: Path,
    label_rows: list[dict],
    summaries: list[dict],
    label_fields: list[str],
    summary_fields: list[str],
) -> None:
    write_csv(out_dir / "labels.csv", label_rows, label_fields)
    write_jsonl(out_dir / "labels.jsonl", label_rows)
    write_csv(out_dir / "audio_summary.csv", summaries, summary_fields)
    missing = [row for row in summaries if row["transcript_status"] in {"missing", "empty"}]
    write_csv(out_dir / "missing_transcripts.csv", missing, summary_fields)


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def process_item(
    item: dict,
    model: VADModel,
    args: argparse.Namespace,
    vad_args: argparse.Namespace,
) -> tuple[list[dict], dict]:
    audio_id = item["audio_id"]
    video_id = item["video_id"]
    wav_path = item["wav"]
    vtt_path = item["vtt"]

    duration, vad_regions = run_vad_regions(model, wav_path, vad_args)
    transcript_status = "missing"
    cues: list[TranscriptCue] = []
    units: list[SentenceUnit] = []

    if vtt_path and vtt_path.exists() and vtt_path.stat().st_size > 0:
        cues = parse_youtube_vtt(vtt_path)
        units = cues_to_sentence_units(
            cues,
            phrase_gap_sec=args.phrase_gap_sec,
            max_sentence_sec=args.max_sentence_sec,
            min_sentence_sec=args.min_sentence_sec,
        )
        transcript_status = "ready" if units else "empty"

    if transcript_status == "ready":
        segment_specs = align_units_to_vad(
            units,
            vad_regions,
            duration=duration,
            pad_sec=args.pad_sec,
            merge_gap_sec=args.align_merge_gap_sec,
            min_segment_sec=args.min_segment_sec,
            boundary_slack_sec=args.vad_boundary_slack_sec,
        )
    else:
        segment_specs = vad_only_rows(
            vad_regions,
            duration=duration,
            pad_sec=args.pad_sec,
            min_segment_sec=args.min_segment_sec,
            max_segment_sec=args.max_vad_only_segment_sec,
        )
        for row in segment_specs:
            row["transcript_status"] = transcript_status

    label_rows: list[dict] = []
    segment_dir = args.out_dir / "segments" / audio_id
    transcript_dir = args.out_dir / "transcripts" / audio_id
    if segment_dir.exists():
        shutil.rmtree(segment_dir)
    if transcript_dir.exists():
        shutil.rmtree(transcript_dir)
    for idx, spec in enumerate(segment_specs, start=1):
        segment_id = f"{audio_id}__sent{idx:06d}"
        segment_file = segment_dir / f"{segment_id}.wav"
        transcript_file = transcript_dir / f"{segment_id}.txt"
        start = float(spec["start"])
        end = float(spec["end"])
        text = str(spec["text"])
        # Loại caption ảo giác phổ biến (exact + promo substring) + chuẩn hóa VLSP.
        text = "" if (is_blocklisted(text) or has_promo_marker(text)) else normalize_vlsp(text)
        transcript_status = spec["transcript_status"]
        if transcript_status == "ready" and not text:
            transcript_status = "missing"

        cut_wav_segment(wav_path, segment_file, start, end)
        write_text(transcript_file, text)

        label_rows.append(
            {
                "audio_id": audio_id,
                "video_id": video_id,
                "segment_id": segment_id,
                "segment_file": manifest_path(segment_file),
                "transcript_file": manifest_path(transcript_file),
                "start": f"{start:.3f}",
                "end": f"{end:.3f}",
                "duration": f"{end - start:.3f}",
                "text": text,
                "transcript_status": transcript_status,
                "vad_status": spec["vad_status"],
                "source_wav": manifest_path(wav_path),
                "source_vtt": manifest_path(vtt_path),
            }
        )

    summary = {
        "audio_id": audio_id,
        "video_id": video_id,
        "source_wav": manifest_path(wav_path),
        "source_vtt": manifest_path(vtt_path),
        "duration": f"{duration:.3f}",
        "transcript_status": transcript_status,
        "vtt_cues": len(cues),
        "sentence_units": len(units),
        "vad_regions": len(vad_regions),
        "segments": len(label_rows),
        "segments_with_text": sum(1 for row in label_rows if row["text"]),
        "segments_without_text": sum(1 for row in label_rows if not row["text"]),
    }
    return label_rows, summary


def print_validation(label_rows: list[dict], summaries: list[dict], total_inputs: int) -> None:
    durations = [float(row["duration"]) for row in label_rows]
    with_vtt = sum(1 for row in summaries if row["source_vtt"])
    missing_vtt = sum(1 for row in summaries if not row["source_vtt"])
    with_text = sum(1 for row in label_rows if row["text"])
    without_text = len(label_rows) - with_text
    no_segment = [row["audio_id"] for row in summaries if int(row["segments"]) == 0]
    too_short = sum(1 for value in durations if value < 0.3)
    too_long = sum(1 for value in durations if value > 12.0)

    _print("[summary]")
    _print(f"input_audio: {total_inputs}")
    _print(f"with_vtt: {with_vtt}")
    _print(f"missing_vtt: {missing_vtt}")
    _print(f"total_segments: {len(label_rows)}")
    _print(f"segments_with_text: {with_text}")
    _print(f"segments_without_text: {without_text}")
    if durations:
        _print(
            "duration_sec: "
            f"min={min(durations):.3f} avg={mean(durations):.3f} max={max(durations):.3f}"
        )
    _print(f"segments_lt_0.3s: {too_short}")
    _print(f"segments_gt_12s: {too_long}")
    _print(f"audio_without_segments: {len(no_segment)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cut YouTube processed WAVs into VAD/transcript-aligned sentence labels."
    )
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=PROJECT_ROOT
        / "VSF-audio-pipeline"
        / "data"
        / "processed"
        / "audio",
    )
    parser.add_argument(
        "--vtt-dir",
        type=Path,
        default=PROJECT_ROOT
        / "VSF-audio-pipeline"
        / "data"
        / "raw"
        / "youtube",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "pipeline_runs" / "youtube_sentence_labels",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip audio IDs already present in audio_summary.csv.")
    parser.add_argument(
        "--reprocess-status",
        action="append",
        default=[],
        choices=["ready", "missing", "empty"],
        help="With --resume, remove existing rows with this transcript_status and process them again.",
    )
    parser.add_argument(
        "--reprocess-audio-id",
        action="append",
        default=[],
        help="With --resume, remove existing rows for this audio_id and process it again.",
    )
    parser.add_argument("--limit", type=int, help="Process only the first N WAV files.")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=1,
        help="Rewrite manifest files after every N processed WAV files. Use 0 to write only at the end.",
    )

    parser.add_argument("--phrase-gap-sec", type=float, default=0.45)
    parser.add_argument("--max-sentence-sec", type=float, default=11.5)
    parser.add_argument("--min-sentence-sec", type=float, default=0.3)
    parser.add_argument("--min-segment-sec", type=float, default=0.08)
    parser.add_argument("--pad-sec", type=float, default=0.03)
    parser.add_argument("--align-merge-gap-sec", type=float, default=0.5)
    parser.add_argument("--vad-boundary-slack-sec", type=float, default=0.5)
    parser.add_argument(
        "--max-vad-only-segment-sec",
        type=float,
        default=12.0,
        help="Split transcript-missing VAD fallback regions into chunks no longer than this. Use 0 to disable.",
    )

    parser.add_argument("--model", type=Path, default=MODEL_DIR / "vad.onnx")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-ms", type=int, default=64)
    parser.add_argument("--model-chunk-ms", type=int, default=32)
    parser.add_argument("--context-ms", type=int, default=4)
    parser.add_argument("--reset-duration", type=float, default=5)
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--negative-threshold", type=float, default=None)
    parser.add_argument("--min-volume", type=float, default=0.6)
    parser.add_argument("--start-secs", type=float, default=0.1)
    parser.add_argument("--stop-secs", type=float, default=0.45)
    parser.add_argument("--merge-gap-secs", type=float, default=0.5)
    parser.add_argument("--min-speech-secs", type=float, default=0.08)
    parser.add_argument("--segment-pad-secs", type=float, default=0.12)
    parser.add_argument("--refine-boundaries", action="store_true")
    parser.add_argument("--refine-energy-db-below-peak", type=float, default=35.0)
    parser.add_argument("--refine-energy-min-rms", type=float, default=1e-4)
    parser.add_argument("--refine-search-pad-ms", type=float, default=700.0)
    parser.add_argument("--refine-pad-ms", type=float, default=0.0)
    parser.add_argument("--refine-min-speech-ms", type=float, default=64.0)
    parser.add_argument("--refine-max-gap-ms", type=float, default=160.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.audio_dir = args.audio_dir.resolve()
    args.vtt_dir = args.vtt_dir.resolve()
    args.out_dir = args.out_dir.resolve()
    if args.resume and args.overwrite:
        raise ValueError("--resume cannot be used with --overwrite")

    prepare_out_dir(args.out_dir, args.overwrite)
    items = collect_audio_items(args.audio_dir, args.vtt_dir, args.limit)
    _print(f"[scan] audio={len(items)} dir={args.audio_dir}")
    _print(f"[scan] vtt_dir={args.vtt_dir}")

    model = VADModel(
        model_path=str(args.model),
        chunk_ms=args.model_chunk_ms,
        context_ms=args.context_ms,
    )
    vad_args = make_vad_args(args)

    label_fields = [
        "audio_id",
        "video_id",
        "segment_id",
        "segment_file",
        "transcript_file",
        "start",
        "end",
        "duration",
        "text",
        "transcript_status",
        "vad_status",
        "source_wav",
        "source_vtt",
    ]
    summary_fields = [
        "audio_id",
        "video_id",
        "source_wav",
        "source_vtt",
        "duration",
        "transcript_status",
        "vtt_cues",
        "sentence_units",
        "vad_regions",
        "segments",
        "segments_with_text",
        "segments_without_text",
    ]

    all_rows: list[dict] = []
    summaries: list[dict] = []
    if args.resume:
        all_rows = read_csv_rows(args.out_dir / "labels.csv")
        summaries = read_csv_rows(args.out_dir / "audio_summary.csv")
        reprocess_statuses = set(args.reprocess_status)
        reprocess_audio_ids = {
            row["audio_id"]
            for row in summaries
            if row.get("audio_id") and row.get("transcript_status") in reprocess_statuses
        }
        reprocess_audio_ids.update(args.reprocess_audio_id)
        if reprocess_audio_ids:
            all_rows = [row for row in all_rows if row.get("audio_id") not in reprocess_audio_ids]
            summaries = [row for row in summaries if row.get("audio_id") not in reprocess_audio_ids]
            reason_parts = []
            if reprocess_statuses:
                reason_parts.append(f"status={','.join(sorted(reprocess_statuses))}")
            if args.reprocess_audio_id:
                reason_parts.append(f"audio_id={','.join(args.reprocess_audio_id)}")
            _print(f"[resume] reprocessing {len(reprocess_audio_ids)} audio file(s) ({'; '.join(reason_parts)})")
        completed_audio_ids = {row["audio_id"] for row in summaries if row.get("audio_id")}
        if completed_audio_ids:
            items = [item for item in items if item["audio_id"] not in completed_audio_ids]
            _print(
                f"[resume] loaded {len(summaries)} completed audio file(s), "
                f"{len(all_rows)} existing label row(s)"
            )
            _print(f"[resume] remaining audio={len(items)}")
        else:
            _print("[resume] no existing audio_summary.csv rows found")

    total_inputs = len(summaries) + len(items)
    for idx, item in enumerate(items, start=len(summaries) + 1):
        _print(
            f"[{idx}/{total_inputs}] {item['audio_id']} "
            f"vtt={'yes' if item['vtt'] else 'missing'}"
        )
        label_rows, summary = process_item(item, model, args, vad_args)
        all_rows.extend(label_rows)
        summaries.append(summary)
        _print(
            f"[labels] {item['audio_id']}: "
            f"{summary['segments']} segment(s), {summary['segments_with_text']} with text"
        )
        if args.checkpoint_every > 0 and idx % args.checkpoint_every == 0:
            write_outputs(args.out_dir, all_rows, summaries, label_fields, summary_fields)
            _print(f"[checkpoint] wrote manifests after {idx} audio file(s)")

    write_outputs(args.out_dir, all_rows, summaries, label_fields, summary_fields)

    print_validation(all_rows, summaries, total_inputs)
    _print(f"[done] labels: {args.out_dir / 'labels.csv'}")
    _print(f"[done] jsonl:  {args.out_dir / 'labels.jsonl'}")
    _print(f"[done] audio_summary: {args.out_dir / 'audio_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
