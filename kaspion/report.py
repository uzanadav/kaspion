"""Generate dashboard.html — a self-contained, interactive, Hebrew-RTL family finance app.

Single file, no server, no Node, no frameworks. Layout: fixed sidebar navigation
(bottom bar on mobile) with five views — overview, categories, transactions, trends,
trips (a named date range: what a holiday cost).
All months' data is embedded as JSON; vanilla JS renders everything:
  * sidebar switches views
  * header arrows / trend bars switch month
  * clicking a category filters transactions (and jumps to that view)
  * sortable transactions table (click any column header)
  * live search
Run: python3 -m kaspion.report  (also runs automatically at the end of sync.py)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from kaspion.db import connect
from kaspion.ingest.crypto import (
    COMPANY_FIELDS,
    CRED_FILE,
    FIELD_LABELS,
    company_of,
    load_credentials,
)
from kaspion.insights import build_insights, merchant_label
from kaspion.paths import report_path

OUT = report_path()

HEB_MONTHS = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]


def _label(key: str) -> str:
    y, m = key.split("-")
    return f"{HEB_MONTHS[int(m)]} {y}"


def _flag_months(ordered: list[dict], current_key: str) -> None:
    """Stamp every month with the flags the charts read. In place; no database, so it is
    testable from synthetic dicts the way insights.py is."""
    for i, m in enumerate(ordered):
        m["isCurrent"] = m["key"] == current_key
        # a month still ahead of us holds nothing but future-dated installments and card
        # charges — real rows, but not money that has left yet, so no chart may draw them
        # as spending that already happened
        m["isFuture"] = m["key"] > current_key
        # the day this month's data actually starts. t[0] is 'YYYY-MM-DD'.
        m["firstDay"] = min((int(t[0][8:10]) for t in m["txns"]), default=0)
        # "a whole month of data" — safe to draw solid and to compare against. Only the
        # FIRST month can be cut short by when data collection started; a later month with
        # a quiet start is complete, just quiet. Deliberately NOT insights._finished(),
        # which asks a different question (enough rows to be worth comparing) and answers
        # it differently.
        m["complete"] = (not m["isCurrent"] and not m["isFuture"]
                         and (i > 0 or 0 < m["firstDay"] <= 3))
        m["pace"] = round(m["budget"] - m["spent"], 2)
        m["saved"] = round(m["income"] - m["spent"], 2)


def _destinations(months: list[dict], cur_key: str, top: int = 10) -> list[dict]:
    """Where the money actually went, across the whole history.

    Grouped by DISPLAY LABEL rather than by merchant_key, so one series of checks lands on
    one bar instead of four — but the raw keys ride along, because the drill-down filters
    the transactions table by merchant_key and has to match every row in the family.
    """
    agg: dict[str, dict] = {}
    for m in months:
        if m["key"] > cur_key:            # a future-dated installment has not been spent yet
            continue
        for t in m["txns"]:
            # t[7] category_id, t[10] is_income, t[4] abs(amount), t[11] merchant_key.
            # is_income is `amount > 0`, so it does NOT catch a negative row filed under
            # 'income' (a PAYBOX reversal, a card fee). fct_budget_pacing leaves those out
            # of `spent`; leaving them in here would total more than the month above it.
            if t[10] or t[7] == "income":
                continue
            label = merchant_label(t[11])
            d = agg.setdefault(label, {"label": label, "total": 0.0, "keys": []})
            d["total"] += t[4]
            if t[11] not in d["keys"]:
                d["keys"].append(t[11])
    out = sorted(agg.values(), key=lambda d: -d["total"])[:top]
    for d in out:
        d["total"] = round(d["total"], 2)
    return out


def _connected() -> list[dict]:
    # one entry per CONNECTION (a company can have several — two Max logins for two
    # family members), never credential values, only ids the picker groups/labels with.
    if not CRED_FILE.exists():
        return []
    try:
        creds = load_credentials()
    except Exception:  # noqa: BLE001 - an unreadable/corrupt blob just shows as "none saved"
        return []
    return sorted(
        ({"id": k, "company": company_of(k), "label": v.get("label") or ""}
         for k, v in creds.items()),
        key=lambda c: c["id"],
    )


def _collect() -> dict:
    con = connect()
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731

    pacing = q("""
        select strftime(p.posted_month, '%Y-%m'), c.name_he, p.actual_ils, p.budget_ils,
               p.pace_status, p.category_id, p.budget_is_suggested
        from main.fct_budget_pacing p join main.dim_category c using (category_id)
        where p.category_id != 'income'
        order by p.actual_ils desc
    """)
    # The list shows money BOTH ways, so it comes from int_categorized rather than
    # fct_spend (outflows only). The exclusions are kept identical to fct_spend's, or
    # the page would show transfers and card debits the totals deliberately leave out.
    txns = q("""
        select strftime(t.posted_month, '%Y-%m'), strftime(t.posted_date, '%Y-%m-%d'),
               strftime(t.posted_date, '%d.%m'), t.raw_description, c.name_he, abs(t.amount),
               case t.category_source when 'ai' then '🤖' when 'override' then '✅' else '❔' end,
               t.transaction_id, t.category_id,
               -- account_id is '<issuer>-<last digits>' (e.g. 'max-1234'); the prefix is
               -- the institution the charge came from, which the UI badges per row
               split_part(t.account_id, '-', 1) as issuer,
               t.account_id,
               case when t.amount > 0 then 1 else 0 end as is_income,
               -- normalized in stg_transactions (branch digits stripped): the only stable
               -- merchant identity, needed to spot recurring charges and first-time ones
               t.merchant_key,
               -- t[12]/t[13]: this row is half of a charge<->refund pair, and which half.
               -- Both stay in the list (hiding a real transaction is worse than showing a
               -- marked one); the badge is what tells the reader it cost nothing.
               case when t.is_refunded then 1 else 0 end,
               case when t.is_refund_charge then 1 else 0 end
        from main.int_categorized t join main.dim_category c using (category_id)
        where not t.is_transfer
          and not t.is_card_payment
          and t.transaction_id not in (select transaction_id from state.excluded_transactions)
        order by t.posted_date desc
    """)
    categories = q("""
        select category_id, name_he, is_custom from main.dim_category
        where category_id != 'income' order by name_he
    """)
    # Same exclusions as the transactions list and fct_spend. Without the
    # excluded_transactions filter, hiding a bogus inflow with 🗑 would remove it from
    # the list while leaving it inside "הכנסות", the savings figure and the banner —
    # with no way for the household to correct the number.
    # freshness per data source: which accounts are up to date and which have gone
    # stale is otherwise invisible — a scraper that quietly stopped working looks
    # exactly like a month with no spending.
    sources = q("""
        select source,
               min(account_id),
               count(*),
               strftime(min(posted_date), '%d.%m.%Y'),
               strftime(max(posted_date), '%d.%m.%Y'),
               strftime(max(ingested_at), '%d.%m.%Y %H:%M'),
               -- staleness measured against the newest transaction that has actually
               -- happened: statements carry future-dated rows (a September installment,
               -- a card charge dated ahead), and those would otherwise mask a dead feed
               coalesce(date_diff('day',
                   max(case when posted_date <= current_date then posted_date end),
                   current_date), 999)
        from raw.transactions
        group by 1 order by 1
    """)
    income = q("""
        select strftime(date_trunc('month', posted_date), '%Y-%m'), sum(amount)
        from main.int_categorized
        where amount > 0
          and not is_transfer
          and not is_card_payment
          -- the credit half of a refund pair: money coming back, not money earned. A
          -- ₪40 דמי מנוי refunded two days later read as ₪40 of income and inflated the
          -- savings figure from both directions at once.
          and not is_refunded
          and transaction_id not in (select transaction_id from state.excluded_transactions)
        group by 1
    """)
    # trips: named date ranges the household adds from the dashboard. Which rows belong
    # to one is derived in the browser from posted_date, never stored — so a charge that
    # arrives after the trip was created still counts.
    trips = q("""
        select trip_id, name, country, strftime(start_date, '%Y-%m-%d'),
               strftime(end_date, '%Y-%m-%d')
        from state.trips order by start_date desc
    """)
    trip_excl = q("select trip_id, transaction_id from state.trip_exclusions")
    con.close()

    months: dict[str, dict] = {}

    def month(key: str) -> dict:
        return months.setdefault(
            key, {"key": key, "label": _label(key), "spent": 0.0, "budget": 0.0,
                  "income": 0.0, "cats": [], "txns": []}
        )

    for key, name, actual, budget, status, cat_id, suggested in pacing:
        m = month(key)
        actual, budget = float(actual), float(budget or 0)
        m["spent"] += actual
        m["budget"] += budget
        m["cats"].append({
            "id": cat_id, "name": name, "actual": actual, "budget": budget,
            "status": status, "suggested": bool(suggested),
        })

    for (key, iso, d, desc, cat, amt, src, txn_id, cat_id, issuer, account, is_income,
         mkey, refunded, refund_charge) in txns:
        month(key)["txns"].append(
            [iso, d, desc, cat, float(amt), src, txn_id, cat_id, issuer, account,
             int(is_income), mkey, int(refunded), int(refund_charge)]
        )

    for key, inc in income:
        if key in months:
            months[key]["income"] = float(inc)

    out_sources = [{"src": s, "account": a, "n": n, "from": f, "to": t,
                    "loaded": ld, "staleDays": int(sd)}
                   for s, a, n, f, t, ld, sd in sources]

    ordered = [months[k] for k in sorted(months)]
    now = datetime.now()
    current_key = now.strftime("%Y-%m")
    _flag_months(ordered, current_key)
    # isracard/oneZero can only ever arrive as an uploaded file (reCAPTCHA / 2FA), so
    # their row must not read as a sync that keeps failing. Lowercased: the source string
    # in raw.transactions is 'onezero', the institution id is 'oneZero'.
    blocked = {k.lower() for k, v in COMPANY_FIELDS.items() if v.get("blocked")}
    for src in out_sources:
        src["upload"] = src["src"].lower() in blocked

    return {
        "months": ordered,
        # computed in Python, never by a model: figures must be exact
        "insights": build_insights(ordered, current_key),
        # top spend destinations, all-time. Python because the check/reference collapsing
        # lives in insights.py and must not be reimplemented in JS out of sync with it.
        "destinations": _destinations(ordered, current_key),
        "categories": [{"id": c, "name": n, "custom": bool(x)} for c, n, x in categories],
        "trips": [{"id": i, "name": n, "country": c, "start": s, "end": e,
                   "excluded": [x for t, x in trip_excl if t == i]}
                  for i, n, c, s, e in trips],
        "sources": out_sources,
        # what the "add account" dialog can offer, and which connections already exist
        # (one company can have several). Connection ids + labels only — never
        # credential values, which are already visible in "sources" only as an
        # account label, never a secret.
        "institutions": [
            {"id": k, "label": v["label"], "type": v["type"], "blocked": v.get("blocked"),
             "fields": [{"name": f, "label": FIELD_LABELS.get(f, f),
                         "secret": "password" in f.lower()} for f in v["fields"]]}
            for k, v in COMPANY_FIELDS.items()
        ],
        "connected": _connected(),
        "generated": now.strftime("%d.%m.%Y %H:%M"),
        # the day the running month's pace line stops at. Baked in rather than read from
        # the browser clock: the page is a static snapshot, so the cut must be one too —
        # otherwise opening August's file in September clips August at the 3rd.
        "curDay": now.day,
        "startKey": (current_key if current_key in months
                     else (ordered[-1]["key"] if ordered else "")),
    }


ASSETS = Path(__file__).resolve().parent / "assets"


def build_report() -> Path:
    data = _collect()
    # Structure first, DATA last — and never the other way round. The payload is real
    # transaction text from the bank; substituting it before the __CSS__/__JS__ sentinels
    # would let a merchant name that happened to contain "__JS__" rewrite the page.
    # Inserting it last makes the data inert by construction.
    html = (ASSETS / "app.html").read_text(encoding="utf-8")
    html = html.replace("__CSS__", (ASSETS / "app.css").read_text(encoding="utf-8").rstrip("\n"))
    html = html.replace("__JS__", (ASSETS / "app.js").read_text(encoding="utf-8").rstrip("\n"))
    html = html.replace("__GENERATED__", data["generated"])
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(f"dashboard written -> {build_report()}")
