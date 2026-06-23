from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.vtt_parser import extract_text_in_range, parse_youtube_vtt

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
    assert cues[0].timed_text == ((1.0, "xin"), (1.5, "chao"))


def test_extract_text_in_range_uses_exact_timed_chunks(tmp_path: Path):
    p = tmp_path / "vid__title.vi.vtt"
    p.write_text(
        """WEBVTT

00:00:33.480 --> 00:00:36.430
mới.<00:00:34.680><c> Theo</c><00:00:34.879><c> Sở</c><00:00:35.079><c> Xây</c><00:00:35.239><c> dựng,</c>
""",
        encoding="utf-8",
    )
    cues = parse_youtube_vtt(p)
    assert extract_text_in_range(cues, 33.48, 34.67) == "mới."
    assert extract_text_in_range(cues, 34.68, 36.0) == "Theo Sở Xây dựng,"
