"""Import an Isracard statement export (.xlsx) into the raw.transactions contract.

Why this exists: Isracard's login sits behind reCAPTCHA, so israeli-bank-scrapers
cannot log in (upstream issue #1140, open since Jul 2026). Downloading the monthly
statement by hand and importing the file is the supported path — the rows land in
exactly the same shape the scraper produces, so dbt / categorization / the dashboard
never know the difference.

The export has several sections whose position moves between files:
  עסקאות למועד חיוב   – charged in this billing cycle
  עסקאות לידיעה       – made this month but NOT charged this month
  עסקאות שטרם נקלטו   – authorized, not yet settled
All of them are real spending, so all are imported; the voucher number keeps a
transaction from being counted twice when it moves between sections next month.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from kaspion.db import connect

# column layout under every "תאריך רכישה" header row (1-based, as in the sheet)
COL_DATE, COL_MERCHANT, COL_CHARGED, COL_VOUCHER, COL_EXTRA = 1, 2, 5, 7, 8
HEADER_CELL = "תאריך רכישה"

HEB_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
              "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]


def _billing_date(sheet) -> date | None:
    """When this statement actually hits the account.

    Every installment payment of a purchase repeats that purchase's ORIGINAL date
    (a 12-payment plan bought 10.09.25 shows 10.09.25 on all 12 statements), so
    dating them by purchase would pile a year of payments onto one long-past month
    and leave the months the money really left showing nothing. Installments are
    therefore dated to the statement's charge date, which is what the household feels.
    """
    charge_day = charge_month = None
    year = None
    for row in range(1, 12):
        for col in range(1, 9):
            cell = sheet.cell(row, col).value
            if not isinstance(cell, str):
                continue
            if year is None:
                found = re.search(r"(20\d{2})", cell)
                if found and any(m in cell for m in HEB_MONTHS):
                    year = int(found.group(1))
            hit = re.search(r"לחיוב ב-?\s*(\d{2})\.(\d{2})", cell)
            if hit:
                charge_day, charge_month = int(hit.group(1)), int(hit.group(2))
    if year and charge_day and charge_month:
        return date(year, charge_month, charge_day)
    # fall back to the 1st of the statement month named in the header
    for row in range(1, 12):
        for col in range(1, 9):
            cell = sheet.cell(row, col).value
            if isinstance(cell, str):
                for i, name in enumerate(HEB_MONTHS, start=1):
                    hit = re.search(rf"{name}\s+(20\d{{2}})", cell)
                    if hit:
                        return date(int(hit.group(1)), i, 1)
    return None


def _parse_date(value) -> date | None:
    """Sheet dates are 'DD.MM.YY' strings, but openpyxl sometimes types them."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%d.%m.%y").date()
        except ValueError:
            return None
    return None


def _card_digits(sheet) -> str:
    """Card number from the header block, e.g. '‫<card name>‬ - 1234' -> '1234'.
    The cell is wrapped in RTL control characters, so match digits, not position."""
    for row in range(1, 12):
        cell = sheet.cell(row, 1).value
        if not isinstance(cell, str):
            continue
        # the card line reads "<card name> - 1234"; require the separator so a header
        # ending in the statement year ("… אוגוסט 2026") can't be mistaken for a card.
        # Getting this wrong would change account_id, and account_id is part of every
        # transaction_id — the same charge would re-import under a second identity.
        found = re.search(r"[-–]\s*(\d{4,6})\s*$", cell.strip())
        if found and not re.fullmatch(r"20\d{2}", found.group(1)):
            return found.group(1)
    return "unknown"


def parse_file(path: str | Path) -> list[dict]:
    """Read an Isracard .xlsx export into raw.transactions-shaped dicts."""
    import openpyxl  # imported lazily: only the file-import path needs Excel support

    sheet = openpyxl.load_workbook(path, data_only=True).active
    account_id = f"isracard-{_card_digits(sheet)}"
    billing = _billing_date(sheet)
    rows: list[dict] = []

    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row, COL_DATE).value != HEADER_CELL:
            continue
        # walk the section under this header until the dates stop (blank row,
        # a "סה\"כ" total line, or the next section's title)
        for data_row in range(row + 1, sheet.max_row + 1):
            posted = _parse_date(sheet.cell(data_row, COL_DATE).value)
            if posted is None:
                break
            charged = sheet.cell(data_row, COL_CHARGED).value
            if not isinstance(charged, (int, float)):
                continue
            merchant = str(sheet.cell(data_row, COL_MERCHANT).value or "").strip()
            voucher = str(sheet.cell(data_row, COL_VOUCHER).value or "").strip()
            # installments reuse one voucher across payments ("תשלום 11 מתוך 12"),
            # so the note has to be part of the identity or payment 12 would be
            # swallowed as a duplicate of payment 11
            extra = str(sheet.cell(data_row, COL_EXTRA).value or "").strip()
            # The voucher is the identity. Not-yet-settled rows can arrive without one,
            # and two such charges would otherwise hash alike and silently overwrite
            # each other. Only the blank-voucher case gets extra entropy, so ids for
            # rows that DO have a voucher stay byte-identical to previous imports —
            # changing those would re-insert every already-imported charge as new.
            key = (f"{account_id}|{voucher}|{extra}" if voucher
                   else f"{account_id}||{extra}|{posted}|{charged}|{merchant}")
            # an installment payment belongs to the month it is charged, not to the
            # long-past date the original purchase was made (see _billing_date)
            if "תשלום" in extra and billing is not None:
                posted = billing
            rows.append({
                "transaction_id": hashlib.sha256(key.encode()).hexdigest()[:16],
                "account_id": account_id,
                "account_type": "credit_card",
                "posted_date": posted.isoformat(),
                # the sheet lists charges as positive; kaspion's convention is
                # negative = outflow. A refund is already negative here and
                # correctly flips to a positive inflow.
                "amount": -float(charged),
                "currency": "ILS",
                "raw_description": merchant,
                "source": "isracard",
            })
    return rows


def import_file(path: str | Path) -> tuple[int, int]:
    """Upsert one export into raw.transactions. Returns (added, updated).

    Re-importing the same file is safe and self-correcting: a pending charge that
    later settles for a different amount is refreshed rather than left stale.
    """
    from kaspion.ingest.statements import upsert_rows

    return upsert_rows(parse_file(path))


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        added, updated = import_file(arg)
        print(f"{Path(arg).name}: {added} new, {updated} updated")
