from app.modules.audio_pipeline.application.segmentation.music_detect import (
    DEFAULT_MUSIC_KEYWORDS,
    is_music_title,
)


def test_official_mv_is_music():
    assert is_music_title("BƯỚC QUA NHAU V## Official MV", keywords=DEFAULT_MUSIC_KEYWORDS)


def test_featuring_is_music():
    assert is_music_title("Nếu Như Ta Chưa Còn - MCK ft. A AP", keywords=DEFAULT_MUSIC_KEYWORDS)


def test_lyrics_is_music():
    assert is_music_title("Some Song (Lyrics Video)", keywords=DEFAULT_MUSIC_KEYWORDS)


def test_speech_title_is_not_music():
    assert not is_music_title(
        "Con gái Quảng Trị nói chuyện dễ thương", keywords=DEFAULT_MUSIC_KEYWORDS
    )


def test_empty_title_is_not_music():
    assert not is_music_title("", keywords=DEFAULT_MUSIC_KEYWORDS)


def test_custom_artist_keyword_catches_bare_title():
    # "song - artist" không có keyword generic -> operator thêm tên nghệ sĩ.
    assert is_music_title("toidaidot - GREY D", keywords=("grey d",))


def test_case_insensitive():
    assert is_music_title("xyz OFFICIAL MV", keywords=DEFAULT_MUSIC_KEYWORDS)
