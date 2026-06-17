"""
test_end_to_end_demucs.py – Demucs wiring in scripts/end_to_end_pipeline.py.

Uses a stub Demucs command (no torch) that mirrors Demucs' output layout
(``<out>/<model>/<stem>/vocals.wav``). Keeps the stub output mono 16k so the
clean step just copies it (no ffmpeg dependency in CI).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from audio_fixtures import SAMPLE_RATE, make_mixed, write_wav

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import end_to_end_pipeline as ee  # noqa: E402


STUB_DEMUCS = '''
import argparse, shutil, sys
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--two-stems")
p.add_argument("-n")
p.add_argument("-d")
p.add_argument("-o")
p.add_argument("inp")
a = p.parse_args()
out = Path(a.o) / a.n / Path(a.inp).stem
out.mkdir(parents=True, exist_ok=True)
shutil.copy2(a.inp, out / "vocals.wav")
shutil.copy2(a.inp, out / "no_vocals.wav")
'''


def _make_args(tmp_path: Path, stub: Path) -> argparse.Namespace:
    return argparse.Namespace(
        raw_dir=tmp_path / "raw",
        clean_dir=tmp_path / "clean",
        vocals_dir=tmp_path / "vocals",
        sample_rate=SAMPLE_RATE,
        overwrite=False,
        ffmpeg="ffmpeg",
        demucs=True,
        demucs_cmd=f'"{sys.executable}" "{stub}"',
        demucs_model="htdemucs",
        demucs_device="cpu",
    )


@pytest.fixture()
def stub_demucs(tmp_path: Path) -> Path:
    stub = tmp_path / "stub_demucs.py"
    stub.write_text(STUB_DEMUCS, encoding="utf-8")
    return stub


def test_separate_vocals_maps_raw_to_vocal(tmp_path: Path, stub_demucs: Path) -> None:
    args = _make_args(tmp_path, stub_demucs)
    args.raw_dir.mkdir(parents=True)
    raw = write_wav(args.raw_dir / "clip.wav", make_mixed([("silence", 0.3), ("speech", 0.8)]))

    vocal_map = ee.separate_vocals([raw], args)

    assert raw in vocal_map
    vocal = vocal_map[raw]
    assert vocal.exists()
    assert vocal.name == "vocals.wav"


def test_clean_uses_vocal_but_keeps_raw_as_source(tmp_path: Path, stub_demucs: Path) -> None:
    args = _make_args(tmp_path, stub_demucs)
    args.raw_dir.mkdir(parents=True)
    raw = write_wav(args.raw_dir / "clip.wav", make_mixed([("silence", 0.3), ("speech", 0.8)]))

    vocal_map = ee.separate_vocals([raw], args)
    cleaned = ee.clean_audio_files(args, vocal_map)

    assert len(cleaned) == 1
    row = cleaned[0]
    assert row["source"] == raw              # manifest source stays the raw file
    assert ee.wav_is_clean(row["cleaned"], SAMPLE_RATE)
    # stub vocal is already mono 16k -> copied, not converted
    assert row["status"] == "copied"


def test_clean_without_demucs_cleans_raw_directly(tmp_path: Path, stub_demucs: Path) -> None:
    args = _make_args(tmp_path, stub_demucs)
    args.raw_dir.mkdir(parents=True)
    raw = write_wav(args.raw_dir / "clip.wav", make_mixed([("silence", 0.3), ("speech", 0.8)]))

    cleaned = ee.clean_audio_files(args, None)

    assert cleaned[0]["source"] == raw
    assert ee.wav_is_clean(cleaned[0]["cleaned"], SAMPLE_RATE)
