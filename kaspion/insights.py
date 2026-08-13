"""Plain-Hebrew observations about the household's money.

Every figure here is COMPUTED, never generated. A local LLM was evaluated for this job and
produced confident, wrong numbers — dropped digits, wrong superlatives, invented currency —
the one failure a finance dashboard must never ship (docs/AGENT_HANDOFF.md: "Never invent
financial figures").

Pure functions: no database, no network, no imports from the rest of kaspion. The whole
module is testable from synthetic dicts, and the dashboard still works from file://.

Two rules run through all of it:
  1. The current month is INCOMPLETE. Comparing 13 days against a finished month always
     reads "spending is down". Spend only grows, so "already more than" stays true once
     true, while "less than" is not yet knowable — two-sided comparisons use finished
     months instead. This is the same trap that was removed from fct_budget_pacing.
  2. income == 0 means the data was never loaded, not that nothing was earned (report.py
     already renders 'לא נטענו הכנסות'). Those months are left out of income insights.
"""
from __future__ import annotations

import re

# stg_transactions only strips a TRAILING branch/store number from merchant_key, so a
# check payment ("חיוב צק/17672/0050027/18") keeps its unique check number embedded and
# never collapses across months — every check then looks like a brand-new merchant, and
# a run of them looks like unrelated one-off vendors instead of the same recurring payee.
_REFERENCE_NOISE = re.compile(r"צ.?קים|צק/|(\d{2,}[/\-]){2,}\d")


def _is_real_merchant(key: str) -> bool:
    return bool(key) and not _REFERENCE_NOISE.search(key)


# A month needs this many transactions before it may be compared against: the first month
# of a fresh install starts mid-month with one source connected, and averaging against it
# manufactures a "record" out of an artifact.
MIN_TXNS = 10
# Percentage claims need a base worth mentioning, or ₪5 -> ₪20 shouts "+300%".
MIN_BASE_ILS = 150.0
MIN_DELTA_ILS = 100.0


def _ils(x: float) -> str:
    return f"₪{round(x):,}"


def _short(month: dict) -> str:
    """'יולי 2026' -> 'יולי' — the year is noise inside a sentence."""
    return month["label"].split()[0]


def _finished(months: list[dict], cur_key: str) -> list[dict]:
    """Months that are over AND carry enough data to compare. Ascending."""
    return [m for m in months if m["key"] < cur_key and len(m["txns"]) >= MIN_TXNS]


def _cat_in(month: dict, cat_id: str) -> float:
    for c in month["cats"]:
        if c["id"] == cat_id:
            return c["actual"]
    return 0.0


# --- Tier 1: need only the current month -----------------------------------------

def _concentration(cur: dict) -> dict | None:
    spent = [c for c in cur["cats"] if c["actual"] > 0]
    if len(spent) < 4 or cur["spent"] <= 0:
        return None
    top = sorted(spent, key=lambda c: -c["actual"])[:3]
    share = sum(c["actual"] for c in top) / cur["spent"] * 100
    if share < 50:  # not concentrated enough to be worth a line
        return None
    return {"kind": "concentration", "tone": "neutral", "score": 45 + share / 10,
            "link": {"view": "cats", "month": cur["key"]},
            "text": f"{round(share)}% מההוצאות החודש מרוכזים בשלוש קטגוריות: "
                    + ", ".join(c["name"] for c in top)}


def _budget_roundup(cur: dict) -> dict | None:
    with_budget = [c for c in cur["cats"] if c["budget"] > 0]
    over = [c for c in with_budget if c["status"] == "over"]
    if not over or not with_budget:
        return None
    total = sum(c["actual"] - c["budget"] for c in over)
    if total < MIN_DELTA_ILS:
        return None
    return {"kind": "budget_roundup", "tone": "bad", "score": 70 + len(over),
            "link": {"view": "cats", "month": cur["key"]},
            "text": f"{len(over)} מתוך {len(with_budget)} קטגוריות מעל התקציב — "
                    f"{_ils(total)} חריגה מצטברת"}


def _uncategorized(cur: dict) -> dict | None:
    # '❔' is what report.py renders when a row has neither an AI proposal nor an override
    rows = [t for t in cur["txns"] if t[5] == "❔" and not t[10]]
    if len(rows) < 5:
        return None
    return {"kind": "uncategorized", "tone": "neutral", "score": 40 + len(rows) / 10,
            "link": {"view": "txns", "month": cur["key"], "uncat": True,
                     "label": "תנועות שלא סווגו"},
            "text": f"{len(rows)} תנועות עדיין לא סווגו ({_ils(sum(t[4] for t in rows))}) — "
                    f"סיווג שלהן ידייק את התקציבים"}


# --- Tier 2: need finished months -------------------------------------------------

def _recurring(months: list[dict], cur_key: str) -> dict | None:
    """Merchants charging in >=2 months at a stable amount — subscription creep is
    invisible per charge and obvious per year."""
    per_merchant: dict[str, dict[str, float]] = {}
    for m in months:
        if m["key"] > cur_key:
            continue
        for t in m["txns"]:
            if t[10] or not _is_real_merchant(t[11]):   # skip income and reference-number rows
                continue
            per_merchant.setdefault(t[11], {}).setdefault(m["key"], 0.0)
            per_merchant[t[11]][m["key"]] += t[4]

    monthly, keys = 0.0, []
    for key, by_month in per_merchant.items():
        if len(by_month) < 2:
            continue
        vals = sorted(by_month.values())
        # a real subscription bills about the same every month; a merchant simply visited
        # twice for different amounts is not a fixed charge
        if vals[0] <= 0 or vals[-1] > vals[0] * 1.15:
            continue
        monthly += vals[len(vals) // 2]
        keys.append(key)          # kept so the drill-down can show exactly these merchants
    if len(keys) < 3 or monthly < MIN_BASE_ILS:
        return None
    return {"kind": "recurring", "tone": "neutral", "score": 85,
            # Lands on the CURRENT month — "what am I paying now". The headline is a
            # cross-month median, so a merchant that has not billed yet this month will
            # not appear; the chip names the filter, so the table reads as "these
            # merchants" rather than as a restatement of the monthly total.
            "link": {"view": "txns", "month": cur_key, "merchants": keys,
                     "label": "חיובים קבועים"},
            "text": f"{len(keys)} חיובים קבועים חוזרים כל חודש — {_ils(monthly)} בחודש, "
                    f"{_ils(monthly * 12)} בשנה"}


def _mom_totals(cur: dict | None, finished: list[dict]) -> dict | None:
    # The running month may only be reported once it has ALREADY passed last month —
    # that can never reverse. "Spending less" is unknowable until the month closes.
    if cur and finished:
        delta = cur["spent"] - finished[-1]["spent"]
        if delta >= MIN_DELTA_ILS:
            return {"kind": "mom_totals", "tone": "bad", "score": 80,
                    "link": {"view": "txns", "month": cur["key"]},
                    "text": f"כבר הוצאתם {_ils(delta)} יותר מאשר בכל {_short(finished[-1])}"}
    if len(finished) >= 2:
        prev, last = finished[-2], finished[-1]
        delta = last["spent"] - prev["spent"]
        if abs(delta) < MIN_DELTA_ILS:
            return None
        return {"kind": "mom_totals", "tone": "bad" if delta > 0 else "good", "score": 50,
                "link": {"view": "txns", "month": last["key"]},
                "text": f"ב{_short(last)} הוצאתם {_ils(abs(delta))} "
                        f"{'יותר' if delta > 0 else 'פחות'} מאשר ב{_short(prev)}"}
    return None


def _category_move(finished: list[dict]) -> dict | None:
    """Biggest mover in the LAST FINISHED month against its own earlier average.
    Deliberately not the current month: a partial month can only ever be honestly
    described as 'already above', never as 'below'."""
    if len(finished) < 3:
        return None
    target, before = finished[-1], finished[:-1]
    best = None
    for c in target["cats"]:
        history = [_cat_in(m, c["id"]) for m in before]
        avg = sum(history) / len(history)
        if avg < MIN_BASE_ILS:
            continue
        delta = c["actual"] - avg
        if abs(delta) < MIN_DELTA_ILS:
            continue
        pct = abs(delta) / avg * 100
        if best is None or pct > best[0]:
            best = (pct, c, delta)
    if best is None:
        return None
    pct, c, delta = best
    return {"kind": "category_move", "tone": "bad" if delta > 0 else "good",
            "score": 60 + min(pct, 100) / 10,
            "link": {"view": "txns", "month": target["key"], "cat": c["name"]},
            "text": f"{c['name']} ב{_short(target)}: {_ils(c['actual'])} — "
                    f"{round(pct)}% {'מעל' if delta > 0 else 'מתחת'} לממוצע שלכם"}


def _new_merchant(cur: dict | None, finished: list[dict], cur_key: str) -> dict | None:
    # with no prior baseline every merchant is technically "new" — true but meaningless,
    # so this needs an established history before "new" means anything
    if not cur or len(finished) < 2:
        return None
    seen = {t[11] for m in finished for t in m["txns"] if not t[10]}
    fresh: dict[str, list] = {}
    for t in cur["txns"]:
        if t[10] or not _is_real_merchant(t[11]) or t[11] in seen:
            continue
        row = fresh.setdefault(t[11], [0.0, t[2]])
        row[0] += t[4]
    if not fresh:
        return None
    total, name = max(fresh.values(), key=lambda r: r[0])
    if total < MIN_DELTA_ILS:
        return None
    return {"kind": "new_merchant", "tone": "neutral", "score": 75,
            "link": {"view": "txns", "month": cur["key"], "merchants": list(fresh),
                     "label": "מקורות הוצאה חדשים"},
            "text": f"{len(fresh)} מקורות הוצאה חדשים החודש — הגדול שבהם: {name} ({_ils(total)})"}


# --- Tier 3: need real history ----------------------------------------------------

def _income_record(months: list[dict], cur_key: str) -> dict | None:
    # income == 0 means "not loaded", so those months cannot hold a record
    with_income = [m for m in months
                   if m["key"] < cur_key and m["income"] > 0 and len(m["txns"]) >= MIN_TXNS]
    if len(with_income) < 3:   # a "record" out of two months is a coin flip
        return None
    best = max(with_income, key=lambda m: m["income"])
    return {"kind": "income_record", "tone": "good", "score": 65,
            "link": {"view": "txns", "month": best["key"], "flow": "in"},
            "text": f"{best['label']} היה חודש ההכנסה הגבוהה ביותר — {_ils(best['income'])}"}


def _savings_streak(finished: list[dict]) -> dict | None:
    streak, total = 0, 0.0
    for m in reversed(finished):
        if m["income"] <= 0 or m["saved"] <= 0:
            break
        streak += 1
        total += m["saved"]
    if streak < 2:
        return None
    return {"kind": "savings_streak", "tone": "good", "score": 55 + streak,
            "link": {"view": "trends"},
            "text": f"{streak} חודשים ברציפות בחיסכון — {_ils(total)} סה״כ"}


def build_insights(months: list[dict], cur_key: str, limit: int = 4) -> list[dict]:
    """Ranked Hebrew observations, highest score first, at most one per kind.

    `months` is the ascending list _collect() builds; `cur_key` is 'YYYY-MM' for the
    month in progress. Returns [] rather than a weak claim when history is too thin —
    an empty strip is correct, not a bug.
    """
    if not months:
        return []
    cur = next((m for m in months if m["key"] == cur_key), None)
    finished = _finished(months, cur_key)

    found = [
        _recurring(months, cur_key),
        _mom_totals(cur, finished),
        _new_merchant(cur, finished, cur_key),
        _category_move(finished),
        _income_record(months, cur_key),
        _savings_streak(finished),
    ]
    if cur:
        found += [_budget_roundup(cur), _concentration(cur), _uncategorized(cur)]

    return sorted([i for i in found if i], key=lambda i: -i["score"])[:limit]
