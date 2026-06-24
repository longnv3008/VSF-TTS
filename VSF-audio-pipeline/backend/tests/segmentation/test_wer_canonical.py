from math import isnan

from app.modules.audio_pipeline.application.segmentation.wer_canonical import (
    Counts,
    align,
    align_windowed,
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


def test_align_windowed_strips_padding_neighbor_words():
    # audio clip padding ôm câu hàng xóm: ref có từ thừa đầu/cuối, label khớp giữa.
    ref = tokens(normalize("alpha beta một hai ba bốn gamma delta epsilon"))
    hyp = tokens(normalize("một hai ba bốn"))
    full = align(ref, hyp)
    win = align_windowed(ref, hyp)
    assert full.dele == 5  # 2 đầu + 3 cuối thừa
    assert win.errors == 0  # rìa bị bỏ -> label khớp hoàn hảo
    assert win.n_ref == 4
    assert win.wer == 0.0


def test_align_windowed_keeps_interior_errors():
    # lỗi GIỮA span (sub) phải được giữ, chỉ rìa mới trim.
    ref = tokens(normalize("alpha một hai ba bốn delta"))
    hyp = tokens(normalize("một XX ba bốn"))
    win = align_windowed(ref, hyp)
    assert win.n_ref == 4
    assert win.sub == 1
    assert win.wer == 0.25


def test_align_windowed_no_match_falls_back_to_full():
    # không token nào khớp -> không trim (label rác thật).
    ref = tokens(normalize("một hai ba"))
    hyp = tokens(normalize("xxx yyy zzz"))
    assert align_windowed(ref, hyp).wer == align(ref, hyp).wer


def test_micro_average_ignores_zero_ref():
    a = align(tokens("a b c"), tokens("a b c"))      # 0 lỗi / 3
    b = align(tokens("x y"), tokens("x z"))          # 1 lỗi / 2
    empty = align([], tokens("junk"))                # bỏ qua (N=0)
    assert micro_average([a, b, empty]) == 1 / 5
