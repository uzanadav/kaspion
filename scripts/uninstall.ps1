# kaspion uninstaller — Windows. Launched by uninstall.bat (double-click that, not this).
#
# Console text is English for the same reason the installer's is: terminals render Hebrew
# left-to-right, so the words come out reversed.
#
# Your financial data is NEVER removed unless you explicitly type DELETE. Everything else
# here is reversible by running install again.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$app  = $PWD.Path
$data = Join-Path $env:LOCALAPPDATA "kaspion"

Write-Host ""
Write-Host "kaspion uninstaller"
Write-Host "==================="
Write-Host ""
Write-Host "  App folder : $app"
Write-Host "  Data folder: $data"
if (Test-Path $data) {
  $mb = [math]::Round((Get-ChildItem $data -Recurse -File -ErrorAction SilentlyContinue |
                       Measure-Object Length -Sum).Sum / 1MB, 1)
  Write-Host "               ($mb MB - your transactions and bank logins)"
} else {
  Write-Host "               (not present)"
}
Write-Host ""

# ---------- 1. the kaspion:// handler ----------
# Removed before the app folder goes away, or Windows keeps a dead entry pointing at a
# path that no longer exists.
if (Test-Path "HKCU:\Software\Classes\kaspion") {
  Write-Host "Removing the kaspion:// handler..."
  Remove-Item -Recurse -Force "HKCU:\Software\Classes\kaspion" -ErrorAction SilentlyContinue
}

# ---------- 2. the data folder, only on an explicit request ----------
# A y/n prompt is too easy to answer by reflex for something with no undo, so this asks
# for a word. Anything else - including a bare Enter - keeps the data.
if (Test-Path $data) {
  Write-Host ""
  Write-Host "Do you also want to DELETE your financial data?"
  Write-Host "  - This erases every transaction, budget and saved bank login."
  Write-Host "  - It CANNOT be undone. Back up finance.duckdb first if unsure."
  Write-Host "  - Keeping it means a future re-install picks up where you left off."
  Write-Host ""
  $answer = Read-Host 'Type DELETE to erase it, or press Enter to KEEP it'
  # .Trim() matches bash's `read`, which drops surrounding whitespace, so both platforms
  # behave identically. -ceq keeps it case-SENSITIVE: "delete" must not erase anything.
  if ($answer.Trim() -ceq "DELETE") {
    Remove-Item -Recurse -Force $data
    Write-Host "Data folder removed."
  } else {
    Write-Host "Data KEPT at: $data"
  }
}

# ---------- 3. the app folder ----------
# Not deleted from here: this script lives inside it and is currently running.
Write-Host ""
Write-Host "Almost done. One last step you have to do yourself:"
Write-Host ""
Write-Host "  Delete this folder:"
Write-Host "  $app"
Write-Host ""
Write-Host "That removes kaspion's own Python, Node and browser - nothing was ever"
Write-Host "installed anywhere else on this PC, and no administrator rights were used."
Write-Host ""
Read-Host "Press Enter to close" | Out-Null
