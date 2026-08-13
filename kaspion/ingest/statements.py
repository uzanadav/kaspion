"""Shared entry point for importing downloaded statements.

One place decides which bank a file came from and one place writes it, so the
dashboard's upload button never has to care about the format.
"""
from __future__ import annotations

from pathlib import Path

from kaspion.db import connect


def upsert_rows(rows: list[dict]) -> tuple[int, int]:
    """Write parsed rows into raw.transactions. Returns (added, updated).

    Re-importing is safe and self-correcting: a row already present is refreshed
    rather than duplicated, so overlapping date ranges and re-downloads of a
    corrected statement both do the right thing.
    """
    if not rows:
        return 0, 0
    con = connect()
    before = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
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
    return added, len(rows) - added


def detect_format(path: str | Path) -> str:
    """'onezero' | 'isracard', decided by the file itself rather than its name.

    Downloads get renamed, and both banks hand out files called *.xls*, so sniffing
    the container and its header is the only reliable signal.
    """
    with open(path, "rb") as handle:
        magic = handle.read(8)
    if magic.startswith(b"\xd0\xcf\x11\xe0"):   # OLE2 compound file -> legacy .xls
        return "onezero"
    if magic.startswith(b"PK"):                 # zip container -> .xlsx
        return "isracard"
    raise ValueError("unrecognised file: expected an Excel statement (.xls or .xlsx)")


def import_statement(path: str | Path) -> dict:
    """Parse and import one statement, whichever bank it came from."""
    kind = detect_format(path)
    if kind == "onezero":
        from kaspion.ingest.onezero_file import parse_file
    else:
        from kaspion.ingest.isracard_file import parse_file
    rows = parse_file(path)
    added, updated = upsert_rows(rows)
    return {"source": kind, "added": added, "updated": updated, "parsed": len(rows)}
