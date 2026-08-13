"""Import a ONE ZERO account export (.xls) into the raw.transactions contract.

ONE ZERO is a BANK account, which makes it different from the card statements in two
ways that matter:

1. Its rows include the monthly credit-card debits (e.g. "ישראכרט-דיירקט/…" for
   exactly the Isracard statement total). Those must never be
   counted as spend on top of the card's own charges — `int_card_payments.sql`
   recognises them and `fct_spend` drops them. The card-side charges are the spend.
2. Amounts arrive already signed (negative = debit), unlike the card exports which
   list charges as positive.

The file is a real legacy OLE2 .xls, so it needs xlrd rather than openpyxl, and its
Hebrew is stored back-to-front behind an LTR override (see _reading_order).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

COL_DATE, COL_KIND, COL_DESC, COL_AMOUNT, COL_CURRENCY, COL_REF = 0, 2, 3, 4, 5, 8
HEADER_CELL = "תאריך תנועה"

# LTR/RTL overrides and marks the export wraps its Hebrew in
_BIDI = re.compile(r"[‪-‮‎‏]")
# a run of latin/digits, plus the punctuation and spaces that travel with it
_LATIN_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ,./:'\"-]*")


def _reading_order(text: str) -> str:
    """Undo ONE ZERO's back-to-front Hebrew.

    Descriptions are stored reversed behind a U+202D override so a naive viewer
    shows them correctly. Reversing the whole string fixes the Hebrew but also
    flips every number — a card number would come back reversed — so each latin/digit run is
    flipped back afterwards. Rows without the override are already in reading order
    and must be left alone.
    """
    if not _BIDI.search(text):
        return text.strip()
    flipped = _BIDI.sub("", text).strip()[::-1]
    return _LATIN_RUN.sub(lambda m: m.group(0)[::-1], flipped)


def parse_file(path: str | Path) -> list[dict]:
    """Read a ONE ZERO .xls export into raw.transactions-shaped dicts."""
    import xlrd  # lazy: only the file-import path needs legacy Excel support

    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    header = next(
        (r for r in range(sheet.nrows) if str(sheet.cell_value(r, COL_DATE)).strip() == HEADER_CELL),
        None,
    )
    if header is None:
        raise ValueError("not a ONE ZERO export: no 'תאריך תנועה' header row")

    rows: list[dict] = []
    for r in range(header + 1, sheet.nrows):
        serial = sheet.cell_value(r, COL_DATE)
        amount = sheet.cell_value(r, COL_AMOUNT)
        if not isinstance(serial, float) or not isinstance(amount, (int, float)) or amount == 0:
            continue
        y, m, d = xlrd.xldate_as_tuple(serial, book.datemode)[:3]
        description = _reading_order(str(sheet.cell_value(r, COL_DESC)))
        kind = _reading_order(str(sheet.cell_value(r, COL_KIND)))
        reference = str(sheet.cell_value(r, COL_REF)).strip()
        # The bank's reference is unique per movement, so re-importing an overlapping
        # date range updates rows instead of duplicating them. A row without one falls
        # back to its own content — otherwise every reference-less movement in the file
        # would collapse onto a single id. Rows WITH a reference keep their original
        # hash so previously imported movements are still recognised.
        key = f"onezero|{reference}" if reference else (
            f"onezero||{y:04d}-{m:02d}-{d:02d}|{amount}|{description}"
        )
        rows.append({
            "transaction_id": hashlib.sha256(key.encode()).hexdigest()[:16],
            "account_id": "onezero",
            "account_type": "bank",
            "posted_date": date(y, m, d).isoformat(),
            "amount": float(amount),   # already signed: negative = debit
            "currency": str(sheet.cell_value(r, COL_CURRENCY)).strip() or "ILS",
            # keep the movement type in the text: it is what tells a standing order
            # from a cheque from a card debit once the row reaches categorization
            "raw_description": f"{description} [{kind}]" if kind else description,
            "source": "onezero",
        })
    return rows


if __name__ == "__main__":
    import sys

    from kaspion.ingest.statements import upsert_rows

    for arg in sys.argv[1:]:
        added, updated = upsert_rows(parse_file(arg))
        print(f"{Path(arg).name}: {added} new, {updated} updated")
