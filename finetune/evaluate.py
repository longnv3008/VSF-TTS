"""
evaluate.py
===========
So sánh performance giữa model VAD cũ và model đã finetune.

Metrics:
  - AUC-ROC: phân biệt speech/silence
  - Detection Rate @ threshold=0.7 (production threshold)
  - False Alarm Rate @ threshold=0.7
  - Inference latency (ms/chunk)

Kết quả xuất ra CSV và in bảng so sánh rõ ràng.

Usage:
  # So sánh với val set
  python evaluate.py \
    --old-model ../VAD/models/vad/1/vad.onnx \
    --new-model checkpoints/vad_finetuned.onnx \
    --data-dir data

  # Chạy trên toàn bộ thư mục tmp/ (TTS files)
  python evaluate.py \
    --old-model ../VAD/models/vad/1/vad.onnx \
    --new-model checkpoints/vad_finetuned.onnx \
    --tts-dir ../tmp --threshold 0.7 --min-volume 0.6
"""

import argparse
import csv
import sys
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort

try:
    from sklearn.metrics import roc_auc_score, average_precision_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512
CONTEXT_SAMPLES = 64
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
MODEL_DIR = PROJECT_ROOT / "VAD" / "models" / "vad" / "1"
sys.path.insert(0, str(MODEL_DIR))

from utils import calculate_audio_volume, exp_smoothing  # noqa: E402
from prepare_dataset import label_tts_chunks_by_energy  # noqa: E402

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ──────────────────────────────────────────────
# ONNX inference helpers
# ──────────────────────────────────────────────

def load_session(model_path: Path) -> ort.InferenceSession:
    sess = ort.InferenceSession(
        str(model_path),
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
    )
    return sess


def infer_file_probs(
    session: ort.InferenceSession,
    audio: np.ndarray,
    chunk_size: int = CHUNK_SAMPLES,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Chạy inference trên toàn bộ file audio.
    Returns: (probs array [N], elapsed_ms)
    """
    n_chunks = (len(audio) + chunk_size - 1) // chunk_size
    state = np.zeros((2, 1, 128), dtype=np.float32)
    sr = np.array(SAMPLE_RATE, dtype=np.int64)
    probs = []
    volumes = []
    prev_volume = 0.0
    context = np.zeros((CONTEXT_SAMPLES,), dtype=np.float32)

    t0 = time.perf_counter()
    for i in range(n_chunks):
        chunk = audio[i * chunk_size: (i + 1) * chunk_size]
        if len(chunk) < chunk_size:
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
        chunk_normalized = chunk.astype(np.float32) / 32768.0
        model_input = np.concatenate([context, chunk_normalized], axis=0)
        feeds = {
            "input": model_input.reshape(1, -1),
            "state": state,
            "sr": sr,
        }
        out, state = session.run(["output", "stateN"], feeds)
        context = model_input[-CONTEXT_SAMPLES:]
        probs.append(float(out[0, 0]))
        volume = calculate_audio_volume(chunk.astype(np.float64), SAMPLE_RATE)
        prev_volume = exp_smoothing(volume, prev_volume, 0.2)
        volumes.append(prev_volume)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    return np.array(probs, dtype=np.float32), np.array(volumes, dtype=np.float32), elapsed_ms


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    """Đọc WAV file, trả về (sample_rate, int16 array)."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    return sr, np.frombuffer(raw, dtype=np.int16)


# ──────────────────────────────────────────────
# Evaluation on NPZ dataset
# ──────────────────────────────────────────────

def evaluate_on_dataset(
    session: ort.InferenceSession,
    npz_path: Path,
    threshold: float = 0.7,
    max_samples: int = 0,
) -> dict:
    """Evaluate model trên val.npz dataset."""
    data = np.load(str(npz_path), allow_pickle=True)
    chunks = data["chunks"].astype(np.float32)    # [N, 512]
    labels = data["labels"].astype(np.float32)    # [N]
    if max_samples and max_samples < len(labels):
        chunks = chunks[:max_samples]
        labels = labels[:max_samples]

    all_probs = []
    sr = np.array(SAMPLE_RATE, dtype=np.int64)
    context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    t0 = time.perf_counter()
    for i, chunk in enumerate(chunks):
        model_input = np.concatenate([context, chunk.reshape(1, -1)], axis=1)
        feeds = {
            "input": model_input,
            "state": np.zeros((2, 1, 128), dtype=np.float32),  # zero state per chunk
            "sr": sr,
        }
        out, _ = session.run(["output", "stateN"], feeds)
        all_probs.append(float(out[0, 0]))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    probs = np.array(all_probs)
    preds = (probs >= threshold).astype(float)
    n = len(labels)

    metrics = {
        "n_samples": n,
        "n_speech": int(labels.sum()),
        "n_silence": int((1 - labels).sum()),
        "avg_latency_us": elapsed_ms * 1000 / n,  # microseconds per chunk
    }

    if HAS_SKLEARN and len(set(labels)) > 1:
        metrics["auc_roc"] = float(roc_auc_score(labels, probs))
        metrics["avg_precision"] = float(average_precision_score(labels, probs))

    speech_mask = labels == 1.0
    silence_mask = labels == 0.0
    if speech_mask.any():
        metrics[f"detection_rate_t{int(threshold*10)}"] = float(preds[speech_mask].mean())
    if silence_mask.any():
        metrics[f"false_alarm_t{int(threshold*10)}"] = float(preds[silence_mask].mean())

    return metrics


# ──────────────────────────────────────────────
# Evaluation on TTS files (all speech)
# ──────────────────────────────────────────────

def evaluate_on_tts_dir(
    old_session: ort.InferenceSession,
    new_session: ort.InferenceSession,
    tts_dir: Path,
    threshold: float = 0.7,
    min_volume: float = 0.6,
    max_files: int = 0,
) -> list[dict]:
    """
    Chạy cả 2 model trên TTS files.
    TTS files = all speech → detection rate là metric chính.
    """
    rows = []
    wav_files = sorted(tts_dir.glob("*.wav"))
    if max_files:
        wav_files = wav_files[:max_files]
    print(f"[TTS Eval] {len(wav_files)} files trong {tts_dir}")

    for wav_path in wav_files:
        try:
            sr, audio = read_wav(wav_path)
            if sr != SAMPLE_RATE:
                print(f"  [SKIP] {wav_path.name}: sample rate {sr} != {SAMPLE_RATE}")
                continue

            # Inference cả 2 model
            old_probs, old_volumes, old_ms = infer_file_probs(old_session, audio)
            new_probs, new_volumes, new_ms = infer_file_probs(new_session, audio)

            n_chunks = len(old_probs)
            _, labels = label_tts_chunks_by_energy(audio.astype(np.float32) / 32768.0)
            labels = labels[:n_chunks].astype(bool)
            if len(labels) < n_chunks:
                labels = np.pad(labels, (0, n_chunks - len(labels)), constant_values=False)
            if not labels.any():
                labels = np.ones(n_chunks, dtype=bool)

            silence_labels = ~labels
            speech_chunks = int(labels.sum())
            silence_chunks = int(silence_labels.sum())
            old_detect_mask = (old_probs >= threshold) & (old_volumes >= min_volume)
            new_detect_mask = (new_probs >= threshold) & (new_volumes >= min_volume)
            old_detected = int((old_detect_mask & labels).sum())
            new_detected = int((new_detect_mask & labels).sum())
            old_false_alarm = int((old_detect_mask & silence_labels).sum())
            new_false_alarm = int((new_detect_mask & silence_labels).sum())

            row = {
                "file": wav_path.name,
                "duration_sec": round(len(audio) / SAMPLE_RATE, 2),
                "n_chunks": n_chunks,
                "speech_chunks": speech_chunks,
                "silence_chunks": silence_chunks,
                "old_detection_rate": round(old_detected / speech_chunks, 4),
                "new_detection_rate": round(new_detected / speech_chunks, 4),
                "old_tts_silence_false_alarm": round(old_false_alarm / silence_chunks, 4) if silence_chunks else 0.0,
                "new_tts_silence_false_alarm": round(new_false_alarm / silence_chunks, 4) if silence_chunks else 0.0,
                "old_avg_prob": round(float(old_probs.mean()), 4),
                "new_avg_prob": round(float(new_probs.mean()), 4),
                "old_latency_ms": round(old_ms, 2),
                "new_latency_ms": round(new_ms, 2),
                "improvement": round((new_detected - old_detected) / speech_chunks, 4),
            }
            rows.append(row)

            status = "✅" if new_detected >= old_detected else "⚠️"
            print(f"  {status} {wav_path.name}: "
                  f"Old={old_detected}/{speech_chunks}({row['old_detection_rate']:.2f}) "
                  f"New={new_detected}/{speech_chunks}({row['new_detection_rate']:.2f}) "
                  f"FA={old_false_alarm}/{silence_chunks}->{new_false_alarm}/{silence_chunks}")

        except Exception as e:
            print(f"  [ERROR] {wav_path.name}: {e}")

    return rows


# ──────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────

def print_comparison_table(old_metrics: dict, new_metrics: dict, threshold: float):
    """In bảng so sánh model cũ vs mới."""
    t_key = f"t{int(threshold*10)}"
    print(f"\n{'='*65}")
    print(f"{'Metric':<35} {'Old Model':>12} {'New Model':>12}  {'Change':>8}")
    print(f"{'='*65}")

    for key, label in [
        ("auc_roc", "AUC-ROC"),
        ("avg_precision", "Avg Precision (AP)"),
        (f"detection_rate_{t_key}", f"Detection Rate @{threshold}"),
        (f"false_alarm_{t_key}", f"False Alarm Rate @{threshold}"),
        ("avg_latency_us", "Latency (µs/chunk)"),
    ]:
        old_val = old_metrics.get(key)
        new_val = new_metrics.get(key)
        if old_val is None or new_val is None:
            continue

        change = new_val - old_val
        sign = "+" if change >= 0 else ""
        lower_is_better = key in {"false_alarm_" + t_key, "avg_latency_us"}
        is_better = change < 0 if lower_is_better else change > 0
        is_worse = change > 0 if lower_is_better else change < 0
        marker = " ✅" if is_better and abs(change) > 0.001 else (" ⚠️" if is_worse and abs(change) > 0.001 else "")

        print(f"  {label:<33} {old_val:>12.4f} {new_val:>12.4f}  {sign}{change:>+7.4f}{marker}")

    print(f"{'='*65}")


def parse_args():
    parser = argparse.ArgumentParser(description="So sánh Silero VAD gốc vs finetuned")
    parser.add_argument("--old-model", type=Path,
                        default=PROJECT_ROOT / "VAD" / "models" / "vad" / "1" / "vad.onnx")
    parser.add_argument("--new-model", type=Path,
                        default=SCRIPT_DIR / "checkpoints" / "vad_finetuned.onnx")
    parser.add_argument("--data-dir", type=Path, default=SCRIPT_DIR / "data",
                        help="Thư mục chứa val.npz")
    parser.add_argument("--tts-dir", type=Path, default=None,
                        help="Đánh giá thêm trên TTS files")
    parser.add_argument("--threshold", type=float, default=0.7,
                        help="Threshold production (default: 0.7)")
    parser.add_argument("--min-volume", type=float, default=0.6)
    parser.add_argument("--output-csv", type=Path, default=SCRIPT_DIR / "evaluation_report.csv")
    parser.add_argument("--max-samples", type=int, default=0,
                        help="Limit val.npz samples for smoke evaluation (0 = all)")
    parser.add_argument("--max-tts-files", type=int, default=0,
                        help="Limit TTS wav files for smoke evaluation (0 = all)")
    return parser.parse_args()


def main():
    args = parse_args()

    # Check files
    for p, name in [(args.old_model, "Old model"), (args.new_model, "New model")]:
        if not p.exists():
            print(f"[ERROR] {name} không tồn tại: {p}")
            sys.exit(1)

    # Load sessions
    print("[Eval] Loading models...")
    old_session = load_session(args.old_model)
    new_session = load_session(args.new_model)
    print(f"  Old: {args.old_model}")
    print(f"  New: {args.new_model}")

    # Evaluate on val dataset
    val_npz = args.data_dir / "val.npz"
    if val_npz.exists():
        print(f"\n[Eval] Đánh giá trên val dataset ({val_npz})...")
        old_metrics = evaluate_on_dataset(
            old_session, val_npz, threshold=args.threshold,
            max_samples=args.max_samples,
        )
        new_metrics = evaluate_on_dataset(
            new_session, val_npz, threshold=args.threshold,
            max_samples=args.max_samples,
        )

        print(f"\n  Old model: n={old_metrics['n_samples']}, "
              f"speech={old_metrics['n_speech']}, silence={old_metrics['n_silence']}")
        print_comparison_table(old_metrics, new_metrics, threshold=args.threshold)
    else:
        print(f"[WARN] val.npz không tồn tại ({val_npz}). Bỏ qua dataset evaluation.")
        old_metrics, new_metrics = {}, {}

    # Evaluate on TTS files
    if args.tts_dir and args.tts_dir.exists():
        print(f"\n[Eval] Đánh giá trên TTS files ({args.tts_dir})...")
        tts_rows = evaluate_on_tts_dir(
            old_session, new_session, args.tts_dir,
            threshold=args.threshold, min_volume=args.min_volume,
            max_files=args.max_tts_files,
        )

        if tts_rows:
            # Summary
            old_dr = np.mean([r["old_detection_rate"] for r in tts_rows])
            new_dr = np.mean([r["new_detection_rate"] for r in tts_rows])
            old_fa_tts = np.mean([r["old_tts_silence_false_alarm"] for r in tts_rows])
            new_fa_tts = np.mean([r["new_tts_silence_false_alarm"] for r in tts_rows])
            print(f"\n[TTS Summary] Avg Detection Rate: Old={old_dr:.4f} → New={new_dr:.4f} "
                  f"({'↑' if new_dr >= old_dr else '↓'}{abs(new_dr-old_dr):.4f})")

            print(f"[TTS Summary] Avg Silence False Alarm: Old={old_fa_tts:.4f} -> New={new_fa_tts:.4f}")

            # Save CSV
            args.output_csv.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=tts_rows[0].keys())
                writer.writeheader()
                writer.writerows(tts_rows)
            print(f"[Saved] TTS evaluation report → {args.output_csv}")

    print("\n[Done] Evaluation hoàn tất.")
    t_key = f"t{int(args.threshold*10)}"
    old_auc = old_metrics.get("auc_roc", 0)
    new_auc = new_metrics.get("auc_roc", 0)
    old_dr = old_metrics.get(f"detection_rate_{t_key}")
    new_dr = new_metrics.get(f"detection_rate_{t_key}")
    old_fa = old_metrics.get(f"false_alarm_{t_key}")
    new_fa = new_metrics.get(f"false_alarm_{t_key}")
    deploy_ok = (
        new_auc >= old_auc
        and (old_dr is None or new_dr >= old_dr)
        and (old_fa is None or new_fa <= old_fa)
    )
    if deploy_ok:
        print("[Result] ✅ Model mới đạt gate deploy trên các metric đã kiểm tra.")
        print(f"         Có thể deploy: cp {args.new_model} {args.old_model}")
    else:
        print("[Result] ⚠️ Model mới chưa đạt gate deploy.")
        print("         Cần train/evaluate thêm trước khi thay model production.")


if __name__ == "__main__":
    main()
