import pytest

from app.modules.audio_pipeline.application.segmentation.wer_gate import segment_wer


def test_identical_is_zero():
    assert segment_wer("xin chao cac ban", "xin chao cac ban") == 0.0


def test_punctuation_and_case_ignored():
    assert segment_wer("Xin chao, cac ban!", "xin chao cac ban") == 0.0


def test_all_wrong_is_one():
    assert segment_wer("mot hai ba", "x y z") == pytest.approx(1.0)


def test_empty_reference_returns_zero():
    # ref rỗng -> không gate được -> 0.0 (không drop).
    assert segment_wer("", "bat ky text nao") == 0.0


def test_empty_hypothesis_with_ref_is_one():
    # ASR im lặng nhưng VTT có chữ -> toàn deletion -> WER 1.0.
    assert segment_wer("mot hai ba bon", "") == pytest.approx(1.0)


def test_one_substitution_in_four_tokens():
    # 1 lỗi / 4 token ref = 0.25 > ngưỡng 0.05 -> sẽ bị flag.
    assert segment_wer("mot hai ba bon", "mot hai ba nam") == pytest.approx(0.25)
