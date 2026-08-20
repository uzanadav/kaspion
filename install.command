#!/usr/bin/env bash
# kaspion installer — macOS. Double-click this file.
#
# Everything lands inside this folder (uv, Python, the libraries, the scraper), so
# uninstalling is deleting this folder plus the data folder printed at the end.
# Nothing is installed system-wide and no admin password is needed.
#
# Safe to re-run: every step below skips work that is already done, so if the download
# is interrupted you can just double-click again.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
die() { printf '\n\033[31m✘ %s\033[0m\n' "$1"; echo; read -r -p "הקישו Enter לסגירה"; exit 1; }

echo "מתקין את כספיון — ייקח כ-10 דקות ויוריד כ-1.2GB. דרוש חיבור לאינטרנט."

# ---------- 1. uv, vendored into this folder ----------
# The official installer, pointed at ./.tools so it touches nothing else on the machine
# and never edits your shell PATH. uv brings its own Python, so no Python is required.
if [ ! -x ".tools/uv" ]; then
  say "[1/4] מוריד את מנהל ההתקנה…"
  curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR="$PWD/.tools" INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null \
    || die "הורדת מנהל ההתקנה נכשלה — בדקו את חיבור האינטרנט ונסו שוב"
else
  say "[1/4] מנהל ההתקנה כבר קיים — מדלג"
fi
UV="$PWD/.tools/uv"

# ---------- 2. Python + libraries ----------
say "[2/4] מתקין את Python והספריות…"
"$UV" sync --frozen || die "התקנת הספריות נכשלה"

# ---------- 3. the bank scraper ----------
# node/npm arrive as a Python dependency (nodejs-wheel) and live in .venv/bin, so they
# only need to be on PATH for npm's own sake. This step also pulls Chromium (~600MB).
#
# PUPPETEER_CACHE_DIR keeps that browser inside the app folder instead of the shared
# ~/.cache/puppeteer, which is what makes "uninstall = delete this folder" true, and
# stops a half-downloaded browser left by some other project from breaking this install.
say "[3/4] מתקין את רכיב סריקת הבנקים (הורדה גדולה, נא להמתין)…"
npm_install() (
  cd scraper
  export PATH="$PWD/../.venv/bin:$PATH" PUPPETEER_CACHE_DIR="$PWD/../.puppeteer"
  npm install --no-audit --no-fund || exit 1
  # Fetch the browser explicitly instead of relying on puppeteer's postinstall hook:
  # npm 12 blocks install scripts by default, which would leave a "successful" install
  # with no browser and every scrape failing later. Idempotent — a no-op once present,
  # and with no arguments it installs exactly what puppeteer itself asks for.
  npx puppeteer browsers install || exit 1
)
# An interrupted download leaves the browser folder present but the executable missing,
# and puppeteer then fails instead of re-fetching — so a plain re-run would fail
# identically forever. Clearing the partial download is what makes re-running work.
if ! npm_install; then
  say "ההורדה הופסקה באמצע — מנקה ומנסה שוב…"
  rm -rf .puppeteer scraper/node_modules
  npm_install || die "התקנת רכיב הסריקה נכשלה — בדקו את חיבור האינטרנט והריצו שוב את install"
fi

# ---------- 4. an empty database ----------
say "[4/4] יוצר בסיס נתונים ריק…"
"$UV" run python -m kaspion.cli init || die "יצירת בסיס הנתונים נכשלה"

printf '\n\033[32m✔ ההתקנה הושלמה.\033[0m\n'
echo "להפעלה — לחצו פעמיים על kaspion"
echo
read -r -p "הקישו Enter לסגירה"
