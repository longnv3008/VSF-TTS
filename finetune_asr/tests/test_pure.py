"""Pure-unit tests for finetune_asr — stdlib only, no torch/transformers."""
import pytest

from finetune_asr.text_norm import normalize_target
from finetune_asr.wer_eval import score_wer
from finetune_asr.export_ct2 import build_ct2_convert_cmd
from finetune_asr.lora_config import lora_params
from finetune_asr.hpo import suggest_params


# --- normalize_target ---

def test_normalize_lowercases_and_strips_punct():
    assert normalize_target("Xin chào, các bạn!") == "xin chào các bạn"


def test_normalize_keeps_diacritics():
    # Dấu thanh phonemic -> giữ.
    assert normalize_target("lá") == "lá"


def test_normalize_collapses_whitespace_and_nfc():
    assert normalize_target("  xin   chào  ") == "xin chào"


def test_normalize_none_empty():
    assert normalize_target("") == ""
    assert normalize_target(None) == ""


# --- score_wer ---

def test_score_wer_perfect_is_zero():
    assert score_wer(["xin chào các bạn"], ["xin chào các bạn"]) == 0.0


def test_score_wer_one_sub_in_four():
    assert score_wer(["một hai ba bốn"], ["một hai ba năm"]) == pytest.approx(0.25)


def test_score_wer_micro_average_across_segments():
    # tổng lỗi / tổng token ref: (0 + 1) / (2 + 2) = 0.25
    refs = ["xin chào", "các bạn"]
    hyps = ["xin chào", "các xyz"]
    assert score_wer(refs, hyps) == pytest.approx(0.25)


# --- build_ct2_convert_cmd ---

def test_ct2_cmd_shape():
    cmd = build_ct2_convert_cmd("hf_model_dir", "out_ct2", quantization="float16")
    assert cmd[0] == "ct2-transformers-converter"
    assert "--model" in cmd and "hf_model_dir" in cmd
    assert "--output_dir" in cmd and "out_ct2" in cmd
    assert "--quantization" in cmd and "float16" in cmd


# --- lora_params ---

def test_lora_params_defaults():
    p = lora_params()
    assert p["r"] == 8
    assert p["lora_alpha"] == 16
    assert p["target_modules"] == ["q_proj", "v_proj"]
    assert 0.0 <= p["lora_dropout"] <= 1.0


def test_lora_params_override_rank():
    p = lora_params(rank=16, alpha=32, dropout=0.1)
    assert p["r"] == 16 and p["lora_alpha"] == 32 and p["lora_dropout"] == 0.1


# --- suggest_params (Optuna search space, fake trial) ---

class _FakeTrial:
    def suggest_float(self, name, low, high, *, log=False):
        return low  # giá trị biên thấp, đủ để check key + range

    def suggest_categorical(self, name, choices):
        return choices[1]


def test_suggest_params_keys_and_ranges():
    p = suggest_params(_FakeTrial())
    assert set(p) == {"lr", "rank", "dropout"}
    assert p["rank"] in (4, 8, 16, 32)
    assert p["lr"] > 0
    assert 0.0 <= p["dropout"] <= 0.2
