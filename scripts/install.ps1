# kaspion installer — Windows. Launched by install.bat (double-click that, not this).
#
# Everything lands inside the app folder (uv, Python, the libraries, the scraper), so
# uninstalling is deleting that folder plus the data folder printed at the end. Nothing
# is installed machine-wide and no administrator rights are needed.
#
# Safe to re-run: every step skips work already done, so an interrupted download just
# means running it again.
#
# NOTE: this file must keep its UTF-8 BOM. Windows PowerShell 5.1 — what `powershell`
# launches, and what most users have — reads a BOM-less .ps1 as ANSI, which mangles
# every Hebrew string here and fails to parse the script at all.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONUTF8 = "1"
# ...and the console has to be UTF-8 too, or the Hebrew parses correctly but prints
# as mojibake in the window the user is reading.
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

function Say($m) { Write-Host "`n$m" -ForegroundColor White }
# Keeps the window open for someone who double-clicked, but never blocks an automated
# run (CI has no stdin, and a Read-Host there would hang the job until it times out).
function Wait-ForUser {
  if (-not $env:CI) { Read-Host "`nהקישו Enter לסגירה" | Out-Null }
}
function Die($m) {
  Write-Host "`n[X] $m" -ForegroundColor Red
  Wait-ForUser
  exit 1
}

Write-Host "מתקין את כספיון - ייקח כ-10 דקות ויוריד כ-1.2GB. דרוש חיבור לאינטרנט."

$tools = Join-Path $PWD ".tools"
$uv    = Join-Path $tools "uv.exe"

# ---------- 1. uv, vendored into the app folder ----------
# uv brings its own Python, so Windows needs nothing preinstalled.
if (-not (Test-Path $uv)) {
  Say "[1/4] מוריד את מנהל ההתקנה..."
  try {
    $env:UV_INSTALL_DIR = $tools
    $env:UV_NO_MODIFY_PATH = "1"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  } catch { Die "הורדת מנהל ההתקנה נכשלה - בדקו את חיבור האינטרנט ונסו שוב" }
  if (-not (Test-Path $uv)) { Die "מנהל ההתקנה לא נמצא לאחר ההורדה" }
} else {
  Say "[1/4] מנהל ההתקנה כבר קיים - מדלג"
}

# ---------- 2. Python + libraries ----------
Say "[2/4] מתקין את Python והספריות..."
& $uv sync --frozen
if ($LASTEXITCODE -ne 0) { Die "התקנת הספריות נכשלה" }

# ---------- 3. the bank scraper ----------
# node/npm arrive as a Python dependency (nodejs-wheel) into .venv\Scripts; they only
# need to be on PATH for npm's own sake. This step also pulls Chromium (~600MB).
#
# PUPPETEER_CACHE_DIR keeps that browser inside the app folder instead of the shared
# per-user cache, which is what makes "uninstall = delete this folder" true, and stops a
# half-downloaded browser left by some other project from breaking this install.
Say "[3/4] מתקין את רכיב סריקת הבנקים (הורדה גדולה, נא להמתין)..."
$scripts = Join-Path $PWD ".venv\Scripts"
$puppeteerCache = Join-Path $PWD ".puppeteer"
$saved = $env:Path
$env:Path = "$scripts;$env:Path"
$env:PUPPETEER_CACHE_DIR = $puppeteerCache

function Install-Scraper {
  Push-Location scraper
  try {
    # bare npm/npx, resolved through the PATH set above: nodejs-wheel installs these
    # as console-script shims whose extension is pip/uv's business (.exe today), so
    # hardcoding one is how this broke the first time.
    & npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { return $false }
    # Fetch the browser explicitly instead of relying on puppeteer's postinstall hook:
    # npm 12 blocks install scripts by default, which would leave a "successful" install
    # with no browser and every scrape failing later. Idempotent — a no-op once present,
    # and with no arguments it installs exactly what puppeteer itself asks for.
    & npx puppeteer browsers install
    return ($LASTEXITCODE -eq 0)
  } finally { Pop-Location }
}

try {
  if (-not (Install-Scraper)) {
    # An interrupted download leaves the browser folder present but the executable
    # missing, and puppeteer then fails instead of re-fetching — so a plain re-run
    # would fail identically forever. Clearing the partial download fixes that.
    Say "ההורדה הופסקה באמצע - מנקה ומנסה שוב..."
    Remove-Item -Recurse -Force $puppeteerCache, "scraper\node_modules" -ErrorAction SilentlyContinue
    if (-not (Install-Scraper)) { Die "התקנת רכיב הסריקה נכשלה - בדקו את חיבור האינטרנט והריצו שוב את install" }
  }
} finally {
  $env:Path = $saved
}

# ---------- 4. an empty database ----------
Say "[4/4] יוצר בסיס נתונים ריק..."
& $uv run python -m kaspion.cli init
if ($LASTEXITCODE -ne 0) { Die "יצירת בסיס הנתונים נכשלה" }

Write-Host "`n[OK] ההתקנה הושלמה." -ForegroundColor Green
Write-Host "להפעלה - לחצו פעמיים על kaspion.bat"
Wait-ForUser
