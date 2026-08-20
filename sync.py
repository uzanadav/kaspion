"""kaspion sync: ingest -> dbt -> categorize.

Usage:
    python3 sync.py                      # real bank data, rules-only categorization (default)
    python3 sync.py --source seed        # load the 341-row synthetic demo dataset
    python3 sync.py --provider ollama    # opt in to local AI categorization (needs Ollama)
    python3 sync.py --skip-categorize    # pipeline only
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from kaspion.db import connect  # importing kaspion also makes console output UTF-8-safe
from kaspion.pipeline import run_dbt

ROOT = Path(__file__).resolve().parent
SEED_CSV = ROOT / "dbt" / "seeds" / "sample_transactions.csv"


def load_seed() -> int:
    con = connect()
    before = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    # SEED_CSV bound as a parameter, not interpolated into the SQL string: a Windows
    # path (backslashes, or an apostrophe in the username) would otherwise corrupt the
    # single-quoted literal.
    con.execute(
        """
        INSERT INTO raw.transactions
            (transaction_id, account_id, account_type, posted_date,
             amount, currency, raw_description, source)
        SELECT transaction_id, account_id, account_type, posted_date,
               amount, currency, raw_description, source
        FROM read_csv_auto(?, header=true,
                           types={'amount': 'DECIMAL(18,2)', 'posted_date': 'DATE'})
        WHERE transaction_id NOT IN (SELECT transaction_id FROM raw.transactions)
        """,
        [str(SEED_CSV)],
    )
    after = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    con.close()
    return after - before


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["seed", "scraper"], default="scraper")
    parser.add_argument("--skip-categorize", action="store_true")
    parser.add_argument(
        "--provider",
        choices=["ollama", "claude", "none"],
        default=os.environ.get("KASPION_AI_PROVIDER", "none"),
        help="AI categorization provider; default 'none' uses only the built-in "
             "merchant rules — pass 'ollama' or 'claude' to opt in to AI categorization",
    )
    args = parser.parse_args()
    os.environ["KASPION_AI_PROVIDER"] = args.provider

    t0 = time.time()
    steps = 3 if args.skip_categorize else 4
    print(f"kaspion sync · source={args.source} · ai={args.provider}")

    print(f"[1/{steps}] ingesting transactions from {args.source}"
          + (" (bank scraping can take a few minutes)" if args.source == "scraper" else ""))
    if args.source == "seed":
        new = load_seed()
    else:
        from kaspion.ingest.scraper_loader import load_from_scraper

        new = load_from_scraper()
    print(f"      ✔ {new} new transactions (dedup by id — re-running is always safe), "
          f"{_total_txns()} total in the database")

    # STATUS:: lines here (and in scraper_loader.load_from_scraper) are a second,
    # curated output channel — serve.py's /api/sync reads only these, live, into the
    # dashboard's sync log. Everything else printed in this file is unchanged
    # developer/terminal output.
    print("STATUS::מעדכן את הנתונים…", flush=True)
    print(f"[2/{steps}] dbt: staging → transfer & card-payment detection → spend + budget pacing")
    run_dbt()
    print("      ✔ all models rebuilt, every data test passed "
          "(transfers net to zero, card debits excluded, ids unique...)")

    if not args.skip_categorize:
        import requests

        from kaspion.ai.categorize import categorize_new_merchants

        print("STATUS::מסווג בתי עסק חדשים…", flush=True)
        print(f"[3/{steps}] categorizing new merchants: your overrides > built-in Israeli "
              f"merchant rules > {args.provider}")
        try:
            by_rules, by_ai = categorize_new_merchants()
        except requests.exceptions.ConnectionError:
            _write_report(steps, steps)
            print("      ⚠ Ollama is not running — AI skipped (everything else is done).")
            print("        start it with `brew services start ollama`, "
                  "or fix categories in the dashboard")
            print("STATUS::✔ הסתיים — הסיווג האוטומטי דולג (Ollama לא פעיל)", flush=True)
            return
        if by_rules or by_ai:
            print(f"      ✔ {by_rules + by_ai} newly categorized: "
                  f"{by_rules} by built-in rules (free), "
                  f"{by_ai} by AI — rebuilding models with the new categories")
            run_dbt()
        else:
            print("      ✔ nothing new — every merchant is already known "
                  "(memory saved the AI call)")

    _write_report(steps, steps)
    print(f"done in {time.time() - t0:.1f}s")
    print("STATUS::✔ הסתיים", flush=True)


def _total_txns() -> int:
    con = connect()
    total = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    con.close()
    return total


def _write_report(step: int | None = None, steps: int | None = None) -> None:
    from kaspion.report import build_report

    if step:
        print(f"[{step}/{steps}] regenerating the dashboard")
    print(f"      ✔ dashboard updated: {build_report().name} — refresh the browser tab")


if __name__ == "__main__":
    main()
