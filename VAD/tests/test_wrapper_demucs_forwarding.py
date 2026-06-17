"""Wrapper: Demucs default-on, decide once, forward explicit on/off to sub-paths."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import run_vsf_github_to_labels as w  # noqa: E402


def _parse(monkeypatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    return w.parse_args()


def test_decide_available_keeps_on_and_resolves(monkeypatch) -> None:
    monkeypatch.setattr(w, "demucs_available", lambda cmd: True)
    args = _parse(monkeypatch, ["--url", "https://youtu.be/x"])
    w.resolve_and_probe_demucs(args)
    assert args.demucs is True
    assert args.demucs_cmd and "demucs" in args.demucs_cmd


def test_decide_unavailable_disables(monkeypatch) -> None:
    monkeypatch.setattr(w, "demucs_available", lambda cmd: False)
    args = _parse(monkeypatch, ["--url", "https://youtu.be/x"])
    w.resolve_and_probe_demucs(args)
    assert args.demucs is False


def test_local_vad_forwards_no_demucs_when_off(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(w, "run_command", lambda cmd, cwd=None: captured.update(cmd=cmd))
    args = _parse(monkeypatch, ["--url", "https://youtu.be/x", "--no-demucs"])
    w.run_local_vad(args, Path("audio"))
    assert "--no-demucs" in captured["cmd"]
    assert "--demucs" not in captured["cmd"]


def test_local_vad_forwards_demucs_when_on(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(w, "run_command", lambda cmd, cwd=None: captured.update(cmd=cmd))
    args = _parse(monkeypatch, ["--url", "https://youtu.be/x"])
    args.demucs_cmd = '"py" -m demucs'  # pretend resolved
    w.run_local_vad(args, Path("audio"))
    assert "--demucs" in captured["cmd"]
    assert "--demucs-cmd" in captured["cmd"]


def test_github_pipeline_forwards_enabled_when_on(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(w, "run_command", lambda cmd, cwd=None: captured.update(cmd=cmd))
    args = _parse(monkeypatch, ["--url", "https://youtu.be/x"])
    args.demucs_cmd = '"py" -m demucs'
    w.run_github_pipeline(args, Path("audio"))
    assert "--demucs-enabled" in captured["cmd"]


def test_github_pipeline_no_demucs_when_off(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(w, "run_command", lambda cmd, cwd=None: captured.update(cmd=cmd))
    args = _parse(monkeypatch, ["--url", "https://youtu.be/x", "--no-demucs"])
    w.run_github_pipeline(args, Path("audio"))
    assert "--demucs-enabled" not in captured["cmd"]
