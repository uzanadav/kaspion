"""Bank-supplied merchant names and user-typed category names reach the dashboard as
raw text and are rendered with innerHTML. The page holds an authenticated channel to
/api/add-account and /api/remove, so an unescaped `<img onerror>` in a merchant name is
not cosmetic. app.js already has escTxt/escAttr — this checks they are actually used.
"""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "kaspion" / "assets" / "app.js").read_text()

# t[2] = raw_description, t[3] = category name — see report.py's row layout
FREE_TEXT = [r"\$\{t\[2\]\}", r"\$\{t\[3\]\}", r"\$\{c\.name\}", r"\$\{p\.name\}"]


def test_free_text_is_never_interpolated_unescaped():
    for pattern in FREE_TEXT:
        found = [ln for ln in JS.splitlines() if re.search(pattern, ln)]
        assert not found, f"unescaped {pattern} in: {found}"


def test_the_escaping_helpers_still_exist():
    assert "const escTxt" in JS and "const escAttr" in JS
