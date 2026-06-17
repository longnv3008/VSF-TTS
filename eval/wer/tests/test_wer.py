import math

import pytest

from vsf_wer import wer as W


def test_basic_sub_del():
    # ref a b c d / hyp a x c -> a=a, b->x (S), c=c, d del (D)
    c = W.align("a b c d".split(), "a x c".split())
    assert (c.sub, c.dele, c.ins, c.cor, c.n_ref) == (1, 1, 0, 2, 4)
    assert c.errors == 2
    assert c.wer == 0.5


def test_identical():
    c = W.align("a b c".split(), "a b c".split())
    assert c.errors == 0
    assert c.wer == 0.0


def test_all_deletions():
    c = W.align("a b c".split(), [])
    assert (c.dele, c.n_ref) == (3, 3)
    assert c.wer == 1.0


def test_insertions_within_ref():
    c = W.align("a b c".split(), "a b c d e".split())
    assert c.ins == 2
    assert c.wer == pytest.approx(2 / 3)


def test_spurious_empty_ref():
    c = W.align([], "x y".split())
    assert c.n_ref == 0
    assert c.ins == 2
    assert math.isnan(c.wer)
    assert c.spurious is True


def test_micro_average():
    a = W.align("a b".split(), "a b".split())          # 0 err / N2
    b = W.align("a b c d".split(), "a x".split())        # S1 D2 / N4 = 3 err
    assert b.errors == 3 and b.n_ref == 4
    assert W.micro_average([a, b]) == pytest.approx(3 / 6)


def test_cer_via_chars():
    from vsf_wer.normalize import chars
    c = W.align(chars("abc"), chars("abx"))
    assert c.sub == 1 and c.n_ref == 3
    assert c.wer == pytest.approx(1 / 3)


def test_jiwer_crosscheck():
    jiwer = pytest.importorskip("jiwer")
    ref, hyp = "a b c d", "a x c"
    mine = W.align(ref.split(), hyp.split()).wer
    assert mine == pytest.approx(jiwer.wer(ref, hyp))
