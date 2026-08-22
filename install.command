#!/usr/bin/env bash
# kaspion installer — macOS. Double-click this file.
#
# Everything lands inside this folder (uv, Python, the libraries, the scraper), so
# uninstalling is deleting this folder plus the data folder printed at the end.
# Nothing is installed system-wide and no admin password is needed.
#
# Safe to re-run: every step below skips work that is already done, so if the download
# is interrupted you can just double-click again.
#
# Console text is English on purpose. Terminals render Hebrew left-to-right — words come
# out in reverse order — and there is no setting that fixes it (it is an open feature
# request in both Windows Terminal and conhost, and Terminal.app is no better). Reversed
# Hebrew is less readable than plain English, so Hebrew lives where it renders correctly:
# the dashboard and INSTALL.md.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
die() { printf '\n\033[31m✘ %s\033[0m\n' "$1"; echo; read -r -p "Press Enter to close"; exit 1; }

echo "Installing kaspion. This takes about 10 minutes and downloads ~1.2GB."
echo "An internet connection is required."

# ---------- 1. uv, vendored into this folder ----------
# The official installer, pointed at ./.tools so it touches nothing else on the machine
# and never edits your shell PATH. uv brings its own Python, so no Python is required.
if [ ! -x ".tools/uv" ]; then
  say "[1/4] Downloading the installer..."
  curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR="$PWD/.tools" INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null \
    || die "Could not download the installer. Check your internet connection and try again."
else
  say "[1/4] Installer already present - skipping"
fi
UV="$PWD/.tools/uv"

# ---------- 2. Python + libraries ----------
say "[2/4] Installing Python and the libraries..."
"$UV" sync --frozen || die "Installing the libraries failed."

# ---------- 3. the bank scraper ----------
# node/npm arrive as a Python dependency (nodejs-wheel) and live in .venv/bin, so they
# only need to be on PATH for npm's own sake. This step also pulls Chromium (~600MB).
#
# PUPPETEER_CACHE_DIR keeps that browser inside the app folder instead of the shared
# ~/.cache/puppeteer, which is what makes "uninstall = delete this folder" true, and
# stops a half-downloaded browser left by some other project from breaking this install.
say "[3/4] Installing the bank scraper (large download, please wait)..."
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
  say "Download was interrupted - cleaning up and retrying..."
  rm -rf .puppeteer scraper/node_modules
  npm_install || die "Installing the bank scraper failed. Check your internet connection and run install again."
fi

# ---------- 4. an empty database ----------
say "[4/4] Creating an empty database..."
"$UV" run python -m kaspion.cli init || die "Creating the database failed."

printf '\n\033[32m** Setup complete. **\033[0m\n'
echo 'To start kaspion, double-click "kaspion".'
echo
read -r -p "Press Enter to close"
