"""Import a ONE ZERO "פירוט תנועות שקליות בחשבון" PDF statement.

ONE ZERO hands out this PDF where it used to hand out an .xls, so it has to reach
raw.transactions the same way — see onezero_file.py for the two rules that make this
a BANK account (card debits are not spend, amounts are already signed).

The layout is one movement per row, wrapped over as many lines as the description
needs, and every row ends with its two dates:

    45,614.89 0 6.06 -מקס איט פיננסים
    חיוב מ 09/06/2026 09/06/2026
    └ balance  └ credits           └ value date  └ transaction date
                 └ debits

The extractor emits the visual columns left to right, which for this RTL page means
balance first and the description's wrapped lines bottom-up — hence the reversal in
_description(). The transaction date (the last one) is the posted date: the two differ
on rows like זיכוי דמי מנוי, and the .xls export files those under the later one.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# a row ends the moment its two dates appear; everything buffered before them is the row
_ROW_END = re.compile(r"^(.*?)\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s*$")
# balance, credits, debits — the three figures every row opens with
_FIGURES = re.compile(r"^([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\b\s*")


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _description(parts: list[str]) -> str:
    """Wrapped RTL lines come out bottom-up; reading order is the reverse."""
    return " ".join(p for p in reversed(parts) if p)


def parse_file(path: str | Path) -> list[dict]:
    """Read a ONE ZERO PDF statement into raw.transactions-shaped dicts."""
    import pypdf  # lazy: only the file-import path needs PDF support

    pages = [page.extract_text() for page in pypdf.PdfReader(str(path)).pages]
    return parse_text("\n".join(pages))


def parse_text(text: str) -> list[dict]:
    """The parser proper, on the extracted text — the half worth testing directly."""
    if "פירוט של תנועות שקליות בחשבון" not in text:
        raise ValueError("not a ONE ZERO statement: missing the 'פירוט של תנועות שקליות' heading")

    rows: list[dict] = []
    buffer: list[str] = []
    for line in text.splitlines():
        end = _ROW_END.match(line.strip())
        if end is None:
            buffer.append(line.strip())
            continue
        buffer.append(end.group(1))
        # the row starts at its figures, not at the top of the buffer: each page's
        # letterhead sits above the first movement and would otherwise swallow it
        start = next((i for i in reversed(range(len(buffer))) if _FIGURES.match(buffer[i])), None)
        if start is not None:   # no figures = page furniture that happened to end in two dates
            figures = _FIGURES.match(buffer[start])
            _, credits, debits = (_num(g) for g in figures.groups())
            amount = credits - debits
            if amount:
                rows.append({
                    "account_id": "onezero",
                    "account_type": "bank",
                    "posted_date": datetime.strptime(end.group(3), "%d/%m/%Y").date().isoformat(),
                    "amount": amount,       # signed like the .xls export: negative = debit
                    "currency": "ILS",
                    "raw_description": _description(
                        [buffer[start][figures.end():], *buffer[start + 1:]]),
                    "source": "onezero",
                })
        buffer = []
    if not rows:
        raise ValueError("no movements found in the ONE ZERO PDF")
    return rows
