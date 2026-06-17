"""Unit tests for scripts/demucs_env.py (no torch needed)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import demucs_env as de  # noqa: E402


def test_resolve_explicit_passthrough(tmp_path: Path) -> None:
    assert de.resolve_demucs_cmd("my -m demucs", tmp_path) == "my -m demucs"


def test_resolve_uses_venv_demucs_when_present(tmp_path: Path) -> None:
    # Create the platform-appropriate convention python file.
    if os.name == "nt":
        py = tmp_path / ".venv-demucs" / "Scripts" / "python.exe"
    else:
        py = tmp_path / ".venv-demucs" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")

    resolved = de.resolve_demucs_cmd(None, tmp_path)
    assert ".venv-demucs" in resolved
    assert resolved.endswith("-m demucs")


def test_resolve_default_when_no_venv(tmp_path: Path) -> None:
    assert de.resolve_demucs_cmd(None, tmp_path) == "python -m demucs"


def test_demucs_available_true_for_exit_zero(tmp_path: Path) -> None:
    stub = tmp_path / "stub.py"
    stub.write_text("import sys; sys.exit(0)", encoding="utf-8")
    cmd = f'"{sys.executable}" "{stub}"'
    assert de.demucs_available(cmd) is True


def test_demucs_available_false_for_missing_binary() -> None:
    assert de.demucs_available("definitely-not-a-real-binary-xyz") is False
