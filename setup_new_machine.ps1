<#
.SYNOPSIS
  Bootstrap the VSF-TTS E2E pipeline on a fresh Windows machine.

.DESCRIPTION
  Builds the isolated venvs and syncs the crawler backend env. Idempotent:
  re-running skips venvs that already exist.

  Steps:
    1. Check prereqs (Python 3.12, ffmpeg, git, uv).
    2. Sanity-check the in-repo crawler folder (VSF-audio-pipeline).
    3. .venv-vad        <- VAD/requirements.txt
    4. .venv-demucs     <- requirements-demucs.txt           (Demucs CPU)
    5. .venv-demucs-cu128 <- requirements-demucs-cu128.txt   (only with -Gpu; needs CUDA 12.8)
    6. uv sync the crawler backend env
    7. Remind about manual secrets (.env, cookies) not in git
    8. -Smoke: run the offline smoke test

.PARAMETER Gpu
  Also build .venv-demucs-cu128 (Demucs on NVIDIA GPU, CUDA 12.8).

.PARAMETER Smoke
  Run the offline smoke test after setup.

.EXAMPLE
  .\setup_new_machine.ps1
  .\setup_new_machine.ps1 -Gpu -Smoke
#>
[CmdletBinding()]
param(
    [switch]$Gpu,
    [switch]$Smoke
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Info($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[setup] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[setup] ERROR: $m" -ForegroundColor Red; exit 1 }

function Test-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# 1. Prereqs ----------------------------------------------------------------
Info "Checking prerequisites..."

if (-not (Test-Cmd python)) { Die "python not found. Install Python 3.12 and add to PATH." }
$pyVer = (python --version 2>&1).ToString().Trim()
if ($pyVer -notmatch '3\.12') {
    Warn "$pyVer detected; project targets 3.12 (.python-version). Continuing, but mismatches may cause issues."
} else {
    Info "$pyVer OK"
}

if (-not (Test-Cmd ffmpeg)) { Die "ffmpeg not found in PATH. Install ffmpeg (audio clean + crawl need it)." }
Info "ffmpeg OK"

if (-not (Test-Cmd git)) { Die "git not found." }
if (-not (Test-Cmd uv))  { Die "uv not found. Install: https://docs.astral.sh/uv/ (crawler backend uses uv)." }
Info "git + uv OK"

# 2. Crawler folder (in-repo) ----------------------------------------------
Info "Checking in-repo crawler folder (VSF-audio-pipeline)..."
if (-not (Test-Path "VSF-audio-pipeline/backend/pyproject.toml")) {
    Die "VSF-audio-pipeline/backend missing. Repo clone incomplete?"
}

# 3-5. venvs ----------------------------------------------------------------
function New-Venv($dir, $reqFile) {
    if (Test-Path $dir) {
        Info "$dir already exists - skipping (delete it to rebuild)."
        return
    }
    if (-not (Test-Path $reqFile)) { Die "Requirements file not found: $reqFile" }
    Info "Creating $dir from $reqFile ..."
    python -m venv $dir
    & "$dir/Scripts/python.exe" -m pip install --upgrade pip
    & "$dir/Scripts/pip.exe" install -r $reqFile
    Info "$dir done."
}

New-Venv ".venv-vad"    "VAD/requirements.txt"
New-Venv ".venv-demucs" "requirements-demucs.txt"

if ($Gpu) {
    New-Venv ".venv-demucs-cu128" "requirements-demucs-cu128.txt"
} else {
    Info "Skipping GPU env (.venv-demucs-cu128). Pass -Gpu to build it (needs CUDA 12.8)."
}

# 6. Crawler backend env ----------------------------------------------------
Info "Syncing crawler backend env (uv)..."
uv sync --project VSF-audio-pipeline/backend

# 7. Manual secrets reminder ------------------------------------------------
Warn "Manual steps (NOT in git):"
Warn "  - Copy VSF-audio-pipeline/.env.example -> .env and fill secrets."
Warn "  - Place YouTube cookies at VSF-audio-pipeline/cookies/youtube.txt (for crawl)."

# 8. Smoke test -------------------------------------------------------------
if ($Smoke) {
    if (-not (Test-Path "tmp")) {
        Warn "No tmp/ audio folder found - skipping smoke test. Put WAVs in tmp/ and run with -Smoke."
    } else {
        Info "Running offline smoke test (--skip-crawl on tmp/)..."
        & ".venv-vad/Scripts/python.exe" scripts/run_vsf_github_to_labels.py `
            --skip-crawl `
            --processed-audio-dir tmp `
            --work-dir pipeline_runs/smoke `
            --refine-boundaries `
            --overwrite
        if (Test-Path "pipeline_runs/smoke/vad_labels/labels.csv") {
            Info "Smoke test PASS: pipeline_runs/smoke/vad_labels/labels.csv generated."
        } else {
            Die "Smoke test ran but labels.csv missing - check output above."
        }
    }
}

Info "Setup complete."
