from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from kaspion.db import connect
from kaspion.ingest.crypto import load_credentials

SCRAPER_DIR = Path(__file__).resolve().parents[2] / "scraper"


def load_from_scraper(days_back: int = 60) -> int:
    creds = load_credentials()
    all_rows: list[dict] = []
    for company, cfg in creds.items():
        proc = subprocess.run(
            ["node", "scrape.js"],
            cwd=SCRAPER_DIR,
            env=dict(
                os.environ,
                KASPION_COMPANY=company,
                KASPION_CREDENTIALS=json.dumps(cfg["credentials"]),
                KASPION_ACCOUNT_TYPE=cfg["type"],
                KASPION_START_DATE=(date.today() - timedelta(days=days_back)).isoformat(),
            ),
            capture_output=True,
            text=True,
            check=True,
        )
        all_rows.extend(json.loads(proc.stdout))

    _assign_ids(all_rows)
    con = connect()
    before = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    if all_rows:
        con.executemany(
            """
            INSERT INTO raw.transactions
                (transaction_id, account_id, account_type, posted_date,
                 amount, currency, raw_description, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (transaction_id) DO NOTHING
            """,
            [
                [r["transaction_id"], r["account_id"], r["account_type"], r["posted_date"],
                 r["amount"], r["currency"], r["raw_description"], r["source"]]
                for r in all_rows
            ],
        )
    after = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    con.close()
    return after - before


def _assign_ids(rows: list[dict]) -> None:
    counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        if r.get("source_id"):  # prefer the bank's own id when provided
            r["transaction_id"] = hashlib.sha256(
                f"{r['account_id']}|{r['source_id']}".encode()
            ).hexdigest()[:16]
        else:
            key = (r["posted_date"], str(r["amount"]), r["raw_description"], r["account_id"])
            counts[key] += 1
            r["transaction_id"] = hashlib.sha256(
                "|".join([*key, str(counts[key])]).encode()
            ).hexdigest()[:16]
