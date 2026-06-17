"""Demucs command resolution + availability probing.

Shared by scripts/end_to_end_pipeline.py and scripts/run_vsf_github_to_labels.py
so both resolve the Demucs command and probe availability identically. Keeps the
auto-default ("Demucs on; fall back to raw if unavailable") logic in one place.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def split_command(command: str) -> list[str]:
    """Split a command string into argv, tolerating Windows paths with spaces.

    On Windows ``shlex.split`` default (POSIX) eats backslashes; use posix=False
    and strip wrapping quotes so ``"C:\\venv\\python.exe" -m demucs`` becomes a
    usable argv list.
    """
    if os.name == "nt":
        return [tok.strip('"') for tok in shlex.split(command, posix=False)]
    return shlex.split(command)


def _venv_python(root: Path) -> Path | None:
    """Return the project-local .venv-demucs python if present, else None."""
    candidates = [
        root / ".venv-demucs" / "Scripts" / "python.exe",  # Windows
        root / ".venv-demucs" / "bin" / "python",          # POSIX
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def resolve_demucs_cmd(explicit: str | None, root: Path) -> str:
    """Resolve the Demucs command.

    Order: explicit (user ``--demucs-cmd``) > project-local ``.venv-demucs`` >
    ``"python -m demucs"`` fallback.
    """
    if explicit:
        return explicit
    venv_py = _venv_python(root)
    if venv_py is not None:
        return f'"{venv_py}" -m demucs'
    return "python -m demucs"


def demucs_available(cmd: str, timeout: float = 120.0) -> bool:
    """Return True iff ``cmd -h`` runs and exits 0 (Demucs importable/runnable)."""
    try:
        proc = subprocess.run(
            [*split_command(cmd), "-h"],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0
