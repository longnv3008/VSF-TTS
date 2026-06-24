"""
train.py
========
Training loop finetune Silero VAD v6 trên dữ liệu TTS tiếng Việt.

Pipeline:
  1. Load model từ ONNX (via onnx2torch)
  2. Optionally freeze backbone layers
  3. Train với BCEWithLogitsLoss + pos_weight để xử lý class imbalance
  4. Early stopping dựa trên val AUC
  5. Checkpoint model tốt nhất

Usage:
  # Full finetune (toàn bộ model)
  python train.py

  # Chỉ train layers cuối (an toàn hơn, nhanh hơn)
  python train.py --freeze-layers 10

  # Với GPU
  python train.py --device cuda

  # Custom hyperparams
  python train.py --lr 5e-5 --epochs 30 --batch-size 512
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR

try:
    from sklearn.metrics import roc_auc_score, average_precision_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("[WARN] sklearn không có — sẽ dùng accuracy thay AUC")

from dataset import create_dataloaders
from convert_onnx_to_torch import load_torch_model

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512
CONTEXT_SAMPLES = 64
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ──────────────────────────────────────────────
# Training utilities
# ──────────────────────────────────────────────

def get_model_output(
    model: nn.Module,
    chunks: torch.Tensor,    # [B, 512]
    device: torch.device,
) -> torch.Tensor:
    """
    Chạy model trên batch chunks.
    Silero VAD cần state — khi finetune per-chunk, dùng zero state cho từng chunk.
    Đây là simplified training (không stateful) để giảm độ phức tạp.
    """
    B = chunks.shape[0]
    state = torch.zeros(2, B, 128, dtype=torch.float32, device=device)
    sr = torch.tensor(SAMPLE_RATE, dtype=torch.int64, device=device)
    context = torch.zeros(B, CONTEXT_SAMPLES, dtype=chunks.dtype, device=device)
    model_input = torch.cat([context, chunks.to(device)], dim=1)

    # Silero VAD ONNX returns probabilities after sigmoid.
    output, _ = model(model_input, state, sr)
    return output.squeeze(-1).clamp(1e-6, 1.0 - 1e-6)   # [B]


def weighted_bce_loss(
    probs: torch.Tensor,
    labels: torch.Tensor,
    pos_weight: float,
) -> torch.Tensor:
    """Binary cross entropy for probability outputs with speech weighting."""
    per_sample = nn.functional.binary_cross_entropy(probs, labels, reduction="none")
    weights = torch.where(
        labels >= 0.5,
        torch.full_like(labels, pos_weight),
        torch.ones_like(labels),
    )
    return (per_sample * weights).mean()


def train_one_epoch(
    model: nn.Module,
    loader,
    criterion: nn.Module,
    optimizer: optim.Optimizer,
    device: torch.device,
    scaler=None,            # GradScaler cho mixed precision (None nếu không dùng)
    max_batches: int = 0,
) -> dict:
    model.train()
    total_loss = 0.0
    all_preds, all_labels = [], []

    for batch_idx, (chunks, labels) in enumerate(loader):
        chunks = chunks.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        optimizer.zero_grad()

        if scaler is not None:
            with torch.cuda.amp.autocast():
                probs = get_model_output(model, chunks, device)
            loss = criterion(probs.float(), labels.float())
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            probs = get_model_output(model, chunks, device)
            loss = criterion(probs, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        total_loss += loss.item()
        all_preds.extend(probs.detach().cpu().numpy().tolist())
        all_labels.extend(labels.cpu().numpy().tolist())

        if (batch_idx + 1) % 50 == 0:
            print(f"    Batch {batch_idx+1}/{len(loader)} loss={loss.item():.4f}")
        if max_batches and (batch_idx + 1) >= max_batches:
            break

    avg_loss = total_loss / len(loader)
    metrics = {"loss": avg_loss}

    if HAS_SKLEARN and len(set(all_labels)) > 1:
        metrics["auc"] = roc_auc_score(all_labels, all_preds)
        metrics["ap"] = average_precision_score(all_labels, all_preds)

    return metrics


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader,
    criterion: nn.Module,
    device: torch.device,
    max_batches: int = 0,
) -> dict:
    model.eval()
    total_loss = 0.0
    all_preds, all_labels = [], []

    for batch_idx, (chunks, labels) in enumerate(loader):
        chunks = chunks.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        probs = get_model_output(model, chunks, device)
        loss = criterion(probs, labels)

        total_loss += loss.item()
        all_preds.extend(probs.cpu().numpy().tolist())
        all_labels.extend(labels.cpu().numpy().tolist())
        if max_batches and (batch_idx + 1) >= max_batches:
            break

    avg_loss = total_loss / len(loader)
    metrics = {"loss": avg_loss}

    if HAS_SKLEARN and len(set(all_labels)) > 1:
        metrics["auc"] = roc_auc_score(all_labels, all_preds)
        metrics["ap"] = average_precision_score(all_labels, all_preds)

    # Detection rate tại threshold=0.7 (production threshold)
    preds_07 = (np.array(all_preds) >= 0.7).astype(float)
    labels_arr = np.array(all_labels)
    speech_mask = labels_arr == 1.0
    if speech_mask.any():
        metrics["detection_rate_t07"] = float(preds_07[speech_mask].mean())
    silence_mask = labels_arr == 0.0
    if silence_mask.any():
        metrics["false_alarm_t07"] = float(preds_07[silence_mask].mean())

    return metrics


def freeze_layers(model: nn.Module, n_layers_to_freeze: int):
    """Freeze n layer đầu tiên (theo thứ tự named_parameters)."""
    all_params = list(model.named_parameters())
    print(f"[Freeze] Model có {len(all_params)} param groups. Freeze {n_layers_to_freeze} đầu tiên.")

    for i, (name, param) in enumerate(all_params):
        if i < n_layers_to_freeze:
            param.requires_grad = False
            # print(f"  [Frozen] {name}")
        else:
            param.requires_grad = True

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"[Freeze] Trainable params: {trainable:,} / {total:,} ({trainable/total*100:.1f}%)")


# ──────────────────────────────────────────────
# Checkpoint utilities
# ──────────────────────────────────────────────

def save_checkpoint(
    model: nn.Module,
    optimizer: optim.Optimizer,
    epoch: int,
    metrics: dict,
    path: Path,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "metrics": metrics,
    }, path)
    print(f"  [Checkpoint] Saved → {path} (epoch={epoch}, val_auc={metrics.get('auc', 'N/A')})")


def load_checkpoint(model: nn.Module, optimizer, path: Path) -> tuple[int, dict]:
    ckpt = torch.load(path, map_location="cpu")
    model.load_state_dict(ckpt["model_state_dict"])
    if optimizer is not None:
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return ckpt["epoch"], ckpt.get("metrics", {})


# ──────────────────────────────────────────────
# Main training
# ──────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Finetune Silero VAD trên TTS data")
    parser.add_argument("--onnx-path", type=Path,
                        default=PROJECT_ROOT / "VAD" / "models" / "vad" / "1" / "vad.onnx")
    parser.add_argument("--data-dir", type=Path, default=SCRIPT_DIR / "data")
    parser.add_argument("--checkpoint-dir", type=Path, default=SCRIPT_DIR / "checkpoints")
    parser.add_argument("--resume", type=Path, default=None,
                        help="Tiếp tục từ checkpoint")

    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--pos-weight", type=float, default=1.5,
                        help="Weight cho speech class trong BCE loss (>1 = penalize miss speech)")

    parser.add_argument("--freeze-layers", type=int, default=0,
                        help="Số param groups đầu freeze (0 = full finetune)")
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--amp", action="store_true",
                        help="Dùng mixed precision (chỉ với CUDA)")
    parser.add_argument("--early-stop-patience", type=int, default=10)
    parser.add_argument("--log-file", type=Path, default=SCRIPT_DIR / "training_log.json")
    parser.add_argument("--max-train-batches", type=int, default=0,
                        help="Limit train batches for smoke tests (0 = full epoch)")
    parser.add_argument("--max-val-batches", type=int, default=0,
                        help="Limit validation batches for smoke tests (0 = full validation)")
    return parser.parse_args()


def main():
    args = parse_args()
    device = torch.device(args.device)
    print(f"[Train] Device: {device}")

    # Check data
    train_npz = args.data_dir / "train.npz"
    val_npz = args.data_dir / "val.npz"
    if not train_npz.exists() or not val_npz.exists():
        print("[ERROR] Chưa có data. Chạy prepare_dataset.py trước.")
        print(f"  Missing: {train_npz if not train_npz.exists() else val_npz}")
        sys.exit(1)

    # Load model
    model = load_torch_model(args.onnx_path)
    model = model.to(device)

    if args.freeze_layers > 0:
        freeze_layers(model, args.freeze_layers)

    # DataLoaders
    train_loader, val_loader = create_dataloaders(
        train_npz, val_npz,
        batch_size=args.batch_size,
        num_workers=0,  # 0 vì model có thể không pickle được
        balance_classes=True,
    )

    # Loss, optimizer, scheduler
    def criterion(probs, labels):
        return weighted_bce_loss(probs, labels, args.pos_weight)

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = optim.AdamW(trainable_params, lr=args.lr, weight_decay=args.weight_decay)
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.01)

    # Mixed precision
    scaler = torch.cuda.amp.GradScaler() if (args.amp and device.type == "cuda") else None

    # Resume from checkpoint
    start_epoch = 0
    if args.resume and args.resume.exists():
        start_epoch, _ = load_checkpoint(model, optimizer, args.resume)
        start_epoch += 1
        print(f"[Resume] Tiếp tục từ epoch {start_epoch}")

    # Training loop
    best_auc = 0.0
    best_epoch = 0
    patience_counter = 0
    log_history = []

    print(f"\n{'='*60}")
    print(f"[Train] Bắt đầu training: {args.epochs} epochs, lr={args.lr}")
    print(f"[Train] Batch size: {args.batch_size} | Freeze layers: {args.freeze_layers}")
    print(f"[Train] pos_weight: {args.pos_weight} (speech được ưu tiên)")
    print(f"{'='*60}\n")

    for epoch in range(start_epoch, args.epochs):
        t0 = time.time()
        print(f"Epoch {epoch+1}/{args.epochs}")

        # Train
        train_metrics = train_one_epoch(
            model, train_loader, criterion, optimizer, device, scaler,
            max_batches=args.max_train_batches,
        )
        # Validate
        val_metrics = evaluate(
            model, val_loader, criterion, device,
            max_batches=args.max_val_batches,
        )

        scheduler.step()
        elapsed = time.time() - t0

        # Primary metric: AUC hoặc detection_rate nếu không có sklearn
        primary_metric = val_metrics.get("auc", val_metrics.get("detection_rate_t07", 0.0))

        # Log
        entry = {
            "epoch": epoch + 1,
            "train_loss": train_metrics["loss"],
            "val_loss": val_metrics["loss"],
            "val_auc": val_metrics.get("auc", None),
            "val_ap": val_metrics.get("ap", None),
            "val_detection_rate_t07": val_metrics.get("detection_rate_t07", None),
            "val_false_alarm_t07": val_metrics.get("false_alarm_t07", None),
            "lr": scheduler.get_last_lr()[0],
            "elapsed_sec": elapsed,
        }
        log_history.append(entry)

        train_auc = train_metrics.get("auc")
        val_auc = val_metrics.get("auc")
        train_auc_text = f"{train_auc:.4f}" if train_auc is not None else "N/A"
        val_auc_text = f"{val_auc:.4f}" if val_auc is not None else "N/A"
        print(f"  Train loss: {train_metrics['loss']:.4f} | Train AUC: {train_auc_text}")
        print(f"  Val   loss: {val_metrics['loss']:.4f} | Val   AUC: {val_auc_text}")
        if "detection_rate_t07" in val_metrics:
            print(f"  Detection@0.7: {val_metrics['detection_rate_t07']:.3f} | FalseAlarm@0.7: {val_metrics.get('false_alarm_t07', 0):.3f}")
        print(f"  LR: {scheduler.get_last_lr()[0]:.2e} | Time: {elapsed:.1f}s")

        # Save best model
        if primary_metric > best_auc:
            best_auc = primary_metric
            best_epoch = epoch + 1
            patience_counter = 0
            save_checkpoint(
                model, optimizer, epoch,
                val_metrics,
                args.checkpoint_dir / "best_model.pth"
            )
        else:
            patience_counter += 1
            print(f"  [EarlyStop] No improvement {patience_counter}/{args.early_stop_patience}")

        # Save periodic checkpoint
        if (epoch + 1) % 10 == 0:
            save_checkpoint(
                model, optimizer, epoch,
                val_metrics,
                args.checkpoint_dir / f"epoch_{epoch+1:04d}.pth"
            )

        # Save log
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.log_file, "w", encoding="utf-8") as f:
            json.dump(log_history, f, indent=2, ensure_ascii=False)

        # Early stopping
        if patience_counter >= args.early_stop_patience:
            print(f"\n[EarlyStop] Dừng tại epoch {epoch+1}. Best epoch: {best_epoch} (AUC={best_auc:.4f})")
            break

        print()

    print(f"\n{'='*60}")
    print("[Done] Training hoàn tất!")
    print(f"  Best epoch: {best_epoch} | Best metric: {best_auc:.4f}")
    print(f"  Best model: {args.checkpoint_dir / 'best_model.pth'}")
    print(f"  Log: {args.log_file}")
    print(f"\nBước tiếp theo: python export_onnx.py --checkpoint {args.checkpoint_dir / 'best_model.pth'}")


if __name__ == "__main__":
    main()
