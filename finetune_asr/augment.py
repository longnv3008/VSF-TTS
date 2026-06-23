"""Audio augmentation cho fine-tune ASR (tăng đa dạng âm thanh).

Waveform: pitch shift, time-stretch, thêm nhiễu (theo SNR). Spec: SpecAugment mask trên
log-mel. numpy thuần cho noise/spec; librosa lazy cho pitch/stretch. Áp lúc train (opt-in).
"""

from __future__ import annotations

import numpy as np


def add_noise(y: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """Thêm nhiễu Gaussian ở mức SNR mục tiêu (dB)."""
    y = np.asarray(y, dtype=np.float32)
    sig_power = float(np.mean(y.astype(np.float64) ** 2)) or 1e-12
    noise_power = sig_power / (10.0 ** (snr_db / 10.0))
    noise = rng.normal(0.0, np.sqrt(noise_power), size=y.shape).astype(np.float32)
    return y + noise


def pitch_shift(y: np.ndarray, sr: int, n_steps: float) -> np.ndarray:
    """Dịch cao độ n_steps semitone (librosa)."""
    import librosa

    return librosa.effects.pitch_shift(np.asarray(y, dtype=np.float32), sr=sr, n_steps=n_steps)


def time_stretch(y: np.ndarray, rate: float) -> np.ndarray:
    """Co giãn thời gian theo rate (>1 nhanh hơn, ngắn lại); librosa."""
    import librosa

    return librosa.effects.time_stretch(np.asarray(y, dtype=np.float32), rate=rate)


def spec_augment(
    feats: np.ndarray,
    *,
    n_freq_masks: int = 2,
    freq_w: int = 10,
    n_time_masks: int = 2,
    time_w: int = 20,
    rng: np.random.Generator,
) -> np.ndarray:
    """Mask ngẫu nhiên dải freq/time trên log-mel (feats shape [n_mels, n_frames]) -> 0."""
    out = np.array(feats, dtype=feats.dtype, copy=True)
    n_mels, n_frames = out.shape
    for _ in range(n_freq_masks):
        w = int(rng.integers(0, freq_w + 1))
        if w and w < n_mels:
            start = int(rng.integers(0, n_mels - w + 1))
            out[start:start + w, :] = 0
    for _ in range(n_time_masks):
        w = int(rng.integers(0, time_w + 1))
        if w and w < n_frames:
            start = int(rng.integers(0, n_frames - w + 1))
            out[:, start:start + w] = 0
    return out


def apply_waveform_augment(
    y: np.ndarray,
    sr: int,
    rng: np.random.Generator,
    *,
    p_pitch: float = 0.5,
    p_speed: float = 0.5,
    p_noise: float = 0.5,
    transforms: list | None = None,
) -> np.ndarray:
    """Áp random các transform waveform theo xác suất. transforms=[(p, fn(y,sr,rng))] override."""
    if transforms is None:
        transforms = [
            (p_pitch, lambda yy, s, r: pitch_shift(yy, s, float(r.uniform(-3, 3)))),
            (p_speed, lambda yy, s, r: time_stretch(yy, float(r.uniform(0.9, 1.1)))),
            (p_noise, lambda yy, s, r: add_noise(yy, float(r.uniform(5, 30)), r)),
        ]
    out = np.asarray(y, dtype=np.float32)
    for prob, fn in transforms:
        if rng.random() < prob:
            out = np.asarray(fn(out, sr, rng), dtype=np.float32)
    return out
