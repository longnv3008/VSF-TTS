"""
convert_onnx_to_torch.py
========================
Convert vad.onnx (Silero V6) sang PyTorch model có thể finetune.

Sử dụng onnx2torch library để chuyển đổi.
Sau đó verify output match giữa ONNX và PyTorch.

Usage:
  # Chỉ convert
  python convert_onnx_to_torch.py --onnx-path ../VAD/models/vad/1/vad.onnx

  # Convert + verify
  python convert_onnx_to_torch.py --onnx-path ../VAD/models/vad/1/vad.onnx --verify

  # Convert + lưu state dict
  python convert_onnx_to_torch.py --onnx-path ../VAD/models/vad/1/vad.onnx --save checkpoints/base_weights.pth
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import onnxruntime as ort

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512     # 32ms @ 16kHz
CONTEXT_SAMPLES = 64    # 4ms @ 16kHz, matching Triton VAD context
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class FixedSRModelWrapper(torch.nn.Module):
    """Wrap a fixed-16kHz graph so callers keep the original Silero signature."""

    def __init__(self, model: torch.nn.Module):
        super().__init__()
        self.model = model

    def forward(
        self,
        audio_chunk: torch.Tensor,
        state: torch.Tensor,
        sr: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        output, new_state = self.model(audio_chunk, state)
        # Keep sr in the exported graph while preserving 16k-only behavior.
        sr_anchor = sr.to(dtype=output.dtype) * 0.0
        return output + sr_anchor, new_state + sr_anchor


def extract_fixed_sr_model(onnx_model, sample_rate: int = SAMPLE_RATE):
    """Extract the 16kHz branch from Silero's top-level If graph."""
    import copy
    import onnx
    from onnx import helper

    if_nodes = [node for node in onnx_model.graph.node if node.op_type == "If"]
    if not if_nodes:
        return onnx_model
    if len(if_nodes) != 1:
        raise RuntimeError(f"Expected one If node, found {len(if_nodes)}")
    if sample_rate != SAMPLE_RATE:
        raise ValueError("This project only supports fixed 16kHz conversion")

    if_node = if_nodes[0]
    branch_graph = None
    for attr in if_node.attribute:
        if attr.name == "then_branch":
            branch_graph = attr.g
            break
    if branch_graph is None:
        raise RuntimeError("Could not find the 16kHz then_branch in the ONNX graph")

    inputs = [
        copy.deepcopy(value_info)
        for value_info in onnx_model.graph.input
        if value_info.name in {"input", "state"}
    ]
    if len(inputs) != 2:
        raise RuntimeError("Expected ONNX inputs named input and state")

    nodes = []
    initializers = [copy.deepcopy(init) for init in branch_graph.initializer]
    for node in branch_graph.node:
        if node.op_type == "Constant" and len(node.output) == 1:
            tensor_attr = next((attr for attr in node.attribute if attr.name == "value"), None)
            if tensor_attr is not None and tensor_attr.t.name is not None:
                tensor = copy.deepcopy(tensor_attr.t)
                tensor.name = node.output[0]
                initializers.append(tensor)
                continue
        nodes.append(copy.deepcopy(node))
    branch_outputs = [output.name for output in branch_graph.output]
    nodes.extend(
        [
            helper.make_node("Identity", [branch_outputs[0]], ["output"], name="fixed_sr_output"),
            helper.make_node("Identity", [branch_outputs[1]], ["stateN"], name="fixed_sr_stateN"),
        ]
    )

    outputs = [copy.deepcopy(output) for output in onnx_model.graph.output]
    graph = helper.make_graph(
        nodes,
        "silero_vad_fixed_16000",
        inputs,
        outputs,
        initializer=initializers,
    )
    fixed_model = helper.make_model(
        graph,
        opset_imports=[copy.deepcopy(opset) for opset in onnx_model.opset_import],
        producer_name="finetune.extract_fixed_sr_model",
    )
    fixed_model.ir_version = onnx_model.ir_version
    onnx.checker.check_model(fixed_model)
    return fixed_model


def load_onnx_session(onnx_path: Path) -> ort.InferenceSession:
    """Load ONNX model với ONNX Runtime."""
    print(f"[ONNX] Loading model từ {onnx_path}")
    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = 1
    session = ort.InferenceSession(
        str(onnx_path),
        sess_options,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )

    # In input/output specs
    print("[ONNX] Inputs:")
    for inp in session.get_inputs():
        print(f"  {inp.name}: {inp.shape} ({inp.type})")
    print("[ONNX] Outputs:")
    for out in session.get_outputs():
        print(f"  {out.name}: {out.shape} ({out.type})")

    return session


def run_onnx(
    session: ort.InferenceSession,
    audio_chunk: np.ndarray,    # [1, 512] float32
    state: np.ndarray,          # [2, 1, 128] float32
    sr: int = SAMPLE_RATE,
) -> tuple[np.ndarray, np.ndarray]:
    """Chạy inference ONNX, trả về (prob, new_state)."""
    feeds = {
        "input": audio_chunk.astype(np.float32),
        "state": state.astype(np.float32),
        "sr": np.array(sr, dtype=np.int64),
    }
    output, new_state = session.run(["output", "stateN"], feeds)
    return output, new_state


def load_torch_model(onnx_path: Path) -> torch.nn.Module:
    """
    Convert ONNX → PyTorch dùng onnx2torch.
    Model trả về có thể gọi .parameters() và .train()/.eval().
    """
    try:
        import onnx
        from onnx2torch import convert
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency for ONNX -> PyTorch conversion. "
            "Run: python -m pip install onnx onnx2torch"
        ) from exc

    print(f"[PyTorch] Converting {onnx_path} sang PyTorch...")
    onnx_model = onnx.load(str(onnx_path))
    try:
        onnx_model = extract_fixed_sr_model(onnx_model, SAMPLE_RATE)
        torch_model = FixedSRModelWrapper(convert(onnx_model))
    except Exception as exc:
        print(f"[WARN] onnx2torch conversion failed: {exc}")
        print("[WARN] Falling back to official Silero JIT model for trainable PyTorch weights.")
        try:
            import silero_vad
        except ImportError as jit_exc:
            raise RuntimeError(
                "onnx2torch could not convert this ONNX graph and silero_vad JIT "
                "fallback is unavailable."
            ) from jit_exc
        jit_path = Path(silero_vad.__file__).resolve().parent / "data" / "silero_vad.jit"
        full_model = torch.jit.load(str(jit_path), map_location="cpu")
        torch_model = FixedSRModelWrapper(full_model._model)
        print(f"[PyTorch] Loaded trainable JIT fallback: {jit_path}")
    torch_model.eval()

    n_params = sum(p.numel() for p in torch_model.parameters())
    n_trainable = sum(p.numel() for p in torch_model.parameters() if p.requires_grad)
    print(f"[PyTorch] Parameters: {n_params:,} total, {n_trainable:,} trainable")

    return torch_model


def run_torch(
    model: torch.nn.Module,
    audio_chunk: torch.Tensor,  # [1, 512] float32
    state: torch.Tensor,        # [2, 1, 128] float32
    sr: int = SAMPLE_RATE,
    device: torch.device = torch.device("cpu"),
) -> tuple[torch.Tensor, torch.Tensor]:
    """Chạy inference PyTorch model."""
    audio_chunk = audio_chunk.to(device)
    state = state.to(device)
    sr_tensor = torch.tensor(sr, dtype=torch.int64).to(device)

    with torch.no_grad():
        output, new_state = model(audio_chunk, state, sr_tensor)

    return output, new_state


def verify_match(
    onnx_session: ort.InferenceSession,
    torch_model: torch.nn.Module,
    n_chunks: int = 20,
    atol: float = 1e-4,
    device: torch.device = torch.device("cpu"),
):
    """
    Verify output của ONNX và PyTorch model khớp nhau trên random audio.
    Test stateful behavior qua nhiều chunks.
    """
    print(f"\n[Verify] Chạy {n_chunks} chunks random, so sánh ONNX vs PyTorch...")

    # Init state
    onnx_state = np.zeros((2, 1, 128), dtype=np.float32)
    torch_state = torch.zeros(2, 1, 128, dtype=torch.float32)

    max_diff = 0.0
    for i in range(n_chunks):
        # Random audio chunk (normalize [-1, 1])
        audio_np = np.random.randn(1, CHUNK_SAMPLES).astype(np.float32) * 0.1
        audio_np = np.concatenate(
            [np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32), audio_np],
            axis=1,
        )

        # ONNX
        onnx_out, onnx_new_state = run_onnx(onnx_session, audio_np, onnx_state)

        # PyTorch
        audio_torch = torch.from_numpy(audio_np)
        torch_out, torch_new_state = run_torch(torch_model, audio_torch, torch_state, device=device)

        # So sánh output probability
        diff = abs(float(onnx_out[0, 0]) - float(torch_out[0, 0]))
        max_diff = max(max_diff, diff)

        if diff > atol:
            print(f"  [WARN] Chunk {i+1}: ONNX={onnx_out[0,0]:.6f}, PyTorch={torch_out[0,0]:.6f}, diff={diff:.6f}")
        else:
            print(f"  Chunk {i+1:2d}: ONNX={onnx_out[0,0]:.6f}, PyTorch={torch_out[0,0]:.6f} ✓")

        # Cập nhật state
        onnx_state = onnx_new_state
        torch_state = torch_new_state.detach()

    print(f"\n[Verify] Max difference: {max_diff:.8f}")
    if max_diff <= atol:
        print(f"[Verify] ✅ PASS — ONNX và PyTorch outputs khớp nhau (atol={atol})")
        return True
    else:
        print(f"[Verify] ❌ FAIL — Difference quá lớn ({max_diff:.6f} > {atol})")
        print("         Cần kiểm tra lại conversion hoặc dùng phương án khác.")
        return False


def print_model_architecture(model: torch.nn.Module):
    """In cấu trúc model để hiểu có thể freeze/unfreeze layer nào."""
    print("\n[Architecture] Model layers:")
    for name, module in model.named_modules():
        if len(list(module.children())) == 0:  # leaf modules only
            n_params = sum(p.numel() for p in module.parameters())
            if n_params > 0:
                print(f"  {name}: {module.__class__.__name__} ({n_params:,} params)")


def parse_args():
    parser = argparse.ArgumentParser(description="Convert Silero VAD ONNX → PyTorch trainable model")
    parser.add_argument("--onnx-path", type=Path,
                        default=PROJECT_ROOT / "VAD" / "models" / "vad" / "1" / "vad.onnx")
    parser.add_argument("--verify", action="store_true",
                        help="Verify output match giữa ONNX và PyTorch")
    parser.add_argument("--save", type=Path, default=None,
                        help="Lưu state dict PyTorch model ra file .pth")
    parser.add_argument("--print-arch", action="store_true",
                        help="In cấu trúc model")
    parser.add_argument("--device", type=str, default="cpu",
                        choices=["cpu", "cuda"])
    return parser.parse_args()


def main():
    args = parse_args()
    device = torch.device(args.device)

    if not args.onnx_path.exists():
        print(f"[ERROR] ONNX file không tồn tại: {args.onnx_path}")
        sys.exit(1)

    # Load ONNX session (dùng cho verify)
    onnx_session = load_onnx_session(args.onnx_path)

    # Convert sang PyTorch
    torch_model = load_torch_model(args.onnx_path)
    torch_model = torch_model.to(device)

    if args.print_arch:
        print_model_architecture(torch_model)

    if args.verify:
        success = verify_match(onnx_session, torch_model, device=device)
        if not success:
            print("\n[WARNING] Conversion không khớp hoàn toàn.")
            print("Các phương án thay thế:")
            print("  1. Dùng onnxruntime-training thay vì onnx2torch")
            print("  2. Re-implement kiến trúc từ Silero source code")
            print("  3. Giảm atol nếu sai số chấp nhận được")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "model_state_dict": torch_model.state_dict(),
            "onnx_source": str(args.onnx_path),
        }, args.save)
        print(f"\n[Saved] Model state dict → {args.save}")

    print("\n[Done] Conversion hoàn tất.")
    print("Để dùng model trong training:")
    print("  from convert_onnx_to_torch import load_torch_model")
    print(f"  model = load_torch_model(Path('{args.onnx_path}'))")


if __name__ == "__main__":
    main()
