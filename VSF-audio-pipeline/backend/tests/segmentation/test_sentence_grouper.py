from app.modules.audio_pipeline.application.segmentation.sentence_grouper import (
    cues_to_sentence_units,
    words_to_sentence_units,
)
from app.modules.audio_pipeline.application.segmentation.types import TranscriptCue, WordToken


def test_groups_until_sentence_end():
    cues = [
        TranscriptCue(0.0, 1.0, "xin chao"),
        TranscriptCue(1.0, 2.0, "cac ban."),
        TranscriptCue(2.1, 3.0, "hom nay"),
        TranscriptCue(3.0, 4.0, "troi dep."),
    ]
    units = cues_to_sentence_units(cues, phrase_gap_sec=0.45, max_sentence_sec=12.0, min_sentence_sec=0.3)
    assert len(units) == 2
    assert units[0].text == "xin chao cac ban."
    assert units[0].start == 0.0 and units[0].end == 2.0
    assert units[1].text == "hom nay troi dep."


def test_splits_on_large_gap():
    cues = [
        TranscriptCue(0.0, 1.0, "phan mot"),
        TranscriptCue(3.0, 4.0, "phan hai"),
    ]
    units = cues_to_sentence_units(cues, phrase_gap_sec=0.45, max_sentence_sec=12.0, min_sentence_sec=0.3)
    assert len(units) == 2


def _w(text, start, end):
    return WordToken(text=text, start=start, end=end)


def test_words_group_to_sentence_end():
    words = [
        _w("Xin", 0.0, 0.5), _w("chào", 0.5, 1.0), _w("bạn.", 1.0, 1.5),
        _w("Hôm", 1.6, 2.0), _w("nay", 2.0, 2.5), _w("trời", 2.5, 3.0), _w("đẹp.", 3.0, 3.5),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=12.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert [u.text for u in units] == ["Xin chào bạn.", "Hôm nay trời đẹp."]
    assert units[0].start == 0.0 and units[0].end == 1.5
    assert units[1].start == 1.6 and units[1].end == 3.5


def test_words_keep_whole_sentence_under_cap():
    # "...các bản Mò O Ồ Ồ, bản án và bản Yên Hợp." (~10.6s) stays one unit when cap=12.
    words = [
        _w("các", 0.0, 0.4), _w("bản", 0.4, 1.0),
        _w("Mò", 1.0, 3.5), _w("O", 3.5, 5.0), _w("Ồ", 5.0, 6.5), _w("Ồ,", 6.5, 8.0),
        _w("bản", 8.0, 8.4), _w("án", 8.4, 8.9), _w("và", 8.9, 9.2),
        _w("bản", 9.2, 9.6), _w("Yên", 9.6, 10.0), _w("Hợp.", 10.0, 10.6),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=12.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert len(units) == 1
    assert "bản án" in units[0].text


def test_words_over_cap_split_at_comma_not_mid_clause():
    # Same sentence with cap=8 -> split at the comma after "Ồ,", "bản án" stays intact.
    words = [
        _w("các", 0.0, 0.4), _w("bản", 0.4, 1.0),
        _w("Mò", 1.0, 3.5), _w("O", 3.5, 5.0), _w("Ồ", 5.0, 6.5), _w("Ồ,", 6.5, 8.0),
        _w("bản", 8.0, 8.4), _w("án", 8.4, 8.9), _w("và", 8.9, 9.2),
        _w("bản", 9.2, 9.6), _w("Yên", 9.6, 10.0), _w("Hợp.", 10.0, 10.6),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=8.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert len(units) == 2
    assert units[0].text.endswith("Ồ,")
    assert units[1].text == "bản án và bản Yên Hợp."


def test_words_over_cap_no_comma_split_at_longest_pause():
    words = [
        _w("a", 0.0, 1.0), _w("b", 1.0, 2.0), _w("c", 2.0, 3.0), _w("d", 3.0, 4.0),
        _w("e", 4.0, 5.0), _w("f", 5.6, 6.6), _w("g", 6.6, 7.6), _w("h", 7.6, 8.6),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=8.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert units[0].text == "a b c d e"   # split at the 0.6s pause before "f"


def test_words_submin_fragment_merges_into_previous():
    words = [
        _w("Xin", 0.0, 0.5), _w("chào", 0.5, 1.0), _w("bạn.", 1.0, 1.5),
        _w("Ừ.", 1.6, 1.7),
    ]
    units = words_to_sentence_units(words, max_sentence_sec=12.0, min_sentence_sec=0.3, phrase_gap_sec=0.45)
    assert len(units) == 1
    assert units[0].text == "Xin chào bạn. Ừ."
