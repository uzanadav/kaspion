"""Generate realistic synthetic Israeli transactions -> dbt/seeds/sample_transactions.csv.

Deliberately includes: Hebrew+English merchants, salary inflows, inter-account
transfer pairs, a partial current month, and monthly credit-card debits that
equal each card's statement sum (so card-payment detection has real work to do).
"""
from __future__ import annotations

import calendar
import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from kaspion.db import DDL, assign_natural_ids

OUT = Path(__file__).resolve().parents[2] / "dbt" / "seeds" / "sample_transactions.csv"

ACCOUNTS = {
    "leumi-main": "bank",
    "leumi-savings": "bank",
    "max-1234": "credit_card",
    "isracard-5678": "credit_card",
}
CARD_TO_BANK = {"max-1234": "leumi-main", "isracard-5678": "leumi-main"}
CARD_DEBIT_DESC = {"max-1234": "חיוב מקס איט פיננסים", "isracard-5678": "חיוב ישראכרט"}

# merchant -> (true category, typical charge range in ILS)
MERCHANTS = {
    "רמי לוי 342": ("groceries", (150, 700)),
    "שופרסל דיל": ("groceries", (80, 450)),
    "יוחננוף": ("groceries", (100, 500)),
    "וולט": ("restaurants", (60, 180)),
    "קפה גרג": ("restaurants", (30, 90)),
    "מסעדת הבשריה": ("restaurants", (150, 450)),
    "פז יעד לוד": ("transport", (150, 350)),
    "רב קו אונליין": ("transport", (30, 150)),
    "GETT": ("transport", (25, 90)),
    "חברת החשמל": ("housing", (250, 900)),
    "מי אביבים": ("housing", (80, 250)),
    "ארנונה תל אביב": ("housing", (400, 700)),
    "סופר פארם": ("health", (40, 250)),
    "מכבי שירותי בריאות": ("health", (50, 150)),
    "גן ילדים פרטי": ("kids", (2500, 3500)),
    "ZARA TLV": ("clothing", (100, 500)),
    "NETFLIX.COM": ("subscriptions", (55, 55)),
    "SPOTIFY": ("subscriptions", (25, 25)),
    "iCloud": ("subscriptions", (12, 12)),
    "KSP מחשבים": ("electronics", (100, 1500)),
    "סינמה סיטי": ("entertainment", (80, 200)),
    "הפניקס ביטוח": ("insurance", (300, 600)),
}


def month_range(months_back: int) -> list[date]:
    """First-of-month dates for the last `months_back` full months, oldest first."""
    cursor = date.today().replace(day=1)
    months: list[date] = []
    for _ in range(months_back):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        months.append(cursor)
    return sorted(months)


def generate(months_back: int = 6, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    today = date.today()
    rows: list[dict] = []
    # full past months + the current partial month (so the dashboard's
    # "this month" view has data); future-dated rows are filtered at the end.
    for month_start in [*month_range(months_back), today.replace(day=1)]:
        y, m = month_start.year, month_start.month
        days_in_month = calendar.monthrange(y, m)[1]

        # salary (inflow) on the 9th
        rows.append(_row("leumi-main", date(y, m, 9), 24500.00, "משכורת חברת הייטק בעמ"))
        # rent (outflow) on the 1st
        rows.append(_row("leumi-main", date(y, m, 1), -6200.00, "שכר דירה הוראת קבע"))
        # transfer pair: main -> savings on the 10th (must net to zero downstream)
        rows.append(_row("leumi-main", date(y, m, 10), -3000.00, "העברה לחשבון חסכון"))
        rows.append(_row("leumi-savings", date(y, m, 10), 3000.00, "העברה מחשבון עוש"))

        # card spend: 40-60 charges/month spread over both cards
        card_totals: dict[str, float] = defaultdict(float)
        for _ in range(rng.randint(40, 60)):
            merchant, (_, (lo, hi)) = rng.choice(list(MERCHANTS.items()))
            card = rng.choice(list(CARD_TO_BANK))
            amount = -round(rng.uniform(lo, hi), 2)
            rows.append(_row(card, date(y, m, rng.randint(1, days_in_month)), amount, merchant))
            card_totals[card] += amount

        # card statement debit hits the bank on the 10th of NEXT month
        debit_date = (month_start + timedelta(days=40)).replace(day=10)
        for card, total in card_totals.items():
            rows.append(_row(CARD_TO_BANK[card], debit_date, round(total, 2),
                              CARD_DEBIT_DESC[card]))

    return [r for r in rows if date.fromisoformat(r["posted_date"]) <= today]


def _row(account_id: str, posted: date, amount: float, desc: str) -> dict:
    return {
        "account_id": account_id,
        "account_type": ACCOUNTS[account_id],
        "posted_date": posted.isoformat(),
        "amount": f"{amount:.2f}",
        "currency": "ILS",
        "raw_description": desc,
        "source": "seed",
    }


if __name__ == "__main__":
    import duckdb

    rows = generate()
    # a throwaway in-memory connection just to reuse assign_natural_ids's id scheme —
    # the same natural-key logic every real ingest path uses, rather than a second,
    # hand-rolled one here. Its "already in the database" check is always a no-op
    # against an empty table; what it actually buys is collapsing the astronomically
    # rare random-draw collision (same day/amount/merchant/account) to one row instead
    # of keeping both under different ids, consistent with every other ingest path.
    con = duckdb.connect(":memory:")
    con.execute(DDL)
    rows = assign_natural_ids(rows, con)
    rows.sort(key=lambda r: r["posted_date"])
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {OUT}")
