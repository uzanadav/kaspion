#!/usr/bin/env bash
# kaspion uninstaller — macOS. Double-click this file.
#
# Console text is English for the same reason the installer's is: terminals render
# Hebrew left-to-right, so the words come out reversed.
#
# Your financial data is NEVER removed unless you explicitly type DELETE. Everything
# else here is reversible by running install again.
set -euo pipefail
cd "$(dirname "$0")"

APP="$PWD"
DATA="$HOME/Library/Application Support/kaspion"

echo
echo "kaspion uninstaller"
echo "==================="
echo
echo "  App folder : $APP"
echo "  Data folder: $DATA"
if [ -d "$DATA" ]; then
  echo "               ($(du -sh "$DATA" 2>/dev/null | cut -f1) - your transactions and bank logins)"
else
  echo "               (not present)"
fi
echo

# ---------- 1. the kaspion:// handler ----------
# Unregistered before the app folder goes away, or macOS keeps a dead entry pointing at
# a path that no longer exists.
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
if [ -d "Kaspion.app" ]; then
  echo "Removing the kaspion:// handler..."
  [ -x "$LSREG" ] && "$LSREG" -u "$APP/Kaspion.app" >/dev/null 2>&1 || true
  rm -rf "Kaspion.app"
fi

# ---------- 2. the data folder, only on an explicit request ----------
# A y/n prompt is too easy to answer by reflex for something with no undo, so this asks
# for a word. Anything else - including a bare Enter - keeps the data.
if [ -d "$DATA" ]; then
  echo
  echo "Do you also want to DELETE your financial data?"
  echo "  - This erases every transaction, budget and saved bank login."
  echo "  - It CANNOT be undone. Back up finance.duckdb first if unsure."
  echo "  - Keeping it means a future re-install picks up right where you left off."
  echo
  read -r -p 'Type DELETE to erase it, or press Enter to KEEP it: ' answer
  if [ "$answer" = "DELETE" ]; then
    rm -rf "$DATA"
    echo "Data folder removed."
  else
    echo "Data KEPT at: $DATA"
  fi
fi

# ---------- 3. the app folder ----------
# Not deleted from here: this script lives inside it and is currently running.
echo
echo "Almost done. One last step you have to do yourself:"
echo
echo "  Move this folder to the Trash:"
echo "  $APP"
echo
echo "That removes kaspion's own Python, Node and browser - nothing was ever"
echo "installed anywhere else on this Mac, and no admin password was used."
echo
read -r -p "Press Enter to close"
