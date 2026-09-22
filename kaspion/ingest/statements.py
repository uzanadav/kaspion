"""Shared entry point for importing downloaded statements.

One place decides which bank a file came from and one place writes it, so the
dashboard's upload button never has to care about the format.
"""
from __future__ import annotations

from pathlib import Path

from kaspion.db import assign_natural_ids, connect


def upsert_rows(rows: list[dict]) -> tuple[int, int]:
    """Write parsed rows into raw.transactions. Returns (added, updated).

    Re-importing is safe: a row already present (by content — see
    assign_natural_ids) is recognised and skipped rather than duplicated, so
    overlapping date ranges import cleanly. A parser-assigned id (e.g. Isracard's
    voucher number) is trusted and can still update in place if its own amount or
    description changes; content-derived ids cannot, since the content changing
    would make it a different key entirely — see assign_natural_ids's docstring
    for why that trade-off was made.
    """
    if not rows:
        return 0, 0
    con = connect()
    total = len(rows)
    rows = assign_natural_ids(rows, con)
    before = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    if rows:
        con.executemany(
            """
            INSERT INTO raw.transactions
                (transaction_id, account_id, account_type, posted_date,
                 amount, currency, raw_description, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (transaction_id) DO UPDATE SET
                amount          = excluded.amount,
                posted_date     = excluded.posted_date,
                raw_description = excluded.raw_description
            """,
            [[r["transaction_id"], r["account_id"], r["account_type"], r["posted_date"],
              r["amount"], r["currency"], r["raw_description"], r["source"]] for r in rows],
        )
    after = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    con.close()
    added = after - before
    return added, total - added


def detect_format(path: str | Path) -> str:
    """'onezero' | 'onezero_pdf' | 'isracard', decided by the file rather than its name.

    Downloads get renamed, and both banks hand out files called *.xls*, so sniffing
    the container and its header is the only reliable signal.
    """
    with open(path, "rb") as handle:
        magic = handle.read(8)
    if magic.startswith(b"\xd0\xcf\x11\xe0"):   # OLE2 compound file -> legacy .xls
        return "onezero"
    if magic.startswith(b"%PDF"):               # ONE ZERO hands out a PDF now
        return "onezero_pdf"
    if magic.startswith(b"PK"):                 # zip container -> .xlsx
        return "isracard"
    raise ValueError("unrecognised file: expected a statement (.xls, .xlsx or .pdf)")


def drop_known_by_date_and_amount(rows: list[dict]) -> list[dict]:
    """Drop rows the database already holds, matching on date and amount only.

    ONE ZERO describes the same movement differently in its PDF than in its .xls
    export ("חיוב מ -מקס איט פיננסים" vs "מקס איט פיננסים/34685693"), so the content
    identity in assign_natural_ids sees two different transactions and would import
    an account's whole overlap twice. Matching is by MULTIPLICITY, not existence: two
    ₪100 standing orders on the same day are two real movements, and importing an
    export that contains both when the database holds one must still add the second.
    """
    from collections import Counter

    con = connect()
    seen: Counter = Counter()
    keep = []
    for row in rows:
        key = (row["account_id"], row["posted_date"], f'{float(row["amount"]):.2f}')
        seen[key] += 1
        held = con.execute(
            "SELECT count(*) FROM raw.transactions "
            "WHERE account_id = ? AND posted_date = ? AND amount = ?",
            [key[0], key[1], float(row["amount"])],
        ).fetchone()[0]
        if seen[key] > held:
            keep.append(row)
    con.close()
    return keep


def import_statement(path: str | Path) -> dict:
    """Parse and import one statement, whichever bank it came from."""
    kind = detect_format(path)
    if kind == "onezero":
        from kaspion.ingest.onezero_file import parse_file
    elif kind == "onezero_pdf":
        from kaspion.ingest.onezero_pdf import parse_file
    else:
        from kaspion.ingest.isracard_file import parse_file
    rows = parse_file(path)
    if kind.startswith("onezero"):
        rows = drop_known_by_date_and_amount(rows)
    added, updated = upsert_rows(rows)
    return {"source": kind, "added": added, "updated": updated, "parsed": len(rows)}
