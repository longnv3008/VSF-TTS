"""LoRA config cho Whisper fine-tune.

`lora_params` thuần (dict) -> test được không cần peft. `build_lora_config` import peft
trong hàm (lazy) để module import được trong env không có peft (pure-unit tests).
Target q_proj/v_proj = attention proj của Whisper — đủ cho LoRA nhẹ.
"""

from __future__ import annotations


def lora_params(*, rank: int = 8, alpha: int = 16, dropout: float = 0.05) -> dict:
    """Tham số LoRA dạng dict (kwargs cho peft.LoraConfig)."""
    return {
        "r": rank,
        "lora_alpha": alpha,
        "lora_dropout": dropout,
        "target_modules": ["q_proj", "v_proj"],
        "bias": "none",
        "task_type": "SEQ_2_SEQ_LM",
    }


def build_lora_config(*, rank: int = 8, alpha: int = 16, dropout: float = 0.05):
    """peft.LoraConfig từ lora_params (import lazy)."""
    from peft import LoraConfig

    return LoraConfig(**lora_params(rank=rank, alpha=alpha, dropout=dropout))
