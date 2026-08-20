from __future__ import annotations

import hashlib

import duckdb

from kaspion.paths import db_path

DB_PATH = db_path()

DDL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS state;

CREATE TABLE IF NOT EXISTS raw.transactions (
    transaction_id  TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    account_type    TEXT NOT NULL CHECK (account_type IN ('bank', 'credit_card')),
    posted_date     DATE NOT NULL,
    amount          DECIMAL(18, 2) NOT NULL,   -- negative = outflow, positive = inflow
    currency        TEXT NOT NULL DEFAULT 'ILS',
    raw_description TEXT NOT NULL,
    source          TEXT NOT NULL,
    ingested_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS state.ai_proposals (
    merchant_key         TEXT PRIMARY KEY,
    proposed_category_id TEXT NOT NULL,
    provider             TEXT NOT NULL,
    model                TEXT NOT NULL,
    confidence           DOUBLE,
    created_at           TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS state.merchant_overrides (
    merchant_key TEXT PRIMARY KEY,
    category_id  TEXT NOT NULL,
    updated_at   TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS state.budgets (
    category_id        TEXT PRIMARY KEY,
    monthly_amount_ils DECIMAL(18, 2) NOT NULL,
    effective_from     DATE NOT NULL DEFAULT current_date
);

-- categories the household adds from the dashboard. The built-in list stays in the
-- dbt seed; this table only ever ADDS to it, and lives in state.* so a
-- `dbt build --full-refresh` can never wipe it (same rule as budgets/overrides).
CREATE TABLE IF NOT EXISTS state.categories (
    category_id TEXT PRIMARY KEY,
    name_he     TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS state.excluded_transactions (
    transaction_id TEXT PRIMARY KEY,
    excluded_at    TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

def connect() -> duckdb.DuckDBPyConnection:
    """Open the household database.

    Always read-write: DuckDB's Python driver caches the database per process and
    errors if the same file is opened with different configs.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(DDL)
    return con


def assign_natural_ids(rows: list[dict], con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Assign a transaction_id to every row that doesn't already have one, and drop
    rows the database can already account for. Returns only the rows that should
    actually be inserted.

    Content identity — (account_id, posted_date, amount, raw_description) — always
    wins, even over a raw reference number a bank/scraper already supplied: if two
    rows in this same batch share that exact key, only the first is kept; if a
    matching row already exists in the database (checked by CONTENT, not by
    transaction_id, so this is safe for rows inserted under an older id scheme), the
    incoming one is dropped entirely rather than minted a new id.

    This is a deliberate trade-off, made after finding 9 real duplicate groups across
    every institution in this household's data: a bank scrape or statement export has
    repeatedly listed the exact same movement twice in one fetch (most likely a
    pending + settled pair sharing no common reference), and separately, a natural-key
    row's old id scheme depended on its position within a batch, which is not stable
    across separate scrape/upload runs — the same real transaction could mint a second,
    different id later and get inserted again. Neither failure has a reliable signal
    to distinguish it from two genuinely separate transactions that happen to share a
    day, amount, and description — that coincidence is rare enough, and over-counting
    real money is worse than under-counting a rare one, that collapsing to one row is
    the safer default for a finance app.
    """
    keep: list[dict] = []
    seen_keys: set[tuple] = set()
    for r in rows:
        key = (r["account_id"], r["posted_date"], str(r["amount"]), r["raw_description"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # checked for EVERY row, not just ones missing a transaction_id — a row that
        # already carries a "trusted" reference-based id still needs this: that id is
        # deterministic per reference, but two DIFFERENT references can represent the
        # same real movement (a pending + settled pair), and ON CONFLICT DO NOTHING
        # only catches an exact id match, never a content match. Skipping this check
        # for pre-ided rows was the actual bug in an earlier version of this fix — it
        # let a content duplicate re-insert itself on the very next sync.
        existing = con.execute(
            "SELECT count(*) FROM raw.transactions "
            "WHERE account_id = ? AND posted_date = ? AND amount = ? "
            "AND raw_description = ?",
            [key[0], key[1], float(key[2]), key[3]],
        ).fetchone()[0]
        if existing:
            continue
        if not r.get("transaction_id"):
            r["transaction_id"] = hashlib.sha256("|".join(key).encode()).hexdigest()[:16]
        keep.append(r)
    return keep
