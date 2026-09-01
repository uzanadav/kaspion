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

-- a trip is a named date range, nothing more. Which transactions belong to it is DERIVED
-- from their posted_date every time the page is built, never stored, so a charge that
-- lands after the trip was created still shows up in it.
CREATE TABLE IF NOT EXISTS state.trips (
    trip_id    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    country    TEXT NOT NULL DEFAULT '',
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- rows charged inside a trip's range that are not part of the trip (rent, a standing
-- order). Per trip, never global: state.excluded_transactions hides a row from EVERY
-- figure in the app, which is not what "this isn't a holiday expense" means.
CREATE TABLE IF NOT EXISTS state.trip_exclusions (
    trip_id        TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    PRIMARY KEY (trip_id, transaction_id)
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
    """Return only the rows worth inserting, each with a transaction_id.

    Content — (account_id, posted_date, amount, raw_description) — is the identity of a
    transaction and beats any reference number the source supplied. Duplicates within
    the batch and rows already in the database are dropped. See "How a duplicate is
    recognised" in docs/HOW_IT_WORKS.md for why content wins.
    """
    keep: list[dict] = []
    seen_keys: set[tuple] = set()
    for r in rows:
        amount = float(r["amount"])
        # normalised, not str(r["amount"]): Decimal("10.00") and 10.0 are the same
        # charge but stringify differently, which would slip a duplicate past this set
        key = (r["account_id"], r["posted_date"], f"{amount:.2f}", r["raw_description"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # checked for EVERY row, not just ones missing a transaction_id: a "trusted"
        # reference-based id is deterministic per reference, but two DIFFERENT
        # references can describe the same movement (a pending + settled pair), and
        # ON CONFLICT DO NOTHING only catches an exact id match. Skipping this for
        # pre-ided rows let a content duplicate re-insert itself on the next sync.
        existing = con.execute(
            "SELECT count(*) FROM raw.transactions "
            "WHERE account_id = ? AND posted_date = ? AND amount = ? "
            "AND raw_description = ?",
            [key[0], key[1], amount, key[3]],
        ).fetchone()[0]
        if existing:
            continue
        if not r.get("transaction_id"):
            r["transaction_id"] = hashlib.sha256("|".join(key).encode()).hexdigest()[:16]
        keep.append(r)
    return keep
