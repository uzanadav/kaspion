# kaspion one-time setup — Windows.
# Run:  double-click scripts\setup.bat   (or)   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Safe to re-run anytime — leaves an EMPTY database. Add -Demo to load 341 rows of
# synthetic sample data instead: powershell ... -File scripts\setup.ps1 -Demo
# No AI model needed — the low-resource path is the default here.
param([switch]$Demo)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONUTF8 = "1"

function Step($m) { Write-Host "`n==> $m" }
function Ok($m)   { Write-Host "    [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    [!]  $m" -ForegroundColor Yellow }

Write-Host "kaspion setup (Windows) - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

Step "checking Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python not found. Install 3.10+ from https://python.org and tick 'Add python.exe to PATH'." }
$ver = & $py.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$ver -lt [version]"3.10") { throw "Python $ver found - need 3.10+" }
Ok "python $ver"

Step "creating virtual environment (.venv)"
# a .venv copied from another machine keeps the folder but loses python.exe
if ((Test-Path .venv) -and -not (Test-Path ".venv\Scripts\python.exe")) {
  Warn "existing .venv has no usable python - recreating"
  Remove-Item -Recurse -Force .venv
}
if (-not (Test-Path .venv)) { & $py.Source -m venv .venv; Ok "created" } else { Ok "already exists - reusing" }
$venvPy = Join-Path (Resolve-Path ".venv") "Scripts\python.exe"
# put the venv's tools (dbt.exe) on PATH for this session
$env:Path = (Join-Path (Resolve-Path ".venv") "Scripts") + ";" + $env:Path

Step "installing dependencies (duckdb, dbt-duckdb, pandas...)"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -e .
Ok "installed"

if ($Demo) {
  Step "generating sample data + running the full pipeline (-Demo)"
  & $venvPy kaspion/ingest/generate_seed.py
  & $venvPy sync.py --source seed --provider none
  Ok "pipeline green with sample data loaded"
} else {
  Step "preparing an empty database (dbt build + all tests -> dashboard)"
  & $venvPy -m kaspion.cli init
  Ok "pipeline green - database is empty, ready for a real account"
}

Write-Host ""
Write-Host "setup complete." -ForegroundColor Green
Write-Host "next steps:"
Write-Host "  .venv\Scripts\python.exe -m kaspion.serve     # dashboard at http://127.0.0.1:8765"
Write-Host "  (this PC needs no AI: built-in merchant rules categorize the common stuff,"
Write-Host "   and anything else is a one-click fix in the dashboard - remembered forever)"
