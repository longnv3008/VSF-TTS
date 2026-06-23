from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.vtt_parser import (
    parse_youtube_vtt,
    parse_youtube_vtt_words,
)

VTT = """WEBVTT
Kind: captions
Language: vi

00:00:01.000 --> 00:00:03.000
<00:00:01.000><c> xin</c><00:00:01.500><c> chao</c>

00:00:01.000 --> 00:00:03.000
xin chao

00:00:03.200 --> 00:00:05.000
cac ban.
"""

WORDS_VTT = """WEBVTT
Kind: captions
Language: vi

00:00:01.000 --> 00:00:02.500
xin<00:00:01.300><c> chào</c><00:00:01.800><c> bạn.</c>
"""

ROLLING_VTT = """WEBVTT
Kind: captions
Language: vi

00:00:01.000 --> 00:00:02.500
xin<00:00:01.300><c> chào</c>

00:00:02.500 --> 00:00:02.510
xin chào

00:00:02.510 --> 00:00:04.000
xin chào
bạn<00:00:02.800><c> nhé.</c>
"""

PLAIN_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
Xin chào các bạn.
"""


def test_parse_dedup_and_clean(tmp_path: Path):
    p = tmp_path / "vid__title.vi.vtt"
    p.write_text(VTT, encoding="utf-8")
    cues = parse_youtube_vtt(p)
    texts = [c.text for c in cues]
    assert "xin chao" in texts[0]
    assert any("cac ban" in t for t in texts)
    # Không lặp lại cue "xin chao" hai lần liên tiếp.
    assert texts.count("xin chao") == 1
    assert cues[0].start == 1.0 and cues[0].end == 3.0


def test_parse_words_basic(tmp_path):
    p = tmp_path / "vid__t.vi.vtt"
    p.write_text(WORDS_VTT, encoding="utf-8")
    words = parse_youtube_vtt_words(p)
    assert [w.text for w in words] == ["xin", "chào", "bạn."]
    assert words[0].start == 1.0 and words[0].end == 1.3
    assert words[1].start == 1.3 and words[1].end == 1.8
    assert words[2].start == 1.8 and words[2].end == 2.5


def test_parse_words_skips_plain_and_repeat_cues(tmp_path):
    p = tmp_path / "vid__t.vi.vtt"
    p.write_text(ROLLING_VTT, encoding="utf-8")
    words = parse_youtube_vtt_words(p)
    # Plain carried-prefix line and the 10ms repeat cue contribute no new words.
    assert [w.text for w in words] == ["xin", "chào", "bạn", "nhé."]
    assert [w.text for w in words].count("xin") == 1
    # Last word of cue 1 ends at that cue's end; first word of cue 3 starts later -> real gap.
    chao = next(w for w in words if w.text == "chào")
    ban = next(w for w in words if w.text == "bạn")
    assert chao.end == 2.5
    assert ban.start == 2.51


def test_parse_words_empty_when_no_inline_ts(tmp_path):
    p = tmp_path / "vid__t.vi.vtt"
    p.write_text(PLAIN_VTT, encoding="utf-8")
    assert parse_youtube_vtt_words(p) == []
