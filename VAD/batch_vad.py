import argparse
import csv
import sys
import wave
from pathlib import Path

import numpy as np


MODEL_DIR = Path(__file__).resolve().parent / "models" / "vad" / "1"
sys.path.insert(0, str(MODEL_DIR))

from vad import VADModel, VADParams, VADSession  # noqa: E402


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        if channels != 1 or sample_width != 2:
            raise ValueError(
                f"{path} must be mono 16-bit PCM, got {channels} channels and {sample_width} bytes/sample"
            )
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return sample_rate, audio


def events_to_speech_segments(events: list[dict], duration: float) -> list[dict]:
    segments = []
    active_start = None

    for event in events:
        event_type = event["signal_type"]
        event_at = float(event["signal_at"])
        if event_type == "SPEAKING":
            active_start = event_at if active_start is None else min(active_start, event_at)
        elif event_type == "QUIET" and active_start is not None:
            end = max(active_start, min(event_at, duration))
            segments.append({"start": active_start, "end": end})
            active_start = None

    if active_start is not None:
        segments.append({"start": active_start, "end": duration})

    return segments


def merge_speech_segments(
    segments: list[dict],
    merge_gap_secs: float,
    min_speech_secs: float,
) -> list[dict]:
    filtered = [
        {"start": segment["start"], "end": segment["end"]}
        for segment in segments
        if segment["end"] - segment["start"] >= min_speech_secs
    ]
    if not filtered:
        return []

    merged = [filtered[0]]
    for segment in filtered[1:]:
        previous = merged[-1]
        if segment["start"] - previous["end"] <= merge_gap_secs:
            previous["end"] = max(previous["end"], segment["end"])
        else:
            merged.append(segment)
    return merged


def _fill_short_mask_gaps(mask: np.ndarray, max_gap_frames: int) -> np.ndarray:
    if max_gap_frames <= 0 or not mask.any():
        return mask

    filled = mask.copy()
    speech_idx = np.flatnonzero(filled)
    start = int(speech_idx[0])
    end = int(speech_idx[-1])
    i = start
    while i <= end:
        if filled[i]:
            i += 1
            continue
        gap_start = i
        while i <= end and not filled[i]:
            i += 1
        if i - gap_start <= max_gap_frames:
            filled[gap_start:i] = True
    return filled


def _remove_short_mask_runs(mask: np.ndarray, min_run_frames: int) -> np.ndarray:
    if min_run_frames <= 1 or not mask.any():
        return mask

    cleaned = mask.copy()
    i = 0
    n = len(cleaned)
    while i < n:
        if not cleaned[i]:
            i += 1
            continue
        run_start = i
        while i < n and cleaned[i]:
            i += 1
        if i - run_start < min_run_frames:
            cleaned[run_start:i] = False
    return cleaned


def _pad_mask_runs(mask: np.ndarray, pad_frames: int) -> np.ndarray:
    if pad_frames <= 0 or not mask.any():
        return mask

    padded = mask.copy()
    speech_idx = np.flatnonzero(mask)
    start = max(0, int(speech_idx[0]) - pad_frames)
    end = min(len(mask), int(speech_idx[-1]) + pad_frames + 1)
    padded[start:end] = True
    return padded


def mask_to_segments(frames: list[dict], mask: np.ndarray) -> list[dict]:
    segments = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        run_start = i
        while i < n and mask[i]:
            i += 1
        segments.append(
            {
                "start": frames[run_start]["start"],
                "end": frames[i - 1]["end"],
            }
        )
    return segments


def overlap_secs(a: dict, b: dict) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def refine_speech_segments(
    speech_segments: list[dict],
    frames: list[dict],
    duration: float,
    args: argparse.Namespace,
) -> list[dict]:
    if not speech_segments or not frames:
        return speech_segments

    rms = np.array([frame["rms"] for frame in frames], dtype=np.float32)
    peak = float(rms.max(initial=0.0))
    if peak <= 0.0:
        return []

    frame_ms = args.model_chunk_ms
    energy_threshold = max(
        args.refine_energy_min_rms,
        peak * (10.0 ** (-args.refine_energy_db_below_peak / 20.0)),
    )
    energy_mask = rms >= energy_threshold
    energy_mask = _fill_short_mask_gaps(
        energy_mask,
        round(args.refine_max_gap_ms / frame_ms),
    )
    energy_mask = _remove_short_mask_runs(
        energy_mask,
        round(args.refine_min_speech_ms / frame_ms),
    )
    energy_mask = _pad_mask_runs(
        energy_mask,
        round(args.refine_pad_ms / frame_ms),
    )

    energy_segments = mask_to_segments(frames, energy_mask)
    if not energy_segments:
        return []

    refined = []
    search_pad = args.refine_search_pad_ms / 1000.0
    for segment in speech_segments:
        rough = {
            "start": max(0.0, segment["start"]),
            "end": min(duration, segment["end"]),
        }
        search = {
            "start": max(0.0, rough["start"] - search_pad),
            "end": min(duration, rough["end"] + search_pad),
        }
        candidates = [
            energy_segment
            for energy_segment in energy_segments
            if overlap_secs(energy_segment, search) > 0.0
            and overlap_secs(energy_segment, rough) > 0.0
        ]
        if not candidates:
            candidates = [
                energy_segment
                for energy_segment in energy_segments
                if overlap_secs(energy_segment, search) > 0.0
            ]
        if not candidates:
            continue

        refined.append(
            {
                "start": min(candidate["start"] for candidate in candidates),
                "end": max(candidate["end"] for candidate in candidates),
            }
        )

    return merge_speech_segments(refined, args.merge_gap_secs, args.min_speech_secs)


def build_labeled_segments(speech_segments: list[dict], duration: float) -> list[dict]:
    rows = []
    cursor = 0.0

    for segment in speech_segments:
        start = max(0.0, min(segment["start"], duration))
        end = max(start, min(segment["end"], duration))
        if start > cursor:
            rows.append({"label": "quiet", "start": cursor, "end": start})
        if end > start:
            rows.append({"label": "speaking", "start": start, "end": end})
        cursor = max(cursor, end)

    if cursor < duration:
        rows.append({"label": "quiet", "start": cursor, "end": duration})

    return rows


def run_vad_file(
    model: VADModel,
    path: Path,
    args: argparse.Namespace,
) -> tuple[float, list[dict]]:
    sample_rate, audio = read_wav(path)
    if sample_rate != args.sample_rate:
        raise ValueError(f"{path} has sample rate {sample_rate}; expected {args.sample_rate}")

    params = VADParams(
        confidence=args.threshold,
        negative_confidence=args.negative_threshold,
        start_secs=args.start_secs,
        stop_secs=args.stop_secs,
        min_volume=args.min_volume,
    )
    session = VADSession(
        param=params,
        context_ms=args.context_ms,
        chunk_ms=args.model_chunk_ms,
        sample_rate=sample_rate,
    )
    state, context = session.get_state()
    events = []
    frames = []
    request_chunk_size = int(args.chunk_ms * sample_rate / 1000)
    model_chunk_size = int(args.model_chunk_ms * sample_rate / 1000)

    for offset in range(0, len(audio), request_chunk_size):
        chunk = audio[offset : offset + request_chunk_size]
        if len(chunk) < request_chunk_size:
            chunk = np.pad(chunk, (0, request_chunk_size - len(chunk)))

        probs, next_state, next_context = model.detect(
            chunk.reshape(1, -1),
            context.reshape(1, -1),
            state.reshape(1, 2, 128),
            sample_rate,
        )
        probas = np.array(probs)[:, 0].flatten()
        events.extend(session.process(chunk, probas))

        for prob_idx, probability in enumerate(probas):
            frame_start_sample = offset + prob_idx * model_chunk_size
            frame_end_sample = min(frame_start_sample + model_chunk_size, len(audio))
            if frame_start_sample >= len(audio):
                continue
            frame = audio[frame_start_sample:frame_end_sample].astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(frame * frame))) if len(frame) else 0.0
            frames.append(
                {
                    "start": frame_start_sample / sample_rate,
                    "end": frame_end_sample / sample_rate,
                    "probability": float(probability),
                    "rms": rms,
                }
            )

        if session.is_reset(args.reset_duration):
            session.reset_state()
            state, context = session.get_state()
        else:
            state = next_state[:, 0, :]
            context = next_context[0]

    duration = len(audio) / sample_rate
    speech = events_to_speech_segments(events, duration)
    if args.refine_boundaries:
        speech = refine_speech_segments(speech, frames, duration, args)
    speech = merge_speech_segments(speech, args.merge_gap_secs, args.min_speech_secs)
    return duration, build_labeled_segments(speech, duration)


def collect_wav_files(input_path: Path, extra_paths: list[Path]) -> list[Path]:
    files = []
    if input_path.is_dir():
        files.extend(sorted(input_path.glob("*.wav")))
    elif input_path.is_file():
        files.append(input_path)
    else:
        raise FileNotFoundError(input_path)

    files.extend(extra_paths)
    unique = []
    seen = set()
    for path in files:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline VAD and export speaking/quiet segments.")
    parser.add_argument("--input", type=Path, default=Path("..") / "tmp")
    parser.add_argument("--extra", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("outputs") / "vad_segments.csv")
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
    parser.add_argument("--refine-boundaries", action="store_true",
                        help="Refine offline segment boundaries with frame-level RMS inside VAD rough segments.")
    parser.add_argument("--refine-energy-db-below-peak", type=float, default=35.0,
                        help="RMS gate for refinement: peak RMS minus this many dB.")
    parser.add_argument("--refine-energy-min-rms", type=float, default=1e-4,
                        help="Minimum RMS floor for refinement.")
    parser.add_argument("--refine-search-pad-ms", type=float, default=700.0,
                        help="How far around each VAD rough segment to search for energy boundaries.")
    parser.add_argument("--refine-pad-ms", type=float, default=0.0,
                        help="Optional padding around refined energy runs.")
    parser.add_argument("--refine-min-speech-ms", type=float, default=64.0,
                        help="Drop isolated refined speech runs shorter than this.")
    parser.add_argument("--refine-max-gap-ms", type=float, default=160.0,
                        help="Fill internal energy gaps shorter than this during refinement.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = VADModel(
        model_path=str(args.model),
        chunk_ms=args.model_chunk_ms,
        context_ms=args.context_ms,
    )
    files = collect_wav_files(args.input, args.extra)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "label", "start", "end", "duration"],
        )
        writer.writeheader()
        for path in files:
            duration, segments = run_vad_file(model, path, args)
            for segment in segments:
                writer.writerow(
                    {
                        "file": str(path),
                        "label": segment["label"],
                        "start": f"{segment['start']:.3f}",
                        "end": f"{segment['end']:.3f}",
                        "duration": f"{segment['end'] - segment['start']:.3f}",
                    }
                )
            print(f"{path.name}: {len([s for s in segments if s['label'] == 'speaking'])} speaking segment(s), {duration:.3f}s")

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
