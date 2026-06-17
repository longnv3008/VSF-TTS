"""Local pipeline: Demucs default-on, probe gating, per-file fallback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audio_fixtures import SAMPLE_RATE, make_mixed, write_wav

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import end_to_end_pipeline as ee  # noqa: E402


def _args(**over) -> argparse.Namespace:
    base = dict(demucs=True, demucs_cmd=None)
    base.update(over)
    return argparse.Namespace(**base)


def test_probe_unavailable_disables_demucs(monkeypatch) -> None:
    monkeypatch.setattr(ee, "demucs_available", lambda cmd: False)
    args = _args()
    ee.resolve_and_probe_demucs(args)
    assert args.demucs is False


def test_probe_available_keeps_demucs_and_resolves_cmd(monkeypatch) -> None:
    monkeypatch.setattr(ee, "demucs_available", lambda cmd: True)
    args = _args()
    ee.resolve_and_probe_demucs(args)
    assert args.demucs is True
    assert args.demucs_cmd is not None
    assert "demucs" in args.demucs_cmd


def test_no_demucs_flag_skips_probe(monkeypatch) -> None:
    called = {"n": 0}
    monkeypatch.setattr(ee, "demucs_available", lambda cmd: called.__setitem__("n", called["n"] + 1) or True)
    args = _args(demucs=False)
    ee.resolve_and_probe_demucs(args)
    assert args.demucs is False
    assert called["n"] == 0  # probe never run when disabled


def test_per_file_failure_falls_back_to_raw(tmp_path: Path, monkeypatch) -> None:
    # A demucs cmd that always errors -> that file omitted from vocal_map.
    args = argparse.Namespace(
        raw_dir=tmp_path / "raw",
        vocals_dir=tmp_path / "vocals",
        demucs_model="htdemucs",
        demucs_device="cpu",
        demucs_cmd="definitely-not-a-real-binary-xyz",
        overwrite=False,
    )
    args.raw_dir.mkdir(parents=True)
    raw = write_wav(args.raw_dir / "clip.wav", make_mixed([("silence", 0.2), ("speech", 0.5)]))

    vocal_map = ee.separate_vocals([raw], args)
    assert raw not in vocal_map  # fell back; clean step will use raw
