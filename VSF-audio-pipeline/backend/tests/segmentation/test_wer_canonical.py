from math import isnan

from app.modules.audio_pipeline.application.segmentation.wer_canonical import (
    Counts,
    align,
    micro_average,
    normalize,
    tokens,
)


def test_normalize_strips_markup_and_punct_keeps_tones():
    # [âm nhạc] markup bị bỏ; dấu câu bỏ; dấu thanh giữ.
    assert normalize("[âm nhạc] Chợt nhận ra, rằng!") == "chợt nhận ra rằng"


def test_normalize_collapses_adlib_runs():
    # run >=2 token ad-lib bị xoá; 'là' (có dấu) KHÁC 'la' nên không bị nuốt.
    assert normalize("la la la chợt nhận ra") == "chợt nhận ra"
    assert normalize("là chợt nhận ra") == "là chợt nhận ra"


def test_align_counts_sub_del_ins():
    ref = tokens(normalize("một hai ba bốn"))
    hyp = tokens(normalize("một hai bốn năm"))
    c = align(ref, hyp)
    # ref=4 token. "ba" deleted, "năm" inserted -> sai lệch.
    assert c.n_ref == 4
    assert c.errors == c.sub + c.dele + c.ins
    assert c.wer == c.errors / 4


def test_align_empty_ref_is_spurious_when_hyp_has_tokens():
    c = align([], tokens(normalize("lời thừa")))
    assert c.n_ref == 0
    assert isnan(c.wer)
    assert c.spurious is True


def test_micro_average_ignores_zero_ref():
    a = align(tokens("a b c"), tokens("a b c"))      # 0 lỗi / 3
    b = align(tokens("x y"), tokens("x z"))          # 1 lỗi / 2
    empty = align([], tokens("junk"))                # bỏ qua (N=0)
    assert micro_average([a, b, empty]) == 1 / 5
