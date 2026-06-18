from app.modules.audio_pipeline.application.segmentation.text_quality import (
    clean_transcript,
    collapse_repetition,
    has_excessive_repetition,
    has_promo_marker,
    is_blocklisted,
    normalize_vlsp,
)


# --------------------------------------------------------------------------- #
# is_blocklisted
# --------------------------------------------------------------------------- #
def test_blocklist_exact_match_ignores_case_and_punct():
    assert is_blocklisted("Cảm ơn các bạn đã theo dõi")
    assert is_blocklisted("cảm ơn các bạn đã theo dõi.")
    assert is_blocklisted("Thank you for watching!")
    assert is_blocklisted("  hãy đăng ký kênh  ")


def test_blocklist_does_not_match_real_text_or_substring():
    assert not is_blocklisted("hôm nay trời rất đẹp")
    # cụm ảo giác là substring nhưng câu thật dài hơn -> không drop
    assert not is_blocklisted("tôi muốn cảm ơn các bạn đã theo dõi chương trình")
    assert not is_blocklisted("")


# --------------------------------------------------------------------------- #
# has_promo_marker (substring promo kênh — đặc trưng, drop cả khi có chữ thừa)
# --------------------------------------------------------------------------- #
def test_promo_marker_catches_channel_promo_with_trailing_words():
    # hallucination THẬT của i724: exact-match blocklist bỏ lọt vì có đuôi thừa
    assert has_promo_marker(
        "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"
    )
    assert has_promo_marker("nhớ đăng ký kênh của mình nha mọi người")


def test_promo_marker_keeps_real_sentence_mentioning_channel_or_video():
    # câu thật chỉ nhắc "kênh"/"video" nhưng KHÔNG chứa cụm promo -> giữ
    assert not has_promo_marker("tôi thích xem video này trên kênh truyền hình quốc gia")
    assert not has_promo_marker("")


# --------------------------------------------------------------------------- #
# repetition
# --------------------------------------------------------------------------- #
def test_collapse_repetition_caps_consecutive_tokens():
    assert collapse_repetition("đi đi đi đi đi", max_repeat=2) == "đi đi"
    assert collapse_repetition("xin chào các bạn", max_repeat=2) == "xin chào các bạn"


def test_has_excessive_repetition():
    assert has_excessive_repetition(("ha " * 12).strip(), limit=10)
    assert not has_excessive_repetition("ha ha ha", limit=10)
    assert not has_excessive_repetition("", limit=10)


# --------------------------------------------------------------------------- #
# normalize_vlsp
# --------------------------------------------------------------------------- #
def test_normalize_keeps_plain_vietnamese_unchanged():
    # bảo tồn dấu thanh + dấu câu cuối, chỉ gom whitespace
    assert normalize_vlsp("xin chào các bạn.") == "xin chào các bạn."
    assert normalize_vlsp("xin  chào   các bạn") == "xin chào các bạn"
    assert normalize_vlsp("") == ""


def test_normalize_joins_spelled_acronyms():
    assert normalize_vlsp("khối n a t o họp") == "khối nato họp"
    assert normalize_vlsp("đội n.a.t.o") == "đội nato"
    assert normalize_vlsp("fifa công bố") == "fifa công bố"


def test_normalize_keeps_english_proper_nouns_canonical():
    assert normalize_vlsp("xem trên youtube nhé") == "xem trên YouTube nhé"
    assert normalize_vlsp("lên facebook") == "lên Facebook"


# --------------------------------------------------------------------------- #
# clean_transcript (orchestrator)
# --------------------------------------------------------------------------- #
def test_clean_transcript_passthrough_normalizes():
    assert clean_transcript("xin chào các bạn.") == "xin chào các bạn."


def test_clean_transcript_empty_inputs():
    assert clean_transcript("") == ""
    assert clean_transcript(None) == ""
    assert clean_transcript("   ") == ""


def test_clean_transcript_rejects_on_no_speech_and_low_logprob():
    # cả 2 điều kiện -> drop
    assert clean_transcript("nội dung mờ", no_speech_prob=0.9, avg_logprob=-2.0) == ""
    # no_speech cao nhưng logprob ổn -> giữ
    assert clean_transcript("nội dung thật", no_speech_prob=0.9, avg_logprob=-0.2) == "nội dung thật"
    # logprob thấp nhưng no_speech thấp -> giữ
    assert clean_transcript("nội dung thật", no_speech_prob=0.1, avg_logprob=-2.0) == "nội dung thật"


def test_clean_transcript_drops_blocklisted():
    assert clean_transcript("Thank you for watching!") == ""
    assert clean_transcript("Hãy đăng ký kênh") == ""


def test_clean_transcript_drops_promo_with_trailing_words():
    # text-layer phải diệt hallucination promo dù KHÔNG có prob (reject-by-prob có thể không kích)
    assert clean_transcript(
        "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"
    ) == ""


def test_clean_transcript_keeps_real_sentence_mentioning_channel():
    s = "tôi thích xem video này trên kênh truyền hình quốc gia"
    assert clean_transcript(s) == s


def test_clean_transcript_drops_excessive_repetition():
    assert clean_transcript(("loop " * 12).strip()) == ""
