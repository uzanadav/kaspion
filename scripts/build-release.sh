#!/usr/bin/env bash
# Build the zip users download, then prove it carries nothing personal.
#
# Uses `git archive`, never a copy of the working tree: it ships only git-tracked files,
# so the database, credentials, key, generated dashboard, .venv, node_modules and the
# downloaded browser are excluded BY CONSTRUCTION rather than by remembering to exclude
# them. `.gitattributes` additionally drops the synthetic demo dataset.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(git describe --tags --always --dirty)"
OUT="kaspion-${VERSION}.zip"

if [ -n "$(git status --porcelain)" ]; then
  echo "warning: working tree is dirty — the archive is built from HEAD, not your edits" >&2
fi

git archive --format=zip --prefix=kaspion/ -o "$OUT" HEAD
echo "built $OUT ($(du -h "$OUT" | cut -f1))"

# ---------- the leak check ----------
# Any hit here means personal data is about to be published. Fail loudly; never publish
# an archive that has not passed this.
echo
echo "checking the archive for personal data…"
LEAKS="$(unzip -l "$OUT" | grep -iE 'duckdb|\.enc$|kaspion_key|dashboard\.html|sample_transactions|\.venv/|node_modules/|\.puppeteer/|\.tools/' || true)"
if [ -n "$LEAKS" ]; then
  echo "REFUSING TO SHIP — the archive contains:" >&2
  echo "$LEAKS" >&2
  rm -f "$OUT"
  exit 1
fi

# The launchers must survive zip round-tripping as executable, or a macOS user gets a
# file that opens in a text editor instead of running. git stores the bit (100755) and
# `git archive` preserves it; this catches it ever being lost.
for f in kaspion/install.command kaspion/kaspion.command; do
  if unzip -Z "$OUT" "$f" 2>/dev/null | grep -q '^-rwx'; then
    echo "  $f is executable ✓"
  else
    echo "REFUSING TO SHIP — $f is not executable in the archive." >&2
    echo "  fix with: git update-index --chmod=+x ${f#kaspion/}" >&2
    rm -f "$OUT"
    exit 1
  fi
done

echo "clean — no personal data, safe to publish."
echo
echo "next: gh release create v${VERSION#v} $OUT --notes-file INSTALL.md"
