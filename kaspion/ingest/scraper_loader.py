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
    failures: list[str] = []
    succeeded = 0
    for company, cfg in creds.items():
        # never let one bank's outage throw away another's data: a failure here is
        # reported and skipped, and whatever did scrape still gets ingested below.
        try:
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
            rows = json.loads(proc.stdout)
        except subprocess.CalledProcessError as e:
            # stderr is the scraper's own {error, message} json — never contains credentials
            failures.append(f"{company}: {(e.stderr or '').strip()[:200] or 'scraper failed'}")
            continue
        except json.JSONDecodeError:
            failures.append(f"{company}: scraper returned unreadable output")
            continue
        print(f"      · {company}: {len(rows)} transactions")
        succeeded += 1
        all_rows.extend(rows)

    for f in failures:
        print(f"      ⚠ {f}")
    # Only a total wipe-out is fatal. Keying this off `all_rows` instead would abort a
    # run where one bank succeeded but legitimately had nothing new — falsely claiming
    # every institution failed, and throwing away the run this isolation exists to save.
    if failures and succeeded == 0:
        raise RuntimeError(
            "all configured institutions failed to scrape:\n  " + "\n  ".join(failures)
        )

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
