#!/usr/bin/env bash
# kaspion one-time setup: venv + dependencies + sanity-check pipeline run.
# Usage:  bash scripts/setup.sh          (safe to re-run anytime)
set -euo pipefail
cd "$(dirname "$0")/.."

# ---------- logging helpers ----------
BOLD=$(tput bold 2>/dev/null || true); GREEN=$(tput setaf 2 2>/dev/null || true)
RED=$(tput setaf 1 2>/dev/null || true); YELLOW=$(tput setaf 3 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)
step() { echo; echo "${BOLD}==> $1${RESET}"; }
ok()   { echo "${GREEN}    ✔ $1${RESET}"; }
warn() { echo "${YELLOW}    ⚠ $1${RESET}"; }
die()  { echo "${RED}    ✘ $1${RESET}"; exit 1; }

echo "${BOLD}kaspion setup$(date +' — %Y-%m-%d %H:%M')${RESET}"

# ---------- 1. virtual environment ----------
# Reuse an existing .venv (it may be a newer Python than the ambient `python3`,
# e.g. when a 3.9 conda base is active). Only when creating fresh do we hunt for
# a 3.10+ interpreter. The version gate below then checks the venv's python — the
# one actually used — never whatever happens to be on PATH.
step "creating virtual environment (.venv)"
# A .venv copied between machines (or an interrupted create) keeps the directory but loses
# the python symlink — reusing it would blow up on `source .venv/bin/activate`.
if [ -d .venv ] && [ ! -x .venv/bin/python3 ]; then
  warn "existing .venv has no usable python (copied from another machine?) — recreating"
  rm -rf .venv
fi
if [ -d .venv ]; then
  ok "already exists — reusing"
else
  PYBIN=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PYBIN="$cand"; break
    fi
  done
  [ -n "$PYBIN" ] || die "no Python 3.10+ found on PATH — install it (macOS: brew install python@3.12)"
  "$PYBIN" -m venv .venv || die "venv creation failed (on Ubuntu: sudo apt install python3-venv)"
  ok "created with $PYBIN"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
ok "activated ($(python3 -c 'import sys; print(sys.prefix)'))"

# ---------- 2. verify the venv's python ----------
step "checking python3"
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "venv python is $PYVER — need 3.10+. Recreate it: rm -rf .venv && bash scripts/setup.sh"
ok "python3 $PYVER (from .venv)"

# a reused (or interrupted) venv can be missing pip — bootstrap it before use
if ! python3 -m pip --version >/dev/null 2>&1; then
  warn "pip missing in venv — bootstrapping with ensurepip"
  python3 -m ensurepip --upgrade >/dev/null 2>&1 \
    || die "could not bootstrap pip (try: rm -rf .venv && bash scripts/setup.sh)"
  ok "pip bootstrapped"
fi

# ---------- 3. python dependencies ----------
step "installing python dependencies (duckdb, dbt-duckdb, pandas...)"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -e . || die "pip install failed — see output above"
ok "installed: $(python3 -c 'import duckdb; print("duckdb", duckdb.__version__)')"
ok "installed: $(dbt --version 2>/dev/null | grep -m1 'installed' | xargs || echo 'dbt-duckdb')"

# ---------- 4. sample data + full pipeline sanity check ----------
step "generating sample data"
python3 kaspion/ingest/generate_seed.py

step "running the pipeline (ingest -> dbt build + all tests -> dashboard)"
python3 sync.py --skip-categorize
ok "pipeline green — database at data/finance.duckdb"
ok "dashboard written — open dashboard.html in a browser"

# ---------- 5. optional tools ----------
step "checking optional tools"
if command -v ollama >/dev/null; then
  ok "ollama found — enable AI categorization with: ollama pull llama3.1:8b && python3 sync.py"
else
  warn "ollama not installed (free, local AI categorization) — https://ollama.com"
fi
if command -v node >/dev/null; then
  ok "node $(node --version) found — needed only for the bank scraper (cd scraper && npm install)"
else
  warn "node not installed — needed only for the bank scraper (the dashboard needs nothing)"
fi

# ---------- done ----------
echo
echo "${BOLD}${GREEN}setup complete.${RESET}"
echo "next steps:"
echo "  open dashboard.html                     # the dashboard — sample data is already in it"
echo "  source .venv/bin/activate               # in every new terminal"
echo "  python3 sync.py --provider none         # run everything WITHOUT AI (no Ollama needed)"
echo "  python3 sync.py                         # with Ollama: AI categorization"
echo "  python3 -m kaspion.ingest.crypto        # bank credentials (encrypted)"
echo "  python3 sync.py --source scraper        # real data (after: cd scraper && npm install)"
