import numpy as np
import pyloudnorm as pyln

def normalize_value(value, min_value, max_value):
    normalized = (value - min_value) / (max_value - min_value)
    normalized_clamped = max(0, min(1, normalized))
    return normalized_clamped


def calculate_audio_volume(audio_np, sample_rate: int) -> float:
    block_size = len(audio_np) / sample_rate
    meter = pyln.Meter(sample_rate, block_size=block_size)
    loudness = meter.integrated_loudness(audio_np)

    # Loudness goes from -20 to 80 (more or less), where -20 is quiet and 80 is
    # loud.
    loudness = normalize_value(loudness, -20, 80)

    return loudness


def exp_smoothing(value: float, prev_value: float, factor: float) -> float:
    return prev_value + factor * (value - prev_value)