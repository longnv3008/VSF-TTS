"""
export_onnx.py
==============
Export model đã finetune sang ONNX với interface giống hệt Silero V6 gốc.

Interface ONNX phải khớp với vad.py trong Triton server:
  Inputs:
    - input:  [batch, seq_len]  float32  (audio normalized)
    - state:  [2, batch, 128]   float32  (LSTM hidden state)
    - sr:     []                int64    (sample rate)
  Outputs:
    - output: [batch, 1]        float32  (speech probability)
    - stateN: [2, batch, 128]   float32  (updated state)

Usage:
  python export_onnx.py \
    --onnx-path ../VAD/models/vad/1/vad.onnx \
    --checkpoint checkpoints/best_model.pth \
    --output checkpoints/vad_finetuned.onnx

  # Verify sau khi export
  python export_onnx.py ... --verify
"""

import argparse
import sys
import numpy as np
from pathlib import Path

import torch
import onnxruntime as ort

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


def load_finetuned_model(
    onnx_path: Path,
    checkpoint_path: Path,
    device: torch.device = torch.device("cpu"),
) -> torch.nn.Module:
    """Load base model structure + finetuned weights."""
    model = load_torch_model(onnx_path)

    print(f"[Load] Loading checkpoint từ {checkpoint_path}")
    ckpt = torch.load(checkpoint_path, map_location="cpu")

    if "model_state_dict" in ckpt:
        model.load_state_dict(ckpt["model_state_dict"])
        metrics = ckpt.get("metrics", {})
        print(f"  Epoch: {ckpt.get('epoch', '?')+1} | Val AUC: {metrics.get('auc', 'N/A')} | "
              f"Detection@0.7: {metrics.get('detection_rate_t07', 'N/A')}")
    else:
        # Trường hợp save raw state dict
        model.load_state_dict(ckpt)

    model = model.to(device)
    model.eval()
    return model


def export_to_onnx(
    model: torch.nn.Module,
    output_path: Path,
    opset_version: int = 16,
    device: torch.device = torch.device("cpu"),
):
    """Export PyTorch model sang ONNX với dynamic axes."""
    print(f"\n[Export] Xuất ONNX sang {output_path}...")

    # Dummy inputs — batch=1, chunk=512 samples
    dummy_input = torch.randn(1, CHUNK_SAMPLES + CONTEXT_SAMPLES, dtype=torch.float32, device=device)
    dummy_state = torch.zeros(2, 1, 128, dtype=torch.float32, device=device)
    export_model = model.model if hasattr(model, "model") else model

    output_path.parent.mkdir(parents=True, exist_ok=True)

    torch.onnx.export(
        export_model,
        (dummy_input, dummy_state),
        str(output_path),
        opset_version=opset_version,
        input_names=["input", "state"],
        output_names=["output", "stateN"],
        dynamic_axes={
            "input": {0: "batch_size", 1: "seq_len"},
            "state": {1: "batch_size"},
            "stateN": {1: "batch_size"},
            "output": {0: "batch_size"},
        },
        do_constant_folding=True,
        export_params=True,
        verbose=False,
    )

    # Verify ONNX file hợp lệ
    import onnx
    from onnx import TensorProto, helper
    onnx_model = onnx.load(str(output_path))
    if not any(inp.name == "sr" for inp in onnx_model.graph.input):
        onnx_model.graph.input.extend([
            helper.make_tensor_value_info("sr", TensorProto.INT64, [])
        ])
        onnx.save(onnx_model, str(output_path))
        onnx_model = onnx.load(str(output_path))
    onnx.checker.check_model(onnx_model)

    file_size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"[Export] ✅ Xuất thành công: {output_path} ({file_size_mb:.2f} MB)")

    # In input/output specs
    session = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
    print("[Export] ONNX Inputs:")
    for inp in session.get_inputs():
        print(f"  {inp.name}: {inp.shape} ({inp.type})")
    print("[Export] ONNX Outputs:")
    for out in session.get_outputs():
        print(f"  {out.name}: {out.shape} ({out.type})")


def verify_finetuned_vs_original(
    original_onnx: Path,
    finetuned_onnx: Path,
    n_chunks: int = 10,
):
    """
    So sánh output của model gốc vs model đã finetune trên random audio.
    Không cần khớp chính xác — chỉ kiểm tra range và behavior hợp lý.
    """
    print("\n[Verify] So sánh Original vs Finetuned model...")

    orig_session = ort.InferenceSession(str(original_onnx), providers=["CPUExecutionProvider"])
    new_session = ort.InferenceSession(str(finetuned_onnx), providers=["CPUExecutionProvider"])

    # Test với speech-like audio (high amplitude)
    print("\n  Test với speech-like audio (amp=0.3):")
    for i in range(3):
        audio = np.random.randn(1, CHUNK_SAMPLES + CONTEXT_SAMPLES).astype(np.float32) * 0.3
        state = np.zeros((2, 1, 128), dtype=np.float32)
        sr = np.array(SAMPLE_RATE, dtype=np.int64)

        feeds = {"input": audio, "state": state, "sr": sr}
        orig_out, _ = orig_session.run(["output", "stateN"], feeds)
        new_out, _ = new_session.run(["output", "stateN"], feeds)
        print(f"    Chunk {i+1}: Original={orig_out[0,0]:.4f}  Finetuned={new_out[0,0]:.4f}")

    # Test với silence (very low amplitude)
    print("\n  Test với silence (amp=0.001):")
    for i in range(3):
        audio = np.random.randn(1, CHUNK_SAMPLES + CONTEXT_SAMPLES).astype(np.float32) * 0.001
        state = np.zeros((2, 1, 128), dtype=np.float32)
        sr = np.array(SAMPLE_RATE, dtype=np.int64)

        feeds = {"input": audio, "state": state, "sr": sr}
        orig_out, _ = orig_session.run(["output", "stateN"], feeds)
        new_out, _ = new_session.run(["output", "stateN"], feeds)
        print(f"    Chunk {i+1}: Original={orig_out[0,0]:.4f}  Finetuned={new_out[0,0]:.4f}")

    print("\n[Verify] Kết quả hợp lý nếu:")
    print("  - Speech-like audio có prob cao hơn silence")
    print("  - Finetuned model không có output NaN/Inf")
    print("  - Range output trong [0, 1]")


def parse_args():
    parser = argparse.ArgumentParser(description="Export finetuned Silero VAD sang ONNX")
    parser.add_argument("--onnx-path", type=Path,
                        default=PROJECT_ROOT / "VAD" / "models" / "vad" / "1" / "vad.onnx",
                        help="ONNX model gốc (dùng để load architecture)")
    parser.add_argument("--checkpoint", type=Path,
                        default=SCRIPT_DIR / "checkpoints" / "best_model.pth",
                        help="Checkpoint file từ train.py")
    parser.add_argument("--output", type=Path,
                        default=SCRIPT_DIR / "checkpoints" / "vad_finetuned.onnx",
                        help="Output ONNX file")
    parser.add_argument("--opset", type=int, default=16)
    parser.add_argument("--verify", action="store_true",
                        help="So sánh output với model gốc sau khi export")
    parser.add_argument("--device", type=str, default="cpu")
    return parser.parse_args()


def main():
    args = parse_args()
    device = torch.device(args.device)

    if not args.onnx_path.exists():
        print(f"[ERROR] ONNX gốc không tồn tại: {args.onnx_path}")
        sys.exit(1)
    if not args.checkpoint.exists():
        print(f"[ERROR] Checkpoint không tồn tại: {args.checkpoint}")
        print("Chạy train.py trước để tạo checkpoint.")
        sys.exit(1)

    # Load finetuned model
    model = load_finetuned_model(args.onnx_path, args.checkpoint, device)

    # Export sang ONNX
    export_to_onnx(model, args.output, opset_version=args.opset, device=device)

    # Verify
    if args.verify:
        verify_finetuned_vs_original(args.onnx_path, args.output)

    print(f"\n{'='*60}")
    print("[Done] Export hoàn tất!")
    print("\nĐể deploy lên Triton server:")
    print(f"  cp {args.output} {args.onnx_path}")
    print("  docker restart vad-server")
    print("\nHoặc chạy evaluate.py để kiểm tra trước:")
    print(f"  python evaluate.py --new-model {args.output} --threshold 0.7")


if __name__ == "__main__":
    main()
