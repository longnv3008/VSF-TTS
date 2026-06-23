"""Export LoRA-merged Whisper sang CTranslate2 cho faster-whisper.

faster-whisper (CTranslate2) KHÔNG load được PEFT adapter. Deploy = merge adapter vào base
HF model -> ct2-transformers-converter -> thư mục CT2 -> trỏ ASR_MODEL vào đó.

Module này chỉ build argv cho converter (pure, testable). Việc merge + chạy converter thật
là bước tay (cần transformers/ctranslate2 cài trong env finetune-asr).
"""

from __future__ import annotations


def build_ct2_convert_cmd(model_dir: str, out_dir: str, *, quantization: str = "float16") -> list[str]:
    """argv cho ct2-transformers-converter (model HF đã merge LoRA -> CT2)."""
    return [
        "ct2-transformers-converter",
        "--model",
        model_dir,
        "--output_dir",
        out_dir,
        "--quantization",
        quantization,
    ]
