"""Owner commands. Examples:
    python3 -m kaspion.cli recategorize "וולט" groceries
    python3 -m kaspion.cli set-budget restaurants 1800
    python3 -m kaspion.cli add "פלאפל בשוק" 45 restaurants --date 2026-07-02
    python3 -m kaspion.cli remove <transaction_id>
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime

from kaspion.ai.providers import VALID_CATEGORIES
from kaspion.db import connect


def recategorize(merchant: str, category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise SystemExit(f"unknown category: {category}. valid: {', '.join(VALID_CATEGORIES)}")
    con = connect()
    # normalize exactly like stg_transactions.merchant_key
    key = con.execute(
        r"SELECT trim(regexp_replace(regexp_replace(lower(trim(?)), '\s+\d+$', ''), '\s+', ' ', 'g'))",
        [merchant],
    ).fetchone()[0]
    con.execute(
        """
        INSERT INTO state.merchant_overrides (merchant_key, category_id, updated_at)
        VALUES (?, ?, now())
        ON CONFLICT (merchant_key) DO UPDATE
            SET category_id = excluded.category_id, updated_at = now()
        """,
        [key, category],
    )
    con.close()
    print(f"override saved: '{key}' -> {category}. run `python3 sync.py --skip-categorize` to rebuild.")


def set_budget(category: str, amount: float) -> None:
    if category not in VALID_CATEGORIES:
        raise SystemExit(f"unknown category: {category}. valid: {', '.join(VALID_CATEGORIES)}")
    con = connect()
    con.execute(
        """
        INSERT INTO state.budgets (category_id, monthly_amount_ils)
        VALUES (?, ?)
        ON CONFLICT (category_id) DO UPDATE SET monthly_amount_ils = excluded.monthly_amount_ils
        """,
        [category, amount],
    )
    con.close()
    print(f"budget set: {category} = ₪{amount:,.0f}/month")


def add_transaction(
    description: str, amount: float, category: str = "other", date_str: str | None = None
) -> str:
    """Manually add an expense (positive amount in = negative outflow stored).
    Survives syncs: lives in raw.transactions with source='manual'."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    posted = date_str or date.today().isoformat()
    datetime.strptime(posted, "%Y-%m-%d")  # validate
    txn_id = hashlib.sha256(
        f"manual|{posted}|{description}|{amount}|{datetime.now().isoformat()}".encode()
    ).hexdigest()[:16]
    con = connect()
    con.execute(
        """
        INSERT INTO raw.transactions
            (transaction_id, account_id, account_type, posted_date,
             amount, currency, raw_description, source)
        VALUES (?, 'manual', 'bank', ?, ?, 'ILS', ?, 'manual')
        """,
        [txn_id, posted, -abs(amount), description],
    )
    con.close()
    if category != "other":
        recategorize(description, category)
    return txn_id


def reset_sample_data() -> None:
    """Remove the synthetic seed data + its AI proposals — run before first real scrape.
    (Cross-platform replacement for the old shell one-liner.)"""
    con = connect()
    con.execute("DELETE FROM raw.transactions WHERE source = 'seed'")
    con.execute("DELETE FROM state.ai_proposals")
    con.close()
    print("sample data removed. next: python3 sync.py --source scraper")


def remove_transaction(txn_id: str) -> None:
    """Hide a transaction from all spend numbers (works for scraped rows too —
    actual deletion would just re-import on the next sync)."""
    con = connect()
    con.execute(
        """
        INSERT INTO state.excluded_transactions (transaction_id)
        VALUES (?) ON CONFLICT (transaction_id) DO NOTHING
        """,
        [txn_id],
    )
    con.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="kaspion")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recategorize", help="correct a merchant's category (remembered forever)")
    r.add_argument("merchant")
    r.add_argument("category")
    b = sub.add_parser("set-budget", help="set a monthly budget for a category")
    b.add_argument("category")
    b.add_argument("amount", type=float)
    a = sub.add_parser("add", help="manually add an expense")
    a.add_argument("description")
    a.add_argument("amount", type=float)
    a.add_argument("category", nargs="?", default="other")
    a.add_argument("--date", dest="date_str", default=None, help="YYYY-MM-DD (default: today)")
    x = sub.add_parser("remove", help="hide a transaction from all totals")
    x.add_argument("transaction_id")
    sub.add_parser("reset-sample-data", help="delete the synthetic seed data before going real")
    args = p.parse_args()
    if args.cmd == "recategorize":
        recategorize(args.merchant, args.category)
    elif args.cmd == "set-budget":
        set_budget(args.category, args.amount)
    elif args.cmd == "add":
        txn_id = add_transaction(args.description, args.amount, args.category, args.date_str)
        print(f"added ({txn_id}). run `python3 sync.py --skip-categorize` to rebuild.")
    elif args.cmd == "remove":
        remove_transaction(args.transaction_id)
        print("hidden. run `python3 sync.py --skip-categorize` to rebuild.")
    elif args.cmd == "reset-sample-data":
        reset_sample_data()


if __name__ == "__main__":
    main()
