"""Tests cho augment — cần numpy (+ librosa cho pitch/stretch)."""
import numpy as np
import pytest

from finetune_asr.augment import (
    add_noise,
    apply_waveform_augment,
    spec_augment,
)


def _sine(n=16000, sr=16000, f=220.0):
    t = np.arange(n) / sr
    return np.sin(2 * np.pi * f * t).astype(np.float32)


# --- add_noise ---

def test_add_noise_preserves_shape_and_changes_values():
    y = _sine()
    out = add_noise(y, snr_db=10.0, rng=np.random.default_rng(0))
    assert out.shape == y.shape
    assert not np.array_equal(out, y)


def test_add_noise_higher_snr_smaller_perturbation():
    y = _sine()
    low = add_noise(y, snr_db=5.0, rng=np.random.default_rng(0))
    high = add_noise(y, snr_db=30.0, rng=np.random.default_rng(0))
    assert np.abs(high - y).mean() < np.abs(low - y).mean()


# --- spec_augment ---

def test_spec_augment_masks_to_zero_and_keeps_shape():
    feats = np.ones((80, 100), dtype=np.float32)
    out = spec_augment(feats, n_freq_masks=1, freq_w=5, n_time_masks=1, time_w=10,
                       rng=np.random.default_rng(0))
    assert out.shape == feats.shape
    assert (out == 0).any()  # có vùng bị mask


def test_spec_augment_deterministic_with_seed():
    feats = np.ones((80, 100), dtype=np.float32)
    a = spec_augment(feats, n_freq_masks=2, freq_w=5, n_time_masks=2, time_w=10,
                     rng=np.random.default_rng(42))
    b = spec_augment(feats, n_freq_masks=2, freq_w=5, n_time_masks=2, time_w=10,
                     rng=np.random.default_rng(42))
    assert np.array_equal(a, b)


# --- apply_waveform_augment ---

def test_apply_waveform_all_prob_zero_unchanged():
    y = _sine()
    out = apply_waveform_augment(y, 16000, np.random.default_rng(0),
                                 p_pitch=0.0, p_speed=0.0, p_noise=0.0)
    assert np.array_equal(out, y)


def test_apply_waveform_injected_transform_applied():
    y = _sine()
    bump = [(1.0, lambda yy, sr, rng: yy + 1.0)]
    out = apply_waveform_augment(y, 16000, np.random.default_rng(0), transforms=bump)
    assert np.allclose(out, y + 1.0)


def test_apply_waveform_deterministic_with_seed():
    y = _sine()
    a = apply_waveform_augment(y, 16000, np.random.default_rng(7),
                               p_pitch=0.5, p_speed=0.5, p_noise=0.5)
    b = apply_waveform_augment(y, 16000, np.random.default_rng(7),
                               p_pitch=0.5, p_speed=0.5, p_noise=0.5)
    assert np.array_equal(a, b)


# --- librosa-backed (skip nếu thiếu) ---

def test_pitch_shift_preserves_length():
    pytest.importorskip("librosa")
    from finetune_asr.augment import pitch_shift

    y = _sine()
    out = pitch_shift(y, 16000, 2)
    assert out.shape[0] == y.shape[0]


def test_time_stretch_changes_length():
    pytest.importorskip("librosa")
    from finetune_asr.augment import time_stretch

    y = _sine()
    out = time_stretch(y, 0.8)
    assert out.shape[0] != y.shape[0]
