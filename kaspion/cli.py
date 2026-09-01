"""Owner commands. Examples:
    python3 -m kaspion.cli recategorize "וולט" groceries
    python3 -m kaspion.cli set-budget restaurants 1800
    python3 -m kaspion.cli add "פלאפל בשוק" 45 restaurants --date 2026-07-02
    python3 -m kaspion.cli remove <transaction_id>
"""
from __future__ import annotations

import argparse
import hashlib
import re
from datetime import date, datetime

from kaspion.ai.providers import VALID_CATEGORIES, valid_categories
from kaspion.db import connect


def recategorize(merchant: str, category: str) -> None:
    allowed = valid_categories()
    if category not in allowed:
        # ValueError, never SystemExit: this runs inside the dashboard server too, and
        # SystemExit is a BaseException that escapes its `except Exception` and takes
        # the whole server down (reachable from a stale tab posting a deleted category)
        raise ValueError(f"unknown category: {category}. valid: {', '.join(allowed)}")
    con = connect()
    # normalize exactly like stg_transactions.merchant_key
    key = con.execute(
        r"SELECT trim(regexp_replace(regexp_replace(lower(trim(?)), "
        r"'\s+\d+$', ''), '\s+', ' ', 'g'))",
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
    print(f"override saved: '{key}' -> {category}. "
          "run `python3 sync.py --skip-categorize` to rebuild.")


# 'other' is the fallback every uncategorized row lands on and 'income' is how
# inflows are labelled — both are referenced by the SQL, so neither may be removed.
STRUCTURAL_CATEGORIES = {"other", "income"}


def add_category(category_id: str, name_he: str) -> None:
    """Add a household category. Stored in state.categories, so dbt never wipes it."""
    category_id = (category_id or "").strip().lower()
    name_he = (name_he or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,29}", category_id):
        raise ValueError(
            "מזהה קטגוריה חייב להיות באנגלית קטנה, ספרות או קו תחתון (למשל: pets)"
        )
    if not name_he:
        raise ValueError("צריך שם לקטגוריה")
    # check the seed CSV rather than main.dim_category: dim_category's is_custom column
    # only exists after a dbt build, and nothing on the add path guarantees one has run
    if category_id in VALID_CATEGORIES:
        raise ValueError(f"הקטגוריה '{category_id}' כבר קיימת ברשימה המובנית")
    con = connect()
    con.execute(
        """
        INSERT INTO state.categories (category_id, name_he) VALUES (?, ?)
        ON CONFLICT (category_id) DO UPDATE SET name_he = excluded.name_he
        """,
        [category_id, name_he],
    )
    con.close()


def delete_category(category_id: str) -> int:
    """Remove an owner-added category. Returns how many merchants were moved.

    Anything still pointing at it is reassigned to 'other' FIRST: a transaction left
    referencing a category that no longer exists would break the relationships test
    between fct_spend and dim_category and fail the whole build.
    """
    category_id = (category_id or "").strip().lower()
    if category_id in STRUCTURAL_CATEGORIES:
        raise ValueError(f"אי אפשר למחוק את '{category_id}' — המערכת משתמשת בה")
    con = connect()
    custom = con.execute(
        "SELECT count(*) FROM state.categories WHERE category_id = ?", [category_id]
    ).fetchone()[0]
    if not custom:
        con.close()
        raise ValueError("אפשר למחוק רק קטגוריות שהוספתם — הקטגוריות המובנות קבועות")
    moved = con.execute(
        "SELECT count(*) FROM state.merchant_overrides WHERE category_id = ?", [category_id]
    ).fetchone()[0]
    con.execute(
        "UPDATE state.merchant_overrides SET category_id = 'other' WHERE category_id = ?",
        [category_id],
    )
    con.execute(
        "UPDATE state.ai_proposals SET proposed_category_id = 'other' "
        "WHERE proposed_category_id = ?",
        [category_id],
    )
    con.execute("DELETE FROM state.budgets WHERE category_id = ?", [category_id])
    con.execute("DELETE FROM state.categories WHERE category_id = ?", [category_id])
    con.close()
    return moved


# ---------- trips: a named date range, for "what did the holiday cost?" ----------

def trip_row(name: str, country: str, start: str, end: str) -> dict:
    """Validate a trip and mint its id. Pure — no database, so it is testable directly.

    Hebrew messages: they are shown as-is in the dashboard.
    """
    name = (name or "").strip()[:60]
    country = (country or "").strip()[:60]
    if not name:
        raise ValueError("צריך שם לטיול")
    try:
        # exactly what an <input type="date"> submits
        s_date, e_date = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise ValueError("תאריך לא תקין") from None
    if e_date < s_date:
        raise ValueError("תאריך הסיום חייב להיות אחרי תאריך היציאה")
    # content-derived, same scheme as db.assign_natural_ids(): re-adding the same trip
    # updates it in place instead of leaving two identical pills on the page
    trip_id = hashlib.sha256(f"{name}|{s_date}|{e_date}".encode()).hexdigest()[:12]
    return {"trip_id": trip_id, "name": name, "country": country,
            "start_date": s_date.isoformat(), "end_date": e_date.isoformat()}


def add_trip(name: str, country: str, start: str, end: str) -> str:
    t = trip_row(name, country, start, end)
    con = connect()
    con.execute(
        """
        INSERT INTO state.trips (trip_id, name, country, start_date, end_date)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (trip_id) DO UPDATE SET name = excluded.name, country = excluded.country
        """,
        [t["trip_id"], t["name"], t["country"], t["start_date"], t["end_date"]],
    )
    con.close()
    return t["trip_id"]


def delete_trip(trip_id: str) -> None:
    """Remove a trip and the per-row exclusions that only made sense inside it."""
    if not trip_id:
        raise ValueError("missing trip id")
    con = connect()
    con.execute("DELETE FROM state.trip_exclusions WHERE trip_id = ?", [trip_id])
    con.execute("DELETE FROM state.trips WHERE trip_id = ?", [trip_id])
    con.close()


def toggle_trip_exclusion(trip_id: str, transaction_id: str) -> bool:
    """Flip whether one row counts towards this trip. Returns the new excluded state.

    Scoped to the trip: the row stays in every other figure on the dashboard, unlike
    state.excluded_transactions which hides it everywhere.
    """
    if not trip_id or not transaction_id:
        raise ValueError("missing trip or transaction id")
    con = connect()
    excluded = con.execute(
        "SELECT count(*) FROM state.trip_exclusions WHERE trip_id = ? AND transaction_id = ?",
        [trip_id, transaction_id],
    ).fetchone()[0]
    if excluded:
        con.execute(
            "DELETE FROM state.trip_exclusions WHERE trip_id = ? AND transaction_id = ?",
            [trip_id, transaction_id],
        )
    else:
        con.execute(
            "INSERT INTO state.trip_exclusions (trip_id, transaction_id) VALUES (?, ?)",
            [trip_id, transaction_id],
        )
    con.close()
    return not excluded


def set_budget(category: str, amount: float) -> None:
    allowed = valid_categories()
    if category not in allowed:
        # ValueError, never SystemExit: this runs inside the dashboard server too, and
        # SystemExit is a BaseException that escapes its `except Exception` and takes
        # the whole server down (reachable from a stale tab posting a deleted category)
        raise ValueError(f"unknown category: {category}. valid: {', '.join(allowed)}")
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
    if category not in valid_categories():
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


def init() -> None:
    """Prepare a brand-new installation: empty database, dbt models, empty dashboard.
    Idempotent — safe to re-run on an existing install."""
    from kaspion.paths import data_dir
    from kaspion.pipeline import run_dbt
    from kaspion.report import build_report

    data_dir().mkdir(parents=True, exist_ok=True)
    connect().close()          # lays down the DDL (schemas + tables), inserts nothing
    run_dbt()
    build_report()
    print(f"kaspion ready. data dir: {data_dir()}")


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
    sub.add_parser("init", help="prepare a new installation (empty database)")
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
    ac = sub.add_parser("add-category", help="add a household category")
    ac.add_argument("category_id", help="lowercase id, e.g. pets")
    ac.add_argument("name", help="Hebrew display name")
    dc = sub.add_parser("delete-category", help="delete a category you added")
    dc.add_argument("category_id")
    args = p.parse_args()
    if args.cmd == "init":
        init()
    elif args.cmd == "recategorize":
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
    elif args.cmd == "add-category":
        add_category(args.category_id, args.name)
        print(f"category added: {args.category_id}. "
              "run `python3 sync.py --skip-categorize` to rebuild.")
    elif args.cmd == "delete-category":
        moved = delete_category(args.category_id)
        print(f"category deleted ({moved} merchants moved to 'other'). rebuild to apply.")


if __name__ == "__main__":
    # the command functions raise ValueError so the dashboard server can catch them;
    # on the terminal that still has to look like a clean error, not a traceback
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
