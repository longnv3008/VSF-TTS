# Demucs Auto-Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Demucs vocal separation the default on both pipeline paths (local + crawl), auto-resolving a torch env and silently falling back to raw audio when Demucs is unavailable, so the pipeline never breaks.

**Architecture:** A new shared helper `scripts/demucs_env.py` owns command resolution (`.venv-demucs` convention) and an availability probe. Both entry scripts default Demucs ON, probe once per run, and fall back to the raw `raw → clean → VAD` path on failure. Per-file failures (after the probe passes) also fall back to raw instead of aborting.

**Tech Stack:** Python 3.12 (local scripts) / 3.11 (backend repo), argparse `BooleanOptionalAction`, subprocess, pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-demucs-auto-default-design.md`

---

## Notes before starting

- **This repo is NOT under git.** Every "Commit" step below is therefore a no-op — skip it, or run `git init` first if you want commit checkpoints. Do not let a missing `git` block progress.
- **Running VAD tests** (local `scripts/` + `VAD/`): from the project root
  `python -m pytest VAD/tests/<file> -v`.
- **Running backend repo tests** (Windows): the committed `.venv` is Linux-only.
  Use an isolated temp env (see the `run-backend-tests-windows` memory):
  ```powershell
  $env:UV_PROJECT_ENVIRONMENT = "$env:TEMP\vsf-backend-venv"
  uv run --directory external_repos/VSF-audio-pipeline/backend pytest tests/<file> -v
  ```

## File Structure

- **Create** `scripts/demucs_env.py` — shared: `split_command`, `resolve_demucs_cmd`, `demucs_available`. One responsibility: decide *which* Demucs command and *whether* it runs.
- **Modify** `scripts/end_to_end_pipeline.py` — default Demucs ON, resolve+probe via the helper, per-file fallback in `separate_vocals`.
- **Modify** `scripts/run_vsf_github_to_labels.py` — default Demucs ON, probe once, forward an explicit on/off to both sub-paths.
- **Modify** `external_repos/VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/pipeline_service.py` — per-file graceful fallback in `separate_vocals` (use raw instead of aborting the batch).
- **Create** `VAD/tests/test_demucs_env.py` — unit tests for the helper.
- **Create** `VAD/tests/test_end_to_end_demucs_fallback.py` — local probe + per-file fallback.
- **Create** `VAD/tests/test_wrapper_demucs_forwarding.py` — wrapper decision + flag forwarding.
- **Modify** `external_repos/VSF-audio-pipeline/backend/tests/test_vocal_separation.py` — add crawl-path per-file fallback test.
- **Modify** `PIPELINE.md` — document on-by-default + `--no-demucs` + `.venv-demucs` convention + fallback.

---

## Task 1: Shared helper `scripts/demucs_env.py`

**Files:**
- Create: `scripts/demucs_env.py`
- Test: `VAD/tests/test_demucs_env.py`

- [ ] **Step 1: Write the failing test**

Create `VAD/tests/test_demucs_env.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest VAD/tests/test_demucs_env.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'demucs_env'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/demucs_env.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest VAD/tests/test_demucs_env.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 5: Commit** (skip — repo not under git)

```bash
git add scripts/demucs_env.py VAD/tests/test_demucs_env.py
git commit -m "feat(demucs): add shared cmd resolution + availability probe"
```

---

## Task 2: Local pipeline — default ON + resolve/probe

**Files:**
- Modify: `scripts/end_to_end_pipeline.py`
- Test: `VAD/tests/test_end_to_end_demucs_fallback.py`

- [ ] **Step 1: Write the failing test**

Create `VAD/tests/test_end_to_end_demucs_fallback.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest VAD/tests/test_end_to_end_demucs_fallback.py -v`
Expected: FAIL — `AttributeError: module 'end_to_end_pipeline' has no attribute 'resolve_and_probe_demucs'` (and the per-file test errors because the current `separate_vocals` raises instead of skipping).

- [ ] **Step 3: Add the import + helper**

In `scripts/end_to_end_pipeline.py`, replace the local `split_command` definition (the `def split_command(command: str) -> list[str]:` block, ~lines 110-119) with an import near the top imports (after `from batch_vad import ...`):

```python
from demucs_env import demucs_available, resolve_demucs_cmd, split_command  # noqa: E402,F401
```

Then add this helper just above `def main()`:

```python
def resolve_and_probe_demucs(args: argparse.Namespace) -> None:
    """Resolve the Demucs command and probe once. Disable on unavailable.

    Keeps the run-level "auto on, fall back to raw" decision in one place. After
    this returns, ``args.demucs_cmd`` is the resolved command and ``args.demucs``
    reflects whether separation will actually run.
    """
    if not args.demucs:
        return
    args.demucs_cmd = resolve_demucs_cmd(args.demucs_cmd, PROJECT_ROOT)
    if not demucs_available(args.demucs_cmd):
        _print(f"[demucs] unavailable ({args.demucs_cmd}); falling back to raw audio")
        args.demucs = False
```

- [ ] **Step 4: Flip the CLI defaults**

In `parse_args`, change the Demucs flag and command default:

Replace:
```python
    parser.add_argument(
        "--demucs",
        action="store_true",
        help="Separate vocals with Demucs before clean/VAD (vocal-only segments).",
    )
    parser.add_argument(
        "--demucs-cmd",
        default="python -m demucs",
        help="Demucs command; point at a torch-enabled env if separate from this one.",
    )
```
With:
```python
    parser.add_argument(
        "--demucs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Separate vocals with Demucs before clean/VAD (on by default; --no-demucs to skip).",
    )
    parser.add_argument(
        "--demucs-cmd",
        default=None,
        help="Demucs command. Default: auto-resolve .venv-demucs, else 'python -m demucs'.",
    )
```

- [ ] **Step 5: Wire the helper into `main()`**

Replace the Demucs block in `main()`:
```python
    vocal_map = None
    if args.demucs:
        vocal_map = separate_vocals(collect_audio_files(args.raw_dir), args)
```
With:
```python
    resolve_and_probe_demucs(args)
    vocal_map = separate_vocals(collect_audio_files(args.raw_dir), args) if args.demucs else None
```

- [ ] **Step 6: Make `separate_vocals` fall back per file**

In `separate_vocals`, replace the run + existence check:
```python
        subprocess.run(cmd, check=True)
        if not vocal.exists():
            raise FileNotFoundError(f"demucs did not produce vocals: {vocal}")
        vocal_map[src] = vocal
        _print(f"[demucs] separated: {src.name} -> {vocal.name}")
```
With:
```python
        try:
            subprocess.run(cmd, check=True)
            if not vocal.exists():
                raise FileNotFoundError(f"demucs did not produce vocals: {vocal}")
        except Exception as exc:  # per-file fallback: clean step uses raw for this file
            _print(f"[demucs] FAILED on {src.name}: {exc}; using raw audio for this file")
            continue
        vocal_map[src] = vocal
        _print(f"[demucs] separated: {src.name} -> {vocal.name}")
```

- [ ] **Step 7: Run the new test to verify it passes**

Run: `python -m pytest VAD/tests/test_end_to_end_demucs_fallback.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 8: Run the existing Demucs test for no regression**

Run: `python -m pytest VAD/tests/test_end_to_end_demucs.py -v`
Expected: PASS — 3 passed (existing happy-path wiring unchanged).

- [ ] **Step 9: Commit** (skip — repo not under git)

```bash
git add scripts/end_to_end_pipeline.py VAD/tests/test_end_to_end_demucs_fallback.py
git commit -m "feat(demucs): default-on + probe + per-file fallback in local pipeline"
```

---

## Task 3: Wrapper — default ON + decide once + explicit forwarding

**Files:**
- Modify: `scripts/run_vsf_github_to_labels.py`
- Test: `VAD/tests/test_wrapper_demucs_forwarding.py`

- [ ] **Step 1: Write the failing test**

Create `VAD/tests/test_wrapper_demucs_forwarding.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest VAD/tests/test_wrapper_demucs_forwarding.py -v`
Expected: FAIL — `AttributeError: module 'run_vsf_github_to_labels' has no attribute 'resolve_and_probe_demucs'` / `demucs_available`, and the `--no-demucs` parse fails (flag not defined yet).

- [ ] **Step 3: Add the helper import + decision function**

In `scripts/run_vsf_github_to_labels.py`, after the existing imports add:

```python
from demucs_env import demucs_available, resolve_demucs_cmd  # noqa: E402
```

The script already defines `PROJECT_ROOT = Path(__file__).resolve().parents[1]`, and `scripts/` is on `sys.path` when run directly. (If import resolution is a concern when invoked oddly, add `sys.path.insert(0, str(Path(__file__).resolve().parent))` above the import.)

Add the decision helper above `parse_args`:

```python
def resolve_and_probe_demucs(args: argparse.Namespace) -> None:
    """Resolve the Demucs command and probe once; disable on unavailable.

    The wrapper is the single decision authority: the child end_to_end_pipeline.py
    now defaults Demucs ON, so the wrapper must forward an explicit on/off so the
    child never re-decides.
    """
    if not args.demucs:
        return
    args.demucs_cmd = resolve_demucs_cmd(args.demucs_cmd, PROJECT_ROOT)
    if not demucs_available(args.demucs_cmd):
        print(f"[demucs] unavailable ({args.demucs_cmd}); falling back to raw audio", flush=True)
        args.demucs = False
```

- [ ] **Step 4: Flip the CLI defaults**

Replace:
```python
    parser.add_argument("--demucs", action="store_true", help="Separate vocals with Demucs before VAD.")
    parser.add_argument("--demucs-cmd", default="python -m demucs")
```
With:
```python
    parser.add_argument(
        "--demucs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Separate vocals with Demucs before VAD (on by default; --no-demucs to skip).",
    )
    parser.add_argument("--demucs-cmd", default=None)
```

- [ ] **Step 5: Call the decision in `main()`**

In `main()`, immediately after `args.work_dir.mkdir(parents=True, exist_ok=True)`, add:
```python
    resolve_and_probe_demucs(args)
```

- [ ] **Step 6: Forward an explicit on/off in `run_local_vad`**

Replace:
```python
    if args.demucs:
        cmd.append("--demucs")
        cmd.extend(["--demucs-cmd", args.demucs_cmd])
        cmd.extend(["--demucs-model", args.demucs_model])
        cmd.extend(["--demucs-device", args.demucs_device])
    run_command(cmd, cwd=PROJECT_ROOT)
```
With:
```python
    if args.demucs:
        cmd.append("--demucs")
        cmd.extend(["--demucs-cmd", args.demucs_cmd])
        cmd.extend(["--demucs-model", args.demucs_model])
        cmd.extend(["--demucs-device", args.demucs_device])
    else:
        cmd.append("--no-demucs")
    run_command(cmd, cwd=PROJECT_ROOT)
```

(`run_github_pipeline` already passes nothing Demucs-related when `args.demucs` is false, which the repo treats as off — no change needed there beyond the resolved `args.demucs_cmd` it already forwards.)

- [ ] **Step 7: Run the test to verify it passes**

Run: `python -m pytest VAD/tests/test_wrapper_demucs_forwarding.py -v`
Expected: PASS — 6 passed.

- [ ] **Step 8: Commit** (skip — repo not under git)

```bash
git add scripts/run_vsf_github_to_labels.py VAD/tests/test_wrapper_demucs_forwarding.py
git commit -m "feat(demucs): default-on + single-authority decision in wrapper"
```

---

## Task 4: Crawl path — per-file graceful fallback in the repo

**Files:**
- Modify: `external_repos/VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/pipeline_service.py:1298-1341`
- Test: `external_repos/VSF-audio-pipeline/backend/tests/test_vocal_separation.py`

- [ ] **Step 1: Write the failing test**

Append to `external_repos/VSF-audio-pipeline/backend/tests/test_vocal_separation.py`:

```python
def test_separate_vocals_falls_back_to_raw_on_failure(make_wav, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demucs_enabled", True)
    service = AudioPipelineService()

    raw = make_wav(seconds=0.5, name="raw.wav")

    def boom(input_path, out_dir, *, command, model, device):
        raise RuntimeError("no torch")

    monkeypatch.setattr(pipeline_service, "demucs_separate_vocals", boom)

    rows = [{"raw_file_path": str(raw), "source_url": "u", "video_id": "v"}]
    out = service.separate_vocals(rows)

    assert out[0]["raw_file_path"] == str(raw)        # fell back to raw, not aborted
    assert "original_raw_file_path" not in out[0]
    assert raw.exists()                                # raw NOT deleted on failure
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:TEMP\vsf-backend-venv"
uv run --directory external_repos/VSF-audio-pipeline/backend pytest tests/test_vocal_separation.py -v
```
Expected: FAIL — the current code raises `BatchAbortError` instead of returning the raw row.

- [ ] **Step 3: Replace the loop body with graceful fallback**

In `pipeline_service.py`, replace the body from `outputs: list[...]` through `return outputs` (lines ~1298-1341):

```python
        outputs: list[dict[str, str]] = []
        for row in source_rows:
            current_url = row.get("source_url", "")
            raw_path = row.get("raw_file_path", "")
            raw_file = Path(raw_path)
            if not raw_file.exists() or not raw_file.is_file():
                logger.warning("step=vocal_separation | missing raw | url=%s", current_url)
                outputs.append(row)
                continue
            try:
                vocal = demucs_separate_vocals(
                    raw_file,
                    self.separated_dir,
                    command=settings.demucs_command,
                    model=settings.demucs_model,
                    device=settings.demucs_device,
                )
            except Exception as exc:
                # Per-file fallback: keep raw so normalize/segment still run; never abort batch.
                logger.warning(
                    "step=vocal_separation | url=%s | demucs failed, using raw | error=%s",
                    current_url,
                    format_function_error("separate_vocals", exc),
                )
                outputs.append(row)
                continue

            # Trỏ raw_file_path sang vocal stem để normalize_audio hạ 16k vocal.
            # Xóa raw gốc cho tiết kiệm disk (Demucs đã dùng xong).
            raw_file.unlink(missing_ok=True)
            new_row = dict(row)
            new_row["original_raw_file_path"] = raw_path
            new_row["raw_file_path"] = str(vocal)
            outputs.append(new_row)
            logger.info("step=vocal_separation | url=%s | vocal=%s", current_url, vocal)
        return outputs
```

This removes the now-unused `enumerate` index and `remaining_urls` computation (they existed only to build `BatchAbortError`). `BatchAbortError` remains imported and used elsewhere (e.g. `crawl_youtube`), so leave the import.

- [ ] **Step 4: Run the test to verify it passes**

Run:
```powershell
uv run --directory external_repos/VSF-audio-pipeline/backend pytest tests/test_vocal_separation.py -v
```
Expected: PASS — 3 passed (2 existing + 1 new).

- [ ] **Step 5: Commit** (skip — repo not under git)

```bash
git add external_repos/VSF-audio-pipeline/backend/app/modules/audio_pipeline/application/pipeline_service.py \
        external_repos/VSF-audio-pipeline/backend/tests/test_vocal_separation.py
git commit -m "feat(demucs): per-file graceful fallback to raw in crawl path"
```

---

## Task 5: Docs — `PIPELINE.md`

**Files:**
- Modify: `PIPELINE.md`

- [ ] **Step 1: Update the Demucs section**

Replace the "Optional Demucs vocal separation" section heading and its first/last paragraphs so it reads on-by-default. Specifically:

- Change the heading `## Optional Demucs vocal separation` to `## Demucs vocal separation (on by default)`.
- Replace the opening sentence so it states Demucs runs by default and is auto-resolved:

```text
By default the pipeline runs [Demucs](https://github.com/facebookresearch/demucs)
to separate **vocals** from background music *before* clean/VAD. The Demucs
command is auto-resolved: a project-local `.venv-demucs` is used if present,
otherwise `python -m demucs`. If Demucs cannot run (no torch env), the pipeline
logs a warning and falls back to the raw `raw -> clean -> VAD` path. Disable
entirely with `--no-demucs`.
```

- Replace the closing paragraph (currently "Demucs is **off by default**; without `--demucs` ...") with:

```text
Demucs is **on by default**. Per-file failures fall back to raw for that file;
a missing/broken Demucs env falls back to raw for the whole run. Use
`--no-demucs` to skip separation, or `--demucs-cmd` to point at a specific env.
Vocal stems land in `<work-dir>/vocals/`.
```

- In the "Full GitHub crawler" section, replace the `Add --demucs to separate vocals ...` paragraph with:

```text
Demucs runs by default on the crawl path too (auto-resolved `.venv-demucs`, with
raw fallback when unavailable). Use `--no-demucs` to skip it. `--demucs-cmd/
--demucs-model/--demucs-device` still apply.
```

- [ ] **Step 2: Verify the doc reads correctly**

Run: `python -m pytest VAD/tests -q` (sanity — docs change touches no tests; ensure suite still green).
Expected: PASS.

- [ ] **Step 3: Commit** (skip — repo not under git)

```bash
git add PIPELINE.md
git commit -m "docs(demucs): document on-by-default + fallback + .venv-demucs"
```

---

## Task 6: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full VAD suite**

Run: `python -m pytest VAD/tests -q`
Expected: PASS — previous 91 + new tests (≈ 91 + 15) all green, 0 failures.

- [ ] **Step 2: Run the full backend suite**

Run:
```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:TEMP\vsf-backend-venv"
uv run --directory external_repos/VSF-audio-pipeline/backend pytest -q
```
Expected: PASS — previous 38 + 1 new fallback test all green, 0 failures.

- [ ] **Step 3: Smoke-check the local CLI help**

Run: `python scripts/end_to_end_pipeline.py --help`
Expected: shows `--demucs, --no-demucs` (BooleanOptionalAction) and `--demucs-cmd` with no default value in the help text.

---

## Self-Review (done while writing)

- **Spec coverage:** auto+fallback (Tasks 2,3,4); `.venv-demucs` convention (Task 1); both paths (Tasks 2,3,4); wrapper single-authority explicit forwarding (Task 3); docs (Task 5); tests for resolve/probe/run-level/per-file/wrapper (Tasks 1-4). All spec sections mapped.
- **Refinement vs spec:** the spec named `demucs_separator.py` as the crawl-path fallback seam; the actual try/except already lives one layer up in `pipeline_service.separate_vocals`, so Task 4 changes that seam instead (same effect, smaller diff, `demucs_separator.py` left raising).
- **Type/name consistency:** helper functions `split_command` / `resolve_demucs_cmd` / `demucs_available` and the per-script `resolve_and_probe_demucs(args)` are named identically wherever referenced.
- **No placeholders:** every code/test step contains full code and exact run commands.
