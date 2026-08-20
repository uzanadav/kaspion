#!/usr/bin/env bash
# kaspion — macOS. Double-click to open the dashboard.
# The server prints its address and opens your browser; close this window to stop it.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".tools/uv" ] || [ ! -d ".venv" ]; then
  echo "כספיון עדיין לא הותקן."
  echo "לחצו פעמיים על install (באותה תיקייה) והריצו שוב."
  echo
  read -r -p "הקישו Enter לסגירה"
  exit 1
fi

exec ./.tools/uv run python -m kaspion.serve
