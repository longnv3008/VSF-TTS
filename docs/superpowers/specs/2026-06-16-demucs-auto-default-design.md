# Demucs auto-default — design spec

Date: 2026-06-16
Status: approved (design), pending implementation plan

## Goal

Make Demucs vocal separation the **default** behavior on both pipeline paths
(local `end_to_end_pipeline.py` and crawl `run_vsf_github_to_labels.py`),
instead of the current opt-in `--demucs` flag, **without ever breaking the
pipeline** when Demucs/torch is not available.

## Decisions (from brainstorming)

- **Auto + graceful fallback**: default on. If Demucs cannot run (no torch env,
  bad cmd), log a warning and fall back to `raw -> clean -> VAD` (old behavior).
  Pipeline never crashes due to a missing Demucs env.
- **Convention venv for the torch env**: auto-resolve the Demucs command to a
  project-local `.venv-demucs` so the user does not pass `--demucs-cmd` every
  run.
- **Scope: both paths** (local + crawl), behavior kept in sync.

## Architecture

### New shared helper: `scripts/demucs_env.py`

Single source of truth for command resolution and availability probing.
Imported by both `end_to_end_pipeline.py` and `run_vsf_github_to_labels.py`.

```python
def resolve_demucs_cmd(explicit: str | None, root: Path) -> str: ...
def demucs_available(cmd: str) -> bool: ...
```

#### `resolve_demucs_cmd(explicit, root)`

Resolution order:
1. `explicit` is set (user passed `--demucs-cmd`) -> return it unchanged.
2. `.venv-demucs/Scripts/python.exe` (Windows) or `.venv-demucs/bin/python`
   (POSIX) exists under `root` -> return `'"<python>" -m demucs'`.
3. Otherwise -> return `"python -m demucs"`.

To distinguish "user passed" from "auto", the argparse default for
`--demucs-cmd` changes from `"python -m demucs"` to `None`; the script calls
`resolve_demucs_cmd(args.demucs_cmd, PROJECT_ROOT)`.

#### `demucs_available(cmd)`

Run `[*split_command(cmd), "-h"]` capturing output; return `True` iff exit
code 0. Runs **once per pipeline run**. Any exception (FileNotFoundError,
non-zero exit, import failure inside demucs) -> `False`.

The existing `split_command` (Windows-aware, `posix=False` + quote strip) moves
into / is shared by this helper so both scripts split identically.

### Default-on + disable flag

In both `end_to_end_pipeline.py` and `run_vsf_github_to_labels.py`:

- Replace `--demucs` (`store_true`, default `False`) with
  `--demucs` / `--no-demucs` via `argparse.BooleanOptionalAction`,
  **default `True`**.
- Run-level gate:
  - `--no-demucs` -> Demucs off (skip probe), run raw -> clean -> VAD.
  - default (on) + `demucs_available()` True -> separate vocals.
  - default (on) + `demucs_available()` False -> log warning, set demucs off for
    the whole run, run raw -> clean -> VAD (old behavior; no crash).

### Per-file fallback (after probe passes)

A passing probe does not guarantee every file separates. On a per-file failure
the pipeline still must not break.

- **Local** (`separate_vocals` in `end_to_end_pipeline.py`): wrap each file's
  Demucs call in try/except. On failure -> log warning, **omit that file from
  `vocal_map`**. `clean_audio_files` already falls back to `src` (raw) when the
  file is absent from `vocal_map`, so that file is cleaned from raw. No raise.
- **Crawl** (`separate_vocals` in the repo's `demucs_separator.py`): wrap the
  `subprocess.run(..., check=True)` per-file in try/except. On failure -> log
  warning and **return `input_path` (raw)**. The workflow node already overrides
  `raw_file_path` with the returned path, so `normalize_audio` proceeds on raw.

### Wrapper coordination (`run_vsf_github_to_labels.py`)

The wrapper is the top entry that forwards to both the repo crawl helper and the
local `end_to_end_pipeline.py`.

- Probe once via the shared helper.
- The wrapper is the **single decision authority**; because the child
  `end_to_end_pipeline.py` now defaults Demucs ON and runs its own probe, the
  wrapper must forward an **explicit** on/off so the child never re-decides.
- Probe pass -> forward `--demucs` + the resolved `--demucs-cmd` (absolute,
  convention-resolved) to `run_local_vad`; and `--demucs-enabled` + cmd to
  `run_github_pipeline`.
- Probe fail -> forward `--no-demucs` to `run_local_vad`; pass nothing
  Demucs-related to `run_github_pipeline` (repo crawl helper stays off by
  default). Both sub-paths run on raw.
- `--no-demucs` on the wrapper -> same as probe-fail forwarding, skip probe.

Forwarding the **already-resolved** cmd means the child `end_to_end_pipeline.py`
treats it as explicit and does not re-resolve, avoiding double work / mismatch.

## Data flow (default, Demucs available)

```text
Local:  raw -> demucs(raw, native SR) -> vocal stem
            -> clean(vocal -> mono 16k) -> VAD -> segments -> labels

Crawl:  crawl -> demucs(raw) -> normalize(vocal -> 16k)
            -> build_translations -> build_metadata -> (handoff) local VAD/label
```

When Demucs unavailable -> the `demucs(...)` step is skipped end-to-end and the
old raw path runs.

## Error handling summary

| Situation | Behavior |
|---|---|
| `--no-demucs` | Demucs off, no probe, raw path |
| Demucs cmd missing / probe fail | warn, run-level off, raw path |
| One file fails mid-separation | warn, that file uses raw, run continues |
| Demucs produces no `vocals.wav` | treated as per-file failure -> raw |

## Testing

New / updated tests (stubbed, no torch/ffmpeg required):

- `resolve_demucs_cmd`: 3 branches — explicit passthrough; `.venv-demucs`
  present (tmp dir with fake python file); default `"python -m demucs"`.
- `demucs_available`: stub cmd returning exit 0 -> True; missing cmd / exit 1
  -> False.
- Run-level fallback: probe fail -> pipeline runs raw path, segment count equals
  the pre-Demucs baseline (no regression).
- Per-file fallback: one stubbed file fails -> that file cleaned from raw, run
  does not crash, other files still separated.
- Wrapper: probe fail -> Demucs flag not forwarded to either sub-path; probe
  pass -> resolved absolute `--demucs-cmd` forwarded to both.

Existing suites must stay green: VAD (91) and backend (38).

## Docs

Update `PIPELINE.md`:
- Demucs is now **on by default**; disable with `--no-demucs`.
- `.venv-demucs` convention (auto-resolved cmd); how to create it
  (`requirements-demucs.txt`).
- Fallback behavior: missing env -> warn + raw path, never crashes.

## Out of scope (YAGNI)

- No `separated` boolean column in the manifest (no raw-vs-vocal tracking) unless
  later requested.
- No auto-creation of `.venv-demucs` / auto torch install.
- No GPU auto-detection (`--demucs-device` stays manual; default `cpu`).

## Notes

- Repo is not under git (`Is a git repository: false`); the "commit the design
  doc" brainstorming step is recorded here but cannot be performed.
