import pytest

from app.modules.audio_pipeline.application.separation.noise_probe import (
    parse_noise_floor_db,
)

# stderr giả lập của ffmpeg astats: per-channel rồi Overall (match cuối = overall).
_ASTATS_NOISY = """
[Parsed_astats_0 @ 0x55] Channel: 1
[Parsed_astats_0 @ 0x55] Noise floor dB: -41.998765
[Parsed_astats_0 @ 0x55] Overall
[Parsed_astats_0 @ 0x55] Noise floor dB: -38.123456
"""

_ASTATS_CLEAN = """
[Parsed_astats_0 @ 0x55] Channel: 1
[Parsed_astats_0 @ 0x55] Noise floor dB: -70.500000
[Parsed_astats_0 @ 0x55] Overall
[Parsed_astats_0 @ 0x55] Noise floor dB: -68.900000
"""


def test_parse_noise_floor_takes_overall_last_match():
    assert parse_noise_floor_db(_ASTATS_NOISY) == pytest.approx(-38.123456)
    assert parse_noise_floor_db(_ASTATS_CLEAN) == pytest.approx(-68.9)


def test_parse_noise_floor_handles_inf():
    assert parse_noise_floor_db("Noise floor dB: -inf") == float("-inf")


def test_parse_noise_floor_missing_raises():
    with pytest.raises(ValueError):
        parse_noise_floor_db("no stats here")
