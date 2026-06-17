"""
prepare_dataset.py
==================
Tạo dataset frame-level (512 samples @ 16kHz = 32ms) để finetune Silero VAD.

Nguồn data:
  - TTS audio (e.g. tmp/*.wav):          label=1 (speech, toàn bộ file)
  - YouTube audio + vad_chunks.jsonl:    speech regions → label=1
  - YouTube silence (gap giữa chunks):   label=0

Output: data/train.npz và data/val.npz
  {
    "chunks":  float32 [N, 512]   — normalized [-1, 1]
    "labels":  float32 [N]        — 0.0 hoặc 1.0
    "sources": str [N]            — tên file gốc (debug)
  }

Usage:
  python prepare_dataset.py \
    --tts-dir ../tmp \
    --youtube-dir ../../data/processed/audio \
    --exp-dir ../../data/experiments/vad_asr_compare/youtube_all_cuda_debug_limit1 \
    --out-dir data \
    --val-ratio 0.15 \
    --seed 42
"""

import argparse
import sys

# Fix Unicode encoding on Windows (tránh lỗi với tiếng Việt khi in ra console)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import os
import wave
import random
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512          # 32ms @ 16kHz — Silero VAD chunk size
MIN_SILENCE_SAMPLES = 512    # Tối thiểu 32ms silence mới lấy
PAD_SILENCE_SEC = 0.1        # Pad thêm ở đầu/cuối speech region để tạo silence buffer
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
VSF_ROOT = PROJECT_ROOT.parent


# ──────────────────────────────────────────────
# Audio utilities
# ──────────────────────────────────────────────

def read_wav_mono16k(path: Path) -> np.ndarray:
    """Đọc WAV file, trả về float32 numpy array đã normalize [-1, 1].
    Yêu cầu: mono, 16-bit PCM, 16kHz.
    """
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth != 2:
        raise ValueError(f"{path}: chỉ hỗ trợ 16-bit PCM, got {sampwidth * 8}-bit")
    if framerate != SAMPLE_RATE:
        raise ValueError(f"{path}: cần sample rate {SAMPLE_RATE}Hz, got {framerate}Hz")

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

    if n_channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)  # stereo → mono

    return audio / 32768.0   # normalize to [-1, 1]


def split_into_chunks(audio: np.ndarray, chunk_size: int = CHUNK_SAMPLES) -> np.ndarray:
    """Chia audio thành các chunks cố định. Chunk cuối được pad bằng 0."""
    n_full = len(audio) // chunk_size
    remainder = len(audio) % chunk_size

    chunks = audio[: n_full * chunk_size].reshape(n_full, chunk_size)

    if remainder > 0:
        last = np.zeros(chunk_size, dtype=np.float32)
        last[:remainder] = audio[n_full * chunk_size:]
        chunks = np.vstack([chunks, last.reshape(1, chunk_size)])

    return chunks


# ──────────────────────────────────────────────
# Label generation
# ──────────────────────────────────────────────

def label_chunks_full_speech(audio: np.ndarray, chunk_size: int = CHUNK_SAMPLES) -> tuple[np.ndarray, np.ndarray]:
    """TTS file: toàn bộ là speech (label=1)."""
    chunks = split_into_chunks(audio, chunk_size)
    labels = np.ones(len(chunks), dtype=np.float32)
    return chunks, labels


def _fill_short_label_gaps(labels: np.ndarray, max_gap_chunks: int) -> np.ndarray:
    """Fill short non-speech gaps inside a speech region."""
    if max_gap_chunks <= 0 or not labels.any():
        return labels

    filled = labels.copy()
    speech_idx = np.flatnonzero(labels)
    start = speech_idx[0]
    end = speech_idx[-1]
    i = start
    while i <= end:
        if filled[i]:
            i += 1
            continue
        gap_start = i
        while i <= end and not filled[i]:
            i += 1
        if i - gap_start <= max_gap_chunks:
            filled[gap_start:i] = True
    return filled


def _remove_short_label_runs(labels: np.ndarray, min_run_chunks: int) -> np.ndarray:
    """Remove tiny isolated speech runs caused by clicks or noise."""
    if min_run_chunks <= 1 or not labels.any():
        return labels

    cleaned = labels.copy()
    i = 0
    n = len(cleaned)
    while i < n:
        if not cleaned[i]:
            i += 1
            continue
        run_start = i
        while i < n and cleaned[i]:
            i += 1
        if i - run_start < min_run_chunks:
            cleaned[run_start:i] = False
    return cleaned


def _pad_label_runs(labels: np.ndarray, pad_chunks: int) -> np.ndarray:
    """Pad detected speech regions so boundary chunks are not too tight."""
    if pad_chunks <= 0 or not labels.any():
        return labels

    padded = labels.copy()
    speech_idx = np.flatnonzero(labels)
    start = max(0, speech_idx[0] - pad_chunks)
    end = min(len(labels), speech_idx[-1] + pad_chunks + 1)
    padded[start:end] = True
    return padded


def label_tts_chunks_by_energy(
    audio: np.ndarray,
    chunk_size: int = CHUNK_SAMPLES,
    db_below_peak: float = 35.0,
    min_rms: float = 1e-4,
    pad_ms: float = 64.0,
    min_speech_ms: float = 64.0,
    max_gap_ms: float = 96.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Label TTS chunks with a relative RMS gate.

    TTS files usually contain leading/trailing silence. Marking the whole file
    as speech creates noisy labels and makes finetuning less reliable.
    """
    chunks = split_into_chunks(audio, chunk_size)
    if len(chunks) == 0:
        return chunks, np.empty((0,), dtype=np.float32)

    rms = np.sqrt(np.mean(chunks * chunks, axis=1))
    peak = float(rms.max(initial=0.0))
    if peak <= 0.0:
        return chunks, np.zeros(len(chunks), dtype=np.float32)

    threshold = max(min_rms, peak * (10.0 ** (-db_below_peak / 20.0)))
    labels = rms >= threshold

    chunk_ms = chunk_size * 1000.0 / SAMPLE_RATE
    labels = _fill_short_label_gaps(labels, round(max_gap_ms / chunk_ms))
    labels = _remove_short_label_runs(labels, round(min_speech_ms / chunk_ms))
    labels = _pad_label_runs(labels, round(pad_ms / chunk_ms))

    return chunks, labels.astype(np.float32)


def label_chunks_from_timestamps(
    audio: np.ndarray,
    speech_regions: list[tuple[float, float]],   # [(start_sec, end_sec), ...]
    chunk_size: int = CHUNK_SAMPLES,
    iou_threshold: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Label tung chunk dua tren timestamp overlap voi speech_regions.
    Chunk co IoU >= iou_threshold voi bat ky speech region nao → label=1.
    Dung vectorized numpy de tang toc.
    """
    chunks = split_into_chunks(audio, chunk_size)
    n_chunks = len(chunks)
    labels = np.zeros(n_chunks, dtype=np.float32)

    if not speech_regions:
        return chunks, labels

    chunk_duration = chunk_size / SAMPLE_RATE
    chunk_starts = np.arange(n_chunks, dtype=np.float64) * chunk_duration
    chunk_ends = chunk_starts + chunk_duration

    for speech_start, speech_end in speech_regions:
        overlap_starts = np.maximum(chunk_starts, speech_start)
        overlap_ends = np.minimum(chunk_ends, speech_end)
        overlaps = np.maximum(0.0, overlap_ends - overlap_starts)
        ratios = overlaps / chunk_duration
        labels = np.where(ratios >= iou_threshold, 1.0, labels)

    return chunks, labels.astype(np.float32)


def extract_regions_as_chunks(
    audio: np.ndarray,
    regions: list[tuple[float, float]],
    label: float,
    chunk_size: int = CHUNK_SAMPLES,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract audio only inside regions and assign one label to every chunk."""
    region_chunks = []
    for start_sec, end_sec in regions:
        start = max(0, int(round(start_sec * SAMPLE_RATE)))
        end = min(len(audio), int(round(end_sec * SAMPLE_RATE)))
        if end - start < MIN_SILENCE_SAMPLES:
            continue
        region_chunks.append(split_into_chunks(audio[start:end], chunk_size))

    if not region_chunks:
        return np.empty((0, chunk_size), dtype=np.float32), np.empty((0,), dtype=np.float32)

    chunks = np.vstack(region_chunks).astype(np.float32)
    labels = np.full((len(chunks),), label, dtype=np.float32)
    return chunks, labels


def extract_silence_regions(
    audio_duration: float,
    speech_regions: list[tuple[float, float]],
    pad_sec: float = PAD_SILENCE_SEC,
) -> list[tuple[float, float]]:
    """Tính các vùng silence = phần bù của speech_regions (sau khi pad)."""
    silence = []
    cursor = 0.0

    for start, end in sorted(speech_regions):
        silence_end = max(cursor, start - pad_sec)
        if silence_end - cursor >= MIN_SILENCE_SAMPLES / SAMPLE_RATE:
            silence.append((cursor, silence_end))
        cursor = max(cursor, end + pad_sec)

    if cursor < audio_duration - MIN_SILENCE_SAMPLES / SAMPLE_RATE:
        silence.append((cursor, audio_duration))

    return silence


# ──────────────────────────────────────────────
# Data source processors
# ──────────────────────────────────────────────

def process_tts_dir(
    tts_dir: Path,
    label_mode: str = "energy",
    energy_db_below_peak: float = 35.0,
    energy_min_rms: float = 1e-4,
    energy_pad_ms: float = 64.0,
) -> tuple[list[np.ndarray], list[np.ndarray], list[str]]:
    """Process TTS directory with either full-speech or energy labels."""
    all_chunks, all_labels, all_sources = [], [], []
    wav_files = sorted(tts_dir.glob("*.wav"))
    print(f"[TTS] Tìm thấy {len(wav_files)} file trong {tts_dir}")

    for wav_path in wav_files:
        try:
            audio = read_wav_mono16k(wav_path)
            if label_mode == "full-speech":
                chunks, labels = label_chunks_full_speech(audio)
            else:
                chunks, labels = label_tts_chunks_by_energy(
                    audio,
                    db_below_peak=energy_db_below_peak,
                    min_rms=energy_min_rms,
                    pad_ms=energy_pad_ms,
                )
            all_chunks.append(chunks)
            all_labels.append(labels)
            all_sources.extend([wav_path.name] * len(chunks))
            n_speech = int(labels.sum())
            n_silence = len(labels) - n_speech
            print(
                f"  {wav_path.name}: {len(audio)/SAMPLE_RATE:.2f}s -> "
                f"{n_speech} speech, {n_silence} silence chunks ({label_mode})"
            )
        except Exception as e:
            print(f"  [SKIP] {wav_path.name}: {e}")

    return all_chunks, all_labels, all_sources


def process_youtube_dir(
    audio_dir: Path,
    exp_dir: Path,
    max_files: int = 0,   # 0 = không giới hạn
) -> tuple[list[np.ndarray], list[np.ndarray], list[str]]:
    """
    Xử lý YouTube audio với nhãn từ vad_chunks.jsonl.
    - Regions trong chunks → speech (label=1)
    - Gaps giữa chunks → silence (label=0)
    """
    all_chunks, all_labels, all_sources = [], [], []

    yt_dirs = [d for d in exp_dir.iterdir() if d.is_dir() and d.name.startswith("yt_")]
    yt_dirs = sorted(yt_dirs)
    if max_files > 0:
        yt_dirs = yt_dirs[:max_files]
    print(f"[YouTube] Xu ly {len(yt_dirs)} video trong {exp_dir}")

    for yt_dir in yt_dirs:
        yt_id = yt_dir.name  # e.g. "yt_M5xe04_4YrU"
        wav_path = audio_dir / f"{yt_id}.wav"
        chunks_jsonl = yt_dir / "vad_chunks.jsonl"

        if not wav_path.exists():
            print(f"  [SKIP] {yt_id}: audio file khong ton tai tai {wav_path}")
            continue
        if not chunks_jsonl.exists():
            print(f"  [SKIP] {yt_id}: vad_chunks.jsonl khong ton tai")
            continue

        try:
            audio = read_wav_mono16k(wav_path)
            duration = len(audio) / SAMPLE_RATE

            # Load speech regions tu vad_chunks.jsonl
            speech_regions = []
            with open(chunks_jsonl, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    speech_regions.append((float(obj["start_sec"]), float(obj["end_sec"])))

            n_speech_chunks = 0
            n_silence_chunks = 0

            # Lay speech chunks
            speech_chunks, speech_labels = label_chunks_from_timestamps(audio, speech_regions)
            speech_mask = speech_labels == 1.0
            if speech_mask.any():
                all_chunks.append(speech_chunks[speech_mask])
                all_labels.append(speech_labels[speech_mask])
                all_sources.extend([f"{yt_id}_speech"] * int(speech_mask.sum()))
                n_speech_chunks = int(speech_mask.sum())

            # Lay silence regions (phan bu)
            silence_regions = extract_silence_regions(duration, speech_regions)
            if silence_regions:
                silence_chunks, silence_labels = extract_regions_as_chunks(
                    audio, silence_regions, label=0.0
                )
                if len(silence_chunks) > 0:
                    all_chunks.append(silence_chunks)
                    all_labels.append(silence_labels)
                    all_sources.extend([f"{yt_id}_silence"] * len(silence_labels))
                    n_silence_chunks = len(silence_labels)

            print(f"  {yt_id}: {duration:.0f}s -> {n_speech_chunks} speech, {n_silence_chunks} silence chunks")

        except Exception as e:
            import traceback
            print(f"  [ERROR] {yt_id}: {e}")
            traceback.print_exc()


    return all_chunks, all_labels, all_sources


# ──────────────────────────────────────────────
# Dataset builder
# ──────────────────────────────────────────────


def build_and_save(
    all_chunks: list[np.ndarray],
    all_labels: list[np.ndarray],
    all_sources: list[str],
    out_dir: Path,
    val_ratio: float = 0.15,
    seed: int = 42,
):
    """Gộp, shuffle, split train/val, lưu .npz."""
    if not all_chunks:
        print("[ERROR] Không có data nào được tạo ra!")
        sys.exit(1)

    chunks = np.vstack(all_chunks)
    labels = np.concatenate(all_labels)
    sources = np.array(all_sources)

    n_total = len(chunks)
    n_speech = int(labels.sum())
    n_silence = n_total - n_speech
    print(f"\n[Summary] Tổng: {n_total} chunks | Speech: {n_speech} ({n_speech/n_total*100:.1f}%) | Silence: {n_silence} ({n_silence/n_total*100:.1f}%)")

    # Shuffle
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n_total)
    chunks = chunks[idx]
    labels = labels[idx]
    sources = sources[idx]

    # Split
    n_val = int(n_total * val_ratio)
    val_chunks, val_labels, val_sources = chunks[:n_val], labels[:n_val], sources[:n_val]
    train_chunks, train_labels, train_sources = chunks[n_val:], labels[n_val:], sources[n_val:]

    # Save
    out_dir.mkdir(parents=True, exist_ok=True)
    train_path = out_dir / "train.npz"
    val_path = out_dir / "val.npz"

    tmp_train_path = out_dir / "train.tmp.npz"
    tmp_val_path = out_dir / "val.tmp.npz"
    np.savez_compressed(tmp_train_path, chunks=train_chunks, labels=train_labels, sources=train_sources)
    np.savez_compressed(tmp_val_path, chunks=val_chunks, labels=val_labels, sources=val_sources)
    os.replace(tmp_train_path, train_path)
    os.replace(tmp_val_path, val_path)

    print(f"[Saved] Train: {len(train_chunks)} chunks → {train_path}")
    print(f"[Saved] Val:   {len(val_chunks)} chunks → {val_path}")
    print(f"\nTrain label dist: speech={train_labels.sum():.0f} silence={(1-train_labels).sum():.0f}")
    print(f"Val   label dist: speech={val_labels.sum():.0f} silence={(1-val_labels).sum():.0f}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Chuan bi dataset frame-level cho finetune Silero VAD")
    parser.add_argument("--tts-dir", type=Path, default=PROJECT_ROOT / "tmp",
                        help="Thu muc chua file TTS WAV")
    parser.add_argument("--tts-label-mode", choices=["energy", "full-speech"], default="energy",
                        help="Cach label TTS chunks: energy trim silence dau/cuoi; full-speech giu hanh vi cu")
    parser.add_argument("--tts-energy-db-below-peak", type=float, default=35.0,
                        help="Energy threshold cho TTS = peak RMS tru di so dB nay")
    parser.add_argument("--tts-energy-min-rms", type=float, default=1e-4,
                        help="San RMS toi thieu cho TTS energy labels")
    parser.add_argument("--tts-energy-pad-ms", type=float, default=64.0,
                        help="Pad speech regions khi tao TTS energy labels")
    parser.add_argument("--youtube-dir", type=Path, default=VSF_ROOT / "data" / "processed" / "audio",
                        help="Thu muc chua YouTube WAV files")
    parser.add_argument("--exp-dir", type=Path,
                        default=VSF_ROOT / "data" / "experiments" / "vad_asr_compare" / "youtube_all_cuda_debug_limit1",
                        help="Thu muc experiment chua cac yt_* subfolders voi vad_chunks.jsonl")
    parser.add_argument("--out-dir", type=Path, default=SCRIPT_DIR / "data",
                        help="Thu muc output de luu train.npz va val.npz")
    parser.add_argument("--val-ratio", type=float, default=0.15,
                        help="Ti le validation set (default: 0.15)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-tts", action="store_true", help="Bo qua TTS data")
    parser.add_argument("--no-youtube", action="store_true", help="Bo qua YouTube data")
    parser.add_argument("--max-youtube", type=int, default=0,
                        help="Gioi han so file YouTube xu ly (0 = tat ca, dung de test nhanh)")
    return parser.parse_args()



def main():
    args = parse_args()

    all_chunks, all_labels, all_sources = [], [], []

    # 1. TTS data
    if not args.no_tts:
        if args.tts_dir.exists():
            c, l, s = process_tts_dir(
                args.tts_dir,
                label_mode=args.tts_label_mode,
                energy_db_below_peak=args.tts_energy_db_below_peak,
                energy_min_rms=args.tts_energy_min_rms,
                energy_pad_ms=args.tts_energy_pad_ms,
            )
            all_chunks.extend(c)
            all_labels.extend(l)
            all_sources.extend(s)
        else:
            print(f"[WARN] TTS dir không tồn tại: {args.tts_dir}")

    # 2. YouTube data (mixed speech + silence)
    if not args.no_youtube:
        if args.youtube_dir.exists() and args.exp_dir.exists():
            c, l, s = process_youtube_dir(
                args.youtube_dir, args.exp_dir,
                max_files=args.max_youtube,
            )
            all_chunks.extend(c)
            all_labels.extend(l)
            all_sources.extend(s)
        else:
            print(f"[WARN] YouTube dir hoac exp-dir khong ton tai")
            print(f"  youtube-dir: {args.youtube_dir} (exists={args.youtube_dir.exists()})")
            print(f"  exp-dir: {args.exp_dir} (exists={args.exp_dir.exists()})")


    # 3. Build và save dataset
    build_and_save(all_chunks, all_labels, all_sources, args.out_dir, args.val_ratio, args.seed)


if __name__ == "__main__":
    main()
