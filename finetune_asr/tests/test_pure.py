"""Pure-unit tests for finetune_asr — stdlib only, no torch/transformers."""
import pytest

from finetune_asr.text_norm import normalize_target
from finetune_asr.wer_eval import score_wer
from finetune_asr.export_ct2 import build_ct2_convert_cmd


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
