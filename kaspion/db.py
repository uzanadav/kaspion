from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "finance.duckdb"

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

def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the household database.

    Note: `read_only` is accepted for call-site clarity but ignored — DuckDB's
    Python driver caches the database per process and errors if the same file is
    opened with different configs, so we always use one (read-write) config.
    """
    del read_only
    DB_PATH.parent.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(DDL)
    return con
