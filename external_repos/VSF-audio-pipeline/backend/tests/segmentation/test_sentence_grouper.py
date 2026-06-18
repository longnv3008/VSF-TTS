from app.modules.audio_pipeline.application.segmentation.sentence_grouper import cues_to_sentence_units
from app.modules.audio_pipeline.application.segmentation.types import TranscriptCue


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
