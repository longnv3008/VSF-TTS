from vsf_wer.normalize import normalize, strip_diacritics


def test_bracket_and_adlib_removed():
    # markup [..] bóc tự động; "yeah" trong blocklist -> rỗng
    assert normalize("[âm nhạc] yeah [âm nhạc]", non_lyric=["yeah"]) == ""


def test_punct_stripped_diacritics_kept():
    assert normalize("Yêu là đau, thương là đau!") == "yêu là đau thương là đau"


def test_raw_keeps_bracket_inner():
    # raw KHÔNG bóc markup -> chữ trong ngoặc thành token (cố ý phạt rác)
    assert normalize("[âm nhạc] yeah", level="raw") == "âm nhạc yeah"


def test_promo_phrase_removed():
    s = normalize(
        "Hãy đăng ký kênh để ủng hộ kênh của mình nhé",
        non_lyric=["hãy đăng ký kênh", "ủng hộ kênh của mình"],
    )
    assert "đăng" not in s and "ủng" not in s
    assert s == "để nhé"


def test_boundary_no_overmatch():
    # "na na" bị lọc nhưng "nan" giữ nguyên (khớp theo ranh giới token)
    assert normalize("nan na na", non_lyric=["na na"]) == "nan"


def test_strip_diacritics_flag():
    assert normalize("Đường về nhà", keep_diacritics=False) == "duong ve nha"


def test_strip_diacritics_fn():
    assert strip_diacritics("Yêu đời") == "Yeu doi"


def test_none_safe():
    assert normalize(None) == ""
