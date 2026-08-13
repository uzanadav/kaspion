"""Generate dashboard.html — a self-contained, interactive, Hebrew-RTL family finance app.

Single file, no server, no Node, no frameworks. Layout: fixed sidebar navigation
(bottom bar on mobile) with four views — overview, categories, transactions, trends.
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
from kaspion.insights import build_insights

OUT = Path(__file__).resolve().parents[1] / "dashboard.html"

HEB_MONTHS = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]


def _label(key: str) -> str:
    y, m = key.split("-")
    return f"{HEB_MONTHS[int(m)]} {y}"


def _collect() -> dict:
    con = connect(read_only=True)
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
               t.merchant_key
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
          and transaction_id not in (select transaction_id from state.excluded_transactions)
        group by 1
    """)
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

    for key, iso, d, desc, cat, amt, src, txn_id, cat_id, issuer, account, is_income, mkey in txns:
        month(key)["txns"].append(
            [iso, d, desc, cat, float(amt), src, txn_id, cat_id, issuer, account,
             int(is_income), mkey]
        )

    for key, inc in income:
        if key in months:
            months[key]["income"] = float(inc)

    ordered = [months[k] for k in sorted(months)]
    current_key = datetime.now().strftime("%Y-%m")
    for m in ordered:
        m["isCurrent"] = m["key"] == current_key
        m["pace"] = round(m["budget"] - m["spent"], 2)
        m["saved"] = round(m["income"] - m["spent"], 2)
    return {
        "months": ordered,
        # computed in Python, never by a model: figures must be exact
        "insights": build_insights(ordered, current_key),
        "categories": [{"id": c, "name": n, "custom": bool(x)} for c, n, x in categories],
        "sources": [{"src": s, "account": a, "n": n, "from": f, "to": t,
                     "loaded": ld, "staleDays": int(sd)}
                    for s, a, n, f, t, ld, sd in sources],
        "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "startKey": current_key if current_key in months else (ordered[-1]["key"] if ordered else ""),
    }


TEMPLATE = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>הכסף שלנו</title>
<style>
:root {
  /* tells the browser which native control colors (form fields, scrollbars) to use per theme */
  color-scheme: light dark;
  /* type scale */  --t1:.72rem; --t2:.82rem; --t3:.95rem; --t4:1.15rem; --t5:1.6rem; --t6:2.4rem;
  /* spacing    */  --s1:4px; --s2:8px; --s3:12px; --s4:18px; --s5:26px; --s6:38px;
  /* radius     */  --r1:10px; --r2:14px; --r3:20px;
  /* surfaces   */  --bg:#faf7f2; --surface:#ffffff; --surface-2:#f4efe7; --line:#e9e2d6;
  /* ink        */  --ink:#2f2c27; --ink-2:#6b655c; --ink-3:#989186;
  /* semantic   */  --pos:#0e9f6e; --neg:#dc2626; --warn:#ca8a04; --accent:#c9b48a;
  /* status pills (badges/banners) — tinted background + matching ink, one pair per state */
  --pos-bg:#e7f6ee; --pos-ink:#116646; --warn-bg:#fdf3e0; --warn-ink:#8a5a00;
  --neg-bg:#fdebec; --neg-ink:#a12b30;
  --shadow:0 1px 2px rgba(0,0,0,.04), 0 4px 16px rgba(0,0,0,.04);
  /* aliases kept so existing rules keep working during migration */
  --green:var(--pos); --red:var(--neg); --gray:var(--ink-3);
  --soft:var(--ink-2); --card:var(--surface); --sel:var(--surface-2);
}
/* dark: only tokens are redefined. Guarded so an explicit light choice still wins. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#131316; --surface:#1b1b1f; --surface-2:#26262c; --line:#33333b;
    --ink:#ececf0; --ink-2:#a8a5ad; --ink-3:#77747c;
    --pos:#12ad82; --neg:#e04a48; --warn:#a67c1a; --accent:#8a7b55;
    --pos-bg:rgba(18,173,130,.18); --pos-ink:#4ad9ab;
    --warn-bg:rgba(166,124,26,.22); --warn-ink:#e3b859;
    --neg-bg:rgba(224,74,72,.18); --neg-ink:#f28684;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 4px 20px rgba(0,0,0,.3);
  }
}
/* explicit toggle wins in BOTH directions */
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg:#131316; --surface:#1b1b1f; --surface-2:#26262c; --line:#33333b;
  --ink:#ececf0; --ink-2:#a8a5ad; --ink-3:#77747c;
  --pos:#12ad82; --neg:#e04a48; --warn:#a67c1a; --accent:#8a7b55;
  --pos-bg:rgba(18,173,130,.18); --pos-ink:#4ad9ab;
  --warn-bg:rgba(166,124,26,.22); --warn-ink:#e3b859;
  --neg-bg:rgba(224,74,72,.18); --neg-ink:#f28684;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 4px 20px rgba(0,0,0,.3);
}
:root[data-theme="light"] { color-scheme: light }
* { box-sizing:border-box; margin:0 }
html { font-size:17.5px }
body { font-family:-apple-system, "Segoe UI", "Heebo", Arial, sans-serif;
       background:var(--bg); color:var(--ink); padding:24px 260px 60px 36px }

/* Dates, times, ranges, amounts and account ids are LTR runs inside RTL text.
   Without isolation the bidi algorithm reorders adjacent runs — "13.08.2026 11:01"
   renders as "11:01 13.08.2026" even though the DOM text is correct. isolate is
   what stops that leak; it does not change the text, only how it lays out. */
/* text-align:end is needed alongside direction:ltr — forcing ltr on a table cell also
   flips its own start/end alignment, which would pull numbers away from their header */
.num { unicode-bidi:isolate; direction:ltr; display:inline-block; text-align:end }
.nums { font-variant-numeric:tabular-nums }

/* ---- sidebar (right rail, RTL-natural; bottom bar on mobile) ---- */
#side { position:fixed; inset-inline-start:0; top:0; bottom:0; width:224px; background:var(--card);
        border-inline-end:1px solid var(--line); padding:26px 14px; display:flex; flex-direction:column }
#side .logo { font-size:1.25rem; font-weight:800; text-align:center; margin-bottom:4px }
#side .tag  { font-size:.7rem; color:var(--soft); text-align:center; margin-bottom:26px }
#side nav { display:flex; flex-direction:column; gap:6px }
#side nav a { display:flex; align-items:center; gap:10px; padding:11px 14px; border-radius:12px;
        text-decoration:none; color:var(--ink); font-size:.95rem; cursor:pointer }
#side nav a:hover { background:var(--bg) }
#side nav a.on { background:var(--sel); font-weight:700 }
#side nav a .ico { font-size:1.15rem }
#side .foot { margin-top:auto; font-size:.68rem; color:var(--soft); text-align:center; line-height:1.7 }
#syncbtn { margin-top:18px; padding:11px; border-radius:12px; border:1px solid var(--line);
        background:var(--card); color:var(--ink); font:inherit; font-size:.9rem; cursor:pointer }
#syncbtn:hover { background:var(--sel) }
#syncbtn:disabled { opacity:.55; cursor:wait }
#themebtn { margin-top:8px; padding:9px; border-radius:12px; border:1px solid transparent;
        background:none; color:var(--ink-2); font:inherit; font-size:.82rem; cursor:pointer }
#themebtn:hover { background:var(--sel); border-color:var(--line) }

/* ---- header ---- */
/* content hugs the sidebar on the right instead of floating in the middle */
.head { display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;
        max-width:1280px; margin-inline-start:0; margin-inline-end:auto }
h1 { font-size:1.45rem }
/* month strip: every month is one tap away */
.months { display:flex; gap:7px; max-width:1280px; margin:0 0 20px auto; overflow-x:auto;
        padding-bottom:4px; -webkit-overflow-scrolling:touch }
.mchip { flex:none; padding:8px 16px; border-radius:20px; border:1px solid var(--line);
        background:var(--card); font:inherit; font-size:.88rem; cursor:pointer; color:var(--ink) }
.mchip:hover { background:var(--sel) }
.mchip.sel { background:var(--ink); border-color:var(--ink); color:var(--bg); font-weight:700 }
.mchip .now { display:inline-block; width:7px; height:7px; border-radius:50%;
        background:var(--green); margin-inline-start:6px; vertical-align:middle }
.sub { color:var(--soft); font-size:.85rem; max-width:1280px; margin:0 0 14px auto }
main { max-width:1280px; margin-inline-start:0; margin-inline-end:auto }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:0 22px; align-items:start }
@media (max-width:1000px) { .grid2 { grid-template-columns:1fr } }
.view { display:none } .view.on { display:block }
h2 { font-size:1.05rem; margin:26px 0 12px }
.hint { font-size:.75rem; color:var(--soft) }

/* ---- cards & banner ---- */
.cards { display:grid; grid-template-columns:repeat(3,1fr); gap:10px }
.card { background:var(--card); border:1px solid var(--line); border-radius:var(--r2);
        padding:var(--s4) var(--s3); text-align:center; box-shadow:var(--shadow) }
.card .lbl { font-size:var(--t2); color:var(--soft) }
.card .val { font-size:var(--t5); font-weight:700; margin-top:4px }
/* money coming in gets its own accent + dominant size — it's the figure the eye lands on first */
.card.in { background:linear-gradient(180deg,var(--pos-bg),var(--surface)); border-color:var(--pos-bg) }
.card.in .val { color:var(--green); font-size:var(--t6) }
.card .sub2 { font-size:.68rem; color:var(--soft); margin-top:3px; min-height:1em }
/* the pace now rides in the spend card's subline, so it needs its own colour rule —
   .good/.bad elsewhere are scoped to .val/.tsave and would not apply here */
.card .sub2 .good { color:var(--green); font-weight:600 }
.card .sub2 .bad  { color:var(--red);   font-weight:600 }
@media (max-width:900px) { .cards { grid-template-columns:repeat(2,1fr) } }
.val.good { color:var(--green) } .val.bad { color:var(--red) }
.banner { margin:14px 0 0; padding:13px 16px; border-radius:14px; font-weight:600; font-size:.95rem }
.banner.good { background:var(--pos-bg); color:var(--pos-ink) } .banner.bad { background:var(--neg-bg); color:var(--neg-ink) }
/* insight strip: short computed observations, same connected-list look as .srcgrid */
.insights { display:flex; flex-direction:column; gap:1px; background:var(--line);
        border-radius:var(--r1); overflow:hidden; border:1px solid var(--line) }
.ins { display:flex; align-items:center; gap:var(--s3); padding:var(--s2) var(--s4);
       background:var(--surface); font-size:var(--t2) }
.ins-dot { width:7px; height:7px; border-radius:50%; flex:none; background:var(--ink-3) }
.ins.good .ins-dot { background:var(--pos) }
.ins.bad .ins-dot  { background:var(--neg) }
.ins.go { cursor:pointer }
.ins.go:hover { background:var(--surface-2) }
.ins-txt { flex:1; min-width:0 }
.ins-go { color:var(--ink-3); font-size:var(--t4); flex:none }
.panel { background:var(--card); border:1px solid var(--line); border-radius:var(--r2);
        padding:var(--s4); box-shadow:var(--shadow) }

/* ---- overview: donut + legend + top5 ---- */
.split { display:grid; grid-template-columns:230px 1fr; gap:18px; align-items:center }
.donut-wrap { position:relative; width:210px; height:210px; margin:0 auto }
.donut-wrap svg { transform:rotate(-90deg) }
.donut-c { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center }
.donut-c .b { font-size:1.3rem; font-weight:800 } .donut-c .s { font-size:.72rem; color:var(--soft) }
.legend { display:flex; flex-direction:column; gap:8px }
.leg { display:flex; align-items:center; gap:9px; font-size:.88rem; cursor:pointer; padding:5px 8px; border-radius:10px }
.leg:hover { background:var(--bg) }
.leg .dot { width:11px; height:11px; border-radius:4px; flex:none }
.leg .nm { flex:1 } .leg .am { font-weight:600 }

/* ---- categories view ---- */
.cat { margin-bottom:var(--s1); padding:var(--s3); border-radius:var(--r1); cursor:pointer; transition:background .15s }
.cat:hover { background:var(--bg) }
.cat-line { display:flex; justify-content:space-between; font-size:var(--t3); margin-bottom:5px }
.cat-amt small { color:var(--soft); font-weight:400 }
.sugg-tag { font-size:.62rem; font-weight:600; color:var(--warn-ink); background:var(--warn-bg);
        padding:1px 7px; border-radius:8px; margin-inline-start:6px; cursor:help }
/* progress fill anchors to the RIGHT and grows leftward (natural for Hebrew) */
.bar { height:9px; background:var(--line); border-radius:6px; overflow:hidden;
       display:flex; justify-content:flex-start }
.fill { height:100%; border-radius:6px }

/* ---- trends ---- */
.trend { display:flex; gap:8px; align-items:flex-end; justify-content:space-between; padding-top:8px }
.tcol { flex:1; text-align:center; cursor:pointer }
/* the bar grows from the baseline; the income marker floats over the same scale */
.tplot { position:relative; display:flex; align-items:flex-end }
.tbar { width:100%; background:var(--accent); border-radius:6px 6px 0 0; transition:background .15s }
/* income as a rule across the column: spend below it = living within your means */
.tinc { position:absolute; inset-inline:0; border-top:2px dashed var(--green);
        pointer-events:none }
/* .over = spent more than came in that month */
.tinc.over { border-top-color:var(--red) }
.tinc span { position:absolute; inset-inline-end:2px; top:-13px; font-size:.6rem;
        font-weight:600; color:var(--green); background:var(--card); padding:0 3px;
        border-radius:4px }
.tinc.over span { color:var(--red) }
.tcol:hover .tbar { background:var(--ink-3) }
.tcol.sel .tbar { background:var(--green) }
.tval { font-size:.62rem; color:var(--soft); margin-bottom:3px }
.tlab { font-size:.72rem; color:var(--soft); margin-top:5px }
.tcol.sel .tlab { color:var(--green); font-weight:700 }
/* what the month actually kept: the gap between the income rule and the bar.
   Only rendered when income exists — a month with no income loaded would
   otherwise read as a huge overspend when it is really just missing data. */
.tsave { font-size:.78rem; font-weight:700; margin-top:2px; letter-spacing:.2px }
.tsave.good { color:var(--green) }
.tsave.bad { color:var(--red) }
.pos { color:var(--green); font-weight:600 } .neg { color:var(--red); font-weight:600 }

/* ---- per-category trend cards ---- */
.catgrid { display:grid; grid-template-columns:repeat(auto-fill, minmax(215px, 1fr)); gap:12px }
.catcard { background:var(--card); border:1px solid var(--line); border-radius:var(--r2);
        padding:var(--s3) var(--s4); cursor:pointer; transition:border-color .15s; box-shadow:var(--shadow) }
.catcard:hover { border-color:var(--accent) }
.cc-head { display:flex; justify-content:space-between; align-items:center; font-size:var(--t4); font-weight:600 }
.badge { font-size:var(--t1); font-weight:600; padding:3px 10px; border-radius:var(--r1); white-space:nowrap }
.badge.ok  { background:var(--pos-bg); color:var(--pos-ink) }
.badge.mid { background:var(--warn-bg); color:var(--warn-ink) }
.badge.bad { background:var(--neg-bg); color:var(--neg-ink) }
.cc-chart { display:flex; gap:8px; align-items:flex-start; margin-top:12px }
/* the month row lives inside the plot so it lines up with the bars automatically,
   instead of being nudged by hand to clear the axis gutter */
.cc-plot { flex:1; min-width:0; display:flex; flex-direction:column }
.cc-axis { flex:none; height:68px; position:relative; display:flex; flex-direction:column;
        justify-content:space-between; align-items:flex-end; font-size:.64rem;
        color:var(--soft); white-space:nowrap; padding:1px 0 }
/* the target reads as a third axis tick sitting exactly on the dashed line — in the
   gutter, so unlike a label inside the plot it can never be hidden behind a bar */
.cc-axis .tgt { position:absolute; inset-inline-end:0; transform:translateY(50%);
        color:var(--ink); font-weight:600; background:var(--card); padding:0 2px }
.cc-bars { height:68px; display:flex; gap:6px; align-items:flex-end; position:relative }
.mb { flex:1; max-width:24px; margin:0 auto; border-radius:4px 4px 0 0; min-height:3px }
.tline { position:absolute; inset-inline:0; border-top:2px dashed var(--ink);
        opacity:.45; pointer-events:none }
.cc-months { display:flex; gap:6px; margin-top:6px }
.cc-months span { flex:1; text-align:center; font-size:.62rem; color:var(--soft);
        overflow:hidden; white-space:nowrap }
.cc-months span.now { color:var(--ink); font-weight:700 }
.cc-now { display:flex; justify-content:space-between; align-items:baseline; gap:10px;
        font-size:.82rem; color:var(--soft); margin-top:10px }
.cc-now b { color:var(--ink); font-weight:600 }

/* ---- tables ---- */
table { width:100%; border-collapse:collapse; font-size:var(--t2) }
th { text-align:start; color:var(--soft); font-weight:500; font-size:var(--t1); padding:var(--s2) 4px;
     border-bottom:1px solid var(--line) }
th.sortable { cursor:pointer; user-select:none; white-space:nowrap }
th.sortable:hover { color:var(--ink) }
th .arr { font-size:.6rem }
td { padding:var(--s2) 4px; border-bottom:1px solid var(--line) }
tr:last-child td { border-bottom:0 }
.amt { font-weight:600; white-space:nowrap; font-variant-numeric:tabular-nums; unicode-bidi:isolate; direction:ltr; text-align:end }
.amt.in { color:var(--green) }
/* money-direction filter: one row of segmented buttons above the table */
.fseg { display:inline-flex; gap:6px; margin:0 0 10px }
.fseg button { padding:7px 16px; border:1px solid var(--line); border-radius:20px;
        background:var(--card); font:inherit; font-size:.85rem; cursor:pointer; color:var(--ink) }
.fseg button:hover { background:var(--sel) }
.fseg button.on { background:var(--ink); border-color:var(--ink); color:var(--bg); font-weight:700 }
.catname { font-size:.82rem; color:var(--soft) }
/* ---- data-source freshness: one compact row per account, not a stack of labels ---- */
.srcgrid { display:flex; flex-direction:column; gap:1px; background:var(--line);
        border-radius:var(--r1); overflow:hidden; border:1px solid var(--line) }
.srcrow { display:flex; align-items:center; gap:var(--s3); background:var(--surface);
        padding:var(--s3) var(--s4); font-size:var(--t2) }
.srcname { display:flex; align-items:center; gap:var(--s2); font-weight:600;
        font-size:var(--t3); flex:1; min-width:0 }
.srcname i { width:9px; height:9px; border-radius:50%; flex:none }
.srcrange { color:var(--ink-2) }
.srccount { color:var(--ink-2); white-space:nowrap }
.srccount b { color:var(--ink); font-weight:600 }
.srcage { font-size:var(--t1); font-weight:700; padding:2px 9px; border-radius:9px; white-space:nowrap }
.srcage.ok   { background:var(--pos-bg); color:var(--pos-ink) }
.srcage.warn { background:var(--warn-bg); color:var(--warn-ink) }
.srcage.old  { background:var(--neg-bg); color:var(--neg-ink) }
@media (max-width:640px) { .srcrow { flex-wrap:wrap } .srcrange { order:3; width:100%; margin-inline-start:24px } }
/* issuer badge: colored dot carries identity, text stays in the normal ink color */
.iss { display:inline-flex; align-items:center; gap:6px; white-space:nowrap; font-size:.82rem }
.iss i { width:9px; height:9px; border-radius:50%; flex:none }
input { width:100%; padding:10px 14px; border:1px solid var(--line); border-radius:12px;
        font:inherit; background:var(--card); color:var(--ink); margin-bottom:10px }
.chip { display:none; margin:0 0 10px; padding:7px 14px; background:var(--sel); border:1px solid var(--accent);
        border-radius:20px; font-size:.85rem; cursor:pointer }
.chip.on { display:inline-block }

/* ---- edit mode (only when served via python3 -m kaspion.serve) ---- */
.addrow { display:grid; grid-template-columns:2fr 1fr 1fr 1fr auto; gap:8px }
.addrow select, .addrow button { padding:10px 12px; border:1px solid var(--line); border-radius:12px;
        font:inherit; background:var(--card); color:var(--ink) }
.addrow button { background:var(--green); color:#fff; border:0; font-weight:700; cursor:pointer }
.addrow button:disabled { opacity:.5 }
button.del { border:0; background:none; cursor:pointer; font-size:.95rem; opacity:.45 }
button.del:hover { opacity:1 }
select.recat { padding:5px 8px; border:1px solid transparent; border-radius:9px;
        font:inherit; font-size:.82rem; background:none; color:var(--ink); cursor:pointer }
select.recat:hover, select.recat:focus { border-color:var(--line); background:var(--card) }
input.budget-edit { width:5.2em; padding:3px 6px; margin:0; border:1px solid var(--line);
        border-radius:8px; font:inherit; font-size:.82rem; text-align:center; background:var(--bg); color:var(--ink) }
input.budget-edit:focus { outline:1.5px solid var(--accent); background:var(--card) }
.uprow { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center }
#catman .uprow { grid-template-columns:2fr 1fr auto }
/* secondary tool, not a headline panel — smaller and flatter than the budget list above it */
#catman { background:var(--surface-2); box-shadow:none; font-size:var(--t2) }
/* add/upload are occasional actions, not the default view of the page — collapsed by default */
.toolbar { margin-bottom:var(--s4) }
.toolbar summary { cursor:pointer; padding:var(--s3) var(--s4); background:var(--surface-2);
        border:1px solid var(--line); border-radius:var(--r1); font-weight:600; font-size:var(--t2);
        color:var(--ink-2); list-style:none }
.toolbar summary::-webkit-details-marker { display:none }
.toolbar summary:hover { color:var(--ink) }
.toolbar[open] summary { border-radius:var(--r1) var(--r1) 0 0; margin-bottom:var(--s3) }
.ctag { display:inline-flex; align-items:center; gap:7px; background:var(--sel);
        border:1px solid var(--accent); border-radius:20px; padding:5px 12px;
        margin:0 0 6px 6px; font-size:.85rem }
.ctag button { border:0; background:none; cursor:pointer; font-size:.9rem; opacity:.55; padding:0 }
.ctag button:hover { opacity:1 }
.uprow input[type=file] { padding:9px 12px; border:1px dashed var(--line); border-radius:12px;
        font:inherit; font-size:.85rem; background:var(--bg); cursor:pointer }
.uprow button { padding:10px 18px; border:0; border-radius:12px; background:var(--green);
        color:#fff; font:inherit; font-weight:700; cursor:pointer }
.uprow button:disabled { opacity:.5 }
@media (max-width:760px) { .addrow { grid-template-columns:1fr 1fr } .uprow { grid-template-columns:1fr } }

@media (max-width:760px) {
  body { padding:18px 14px 86px }
  #side { top:auto; bottom:0; inset-inline:0; width:auto; height:64px; flex-direction:row; align-items:center;
          justify-content:space-around; padding:0; border-inline-end:0; border-top:1px solid var(--line); z-index:9 }
  #side .logo, #side .tag, #side .foot, #syncbtn, #syncmsg, #themebtn { display:none }
  #side nav { flex-direction:row; gap:0; width:100%; justify-content:space-around }
  #side nav a { flex-direction:column; gap:2px; padding:8px 10px; font-size:.68rem }
  .cards { grid-template-columns:1fr 1fr } .card:first-child { grid-column:1/-1 }
  .split { grid-template-columns:1fr }
}
</style></head><body>

<aside id="side">
  <div class="logo">💰 הכסף שלנו</div>
  <div class="tag">פרטי לחלוטין · על המחשב שלנו</div>
  <nav>
    <a data-v="overview" class="on"><span class="ico">🏠</span><span>סקירה</span></a>
    <a data-v="cats"><span class="ico">📊</span><span>קטגוריות</span></a>
    <a data-v="txns"><span class="ico">📋</span><span>תנועות</span></a>
    <a data-v="trends"><span class="ico">📈</span><span>מגמות</span></a>
  </nav>
  <button id="syncbtn" title="מושך תנועות חדשות, בונה מחדש את הנתונים ומרענן את הדף">🔄 סנכרון עכשיו</button>
  <div class="hint" id="syncmsg" style="text-align:center; margin-top:6px"></div>
  <button id="themebtn" title="מצב תצוגה">🌙 מצב כהה</button>
  <div class="foot">עודכן <span class="num">__GENERATED__</span><br>kaspion · נוצר מ־sync.py</div>
</aside>

<div class="head">
  <h1 id="vtitle">סקירה — <span id="mtitle"></span></h1>
</div>
<div class="sub" id="subline"></div>
<div class="months" id="months"></div>

<main>
<!-- ================= overview ================= -->
<section class="view on" id="v-overview">
  <div class="cards">
    <div class="card in"><div class="lbl">הכנסות</div><div class="val" id="income"></div>
      <div class="sub2" id="income-sub"></div></div>
    <div class="card"><div class="lbl">הוצאות</div><div class="val" id="spent"></div>
      <div class="sub2"></div></div>
    <div class="card"><div class="lbl">נשאר החודש</div><div class="val" id="saved"></div>
      <div class="sub2" id="saved-sub"></div></div>
  </div>
  <div class="banner" id="banner"></div>
  <h2>תובנות</h2>
  <div class="insights" id="insights"></div>

  <div class="grid2">
    <div>
      <h2>חלוקת ההוצאות</h2>
      <div class="panel split">
        <div class="donut-wrap">
          <svg width="210" height="210" viewBox="0 0 210 210" id="donut"></svg>
          <div class="donut-c"><div class="b" id="donut-total"></div><div class="s">סה"כ החודש</div></div>
        </div>
        <div class="legend" id="legend"></div>
      </div>
    </div>
    <div>
      <h2>5 ההוצאות הגדולות</h2>
      <div class="panel"><table id="top5">
        <thead><tr><th>תאריך</th><th>בית עסק</th><th>קטגוריה</th><th>סכום</th></tr></thead><tbody></tbody>
      </table></div>
    </div>
  </div>

  <h2>מקורות המידע</h2>
  <div class="panel"><div id="srcgrid" class="srcgrid"></div></div>
</section>

<!-- ================= categories ================= -->
<section class="view" id="v-cats">
  <h2 style="margin-top:0">תקציב מול ביצוע <span class="hint">(לחצו על קטגוריה לתנועות שלה · שינוי מספר התקציב נשמר אוטומטית)</span></h2>
  <div class="panel" id="cats"></div>

  <h2>ניהול קטגוריות</h2>
  <div class="panel addform" id="catman">
    <div class="uprow">
      <input id="nc-name" placeholder="שם הקטגוריה (למשל: חיות מחמד)" style="margin:0">
      <input id="nc-id" placeholder="מזהה באנגלית (pets)" style="margin:0">
      <button id="nc-go">הוספה</button>
    </div>
    <div class="hint" style="margin-top:6px">
      הקטגוריה תופיע מיד בכל הרשימות · אפשר למחוק רק קטגוריות שהוספתם
    </div>
    <div class="hint" id="nc-msg" style="margin-top:6px"></div>
    <div id="nc-list" style="margin-top:10px"></div>
  </div>
</section>

<!-- ================= transactions ================= -->
<section class="view" id="v-txns">
  <details class="toolbar">
    <summary>➕ הוספת הוצאה · טעינת קובץ</summary>
    <div class="panel addform" id="addform" style="margin-bottom:14px">
      <div style="font-weight:700; margin-bottom:10px">➕ הוספת הוצאה ידנית</div>
      <div class="addrow">
        <input id="a-desc" placeholder="תיאור (למשל: פלאפל בשוק)" style="margin:0">
        <input id="a-amt" type="number" min="0" step="0.01" placeholder="סכום ₪" style="margin:0">
        <input id="a-date" type="date" style="margin:0">
        <select id="a-cat"></select>
        <button id="a-go">הוספה</button>
      </div>
      <div class="hint" id="a-msg" style="margin-top:6px"></div>
    </div>
    <div class="panel addform" id="upform" style="margin-bottom:14px">
      <div style="font-weight:700; margin-bottom:10px">📄 טעינת קובץ עסקאות (ישראכרט · ONE ZERO)</div>
      <div class="uprow">
        <input id="u-file" type="file" accept=".xlsx,.xls" multiple style="margin:0">
        <button id="u-go">טעינה</button>
      </div>
      <div class="hint" style="margin-top:6px">
        הורידו את פירוט העסקאות מאתר ישראכרט או מאפליקציית ONE ZERO (קובץ Excel) וטענו אותו כאן ·
        הקובץ מזוהה אוטומטית · אפשר לבחור כמה קבצים יחד ·
        טעינה חוזרת של אותו קובץ בטוחה ולא תיצור כפילויות ·
        חיובי כרטיסי האשראי בחשבון הבנק לא נספרים פעמיים
      </div>
      <div class="hint" id="u-msg" style="margin-top:6px"></div>
    </div>
  </details>
  <span class="chip" id="chip"></span>
  <div class="fseg" id="fseg">
    <button data-f="all" class="on">הכל</button>
    <button data-f="out">הוצאות</button>
    <button data-f="in">הכנסות</button>
  </div>
  <input id="s" placeholder="חיפוש בית עסק או קטגוריה… 🔍">
  <div class="panel">
    <table id="t"><thead><tr>
      <th class="sortable" data-k="0">תאריך <span class="arr"></span></th>
      <th class="sortable" data-k="2">בית עסק <span class="arr"></span></th>
      <th class="sortable" data-k="8">כרטיס <span class="arr"></span></th>
      <th class="sortable" data-k="3">קטגוריה <span class="arr"></span></th>
      <th class="sortable" data-k="4">סכום <span class="arr"></span></th>
      <th class="sortable" data-k="5">מקור <span class="arr"></span></th>
      <th></th>
    </tr></thead><tbody></tbody></table>
    <div class="hint" style="margin-top:8px">🤖 סווג אוטומטית · ✅ תוקן ידנית · ❔ עדיין לא סווג —
    שינוי קטגוריה נשמר לתמיד ותקף לכל התנועות של אותו בית עסק · 🗑 מסתיר תנועה מכל החישובים</div>
  </div>
</section>

<!-- ================= trends ================= -->
<section class="view" id="v-trends">
  <h2 style="margin-top:0">הוצאות לאורך זמן <span class="hint">(לחצו על חודש למעבר)</span></h2>
  <div class="panel"><div class="trend" id="trend"></div></div>

  <h2>מגמה לפי קטגוריה <span class="hint">ירוק = בתקציב · אדום = חריגה · (לחצו לתנועות)</span></h2>
  <div class="catgrid" id="catgrid"></div>

  <h2>הכנסות, הוצאות וחיסכון</h2>
  <div class="panel"><table id="save">
    <thead><tr><th>חודש</th><th>הכנסות</th><th>הוצאות</th><th>חיסכון</th></tr></thead><tbody></tbody>
  </table></div>
</section>
</main>

<script>
const DATA = __DATA__;
// validated (dataviz/scripts/validate_palette.js) categorical palettes, one per theme —
// same hue order, re-stepped for each surface so CVD separation holds in both
const PALETTE_LIGHT = ['#0e9f6e','#c2410c','#2563eb','#dc2626','#7c3aed','#ca8a04','#0891b2','#65a30d'];
const PALETTE_DARK  = ['#12ad82','#dd6b30','#4a86e8','#e04a48','#9268e0','#a67c1a','#0d9cba','#78a028'];
const NEUTRAL_LIGHT = '#989186', NEUTRAL_DARK = '#77747c';
const isDark = () => document.documentElement.dataset.theme === 'dark'
  || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
const PALETTE = () => isDark() ? PALETTE_DARK : PALETTE_LIGHT;
// which institution each charge came from. Colors are drawn from PALETTE above (not the
// issuers' real brand colors) and the mark is a dot beside the name, never colored text —
// so the label stays legible and the file stays self-contained (no external logo requests).
const ISSUERS = {
  max:      { label: 'מקס',      idx: 2 },
  isracard: { label: 'ישראכרט',  idx: 4 },
  visaCal:  { label: 'כאל',      idx: 5 },
  amex:     { label: 'אמריקן',   idx: 6 },
  leumi:    { label: 'לאומי',    idx: 0 },
  hapoalim: { label: 'הפועלים',  idx: 3 },
  // both spellings: the scraper's company id is camelCase, the file importer's
  // account_id is lowercase — they must land on the same badge
  oneZero:  { label: 'ONE ZERO', idx: 1 },
  onezero:  { label: 'ONE ZERO', idx: 1 },
  manual:   { label: 'ידני',     idx: null },
};
const issuerOf = k => {
  const e = ISSUERS[k] || { label: k || '—', idx: null };
  return { label: e.label, color: e.idx == null ? (isDark() ? NEUTRAL_DARK : NEUTRAL_LIGHT) : PALETTE()[e.idx] };
};
const VIEWS = { overview:'סקירה', cats:'קטגוריות', txns:'תנועות', trends:'מגמות' };
const ils = x => '₪' + Math.round(x).toLocaleString('he-IL');
const $ = id => document.getElementById(id);
// merchant names are free text from the bank (e.g. Hebrew "ד"ר" contains a literal
// quote) — never interpolate them into an HTML attribute unescaped, or the quote
// terminates the attribute early and corrupts every attribute after it on that tag.
const escAttr = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
// Round a chart's top value up to a clean axis number: "2,526" as a tick is noise.
// The steps include 3 and 4 so 2,526 lands on 3,000 rather than 5,000 — a coarser
// ladder would leave the tallest bar at half the chart height, which is exactly the
// wasted headroom the per-card scaling was added to avoid.
const niceCeil = v => {
  if (v <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  return [1, 1.5, 2, 3, 4, 5, 7.5, 10].find(s => v <= s * mag) * mag;
};

let view = 'overview';
let mi = Math.max(DATA.months.findIndex(m => m.key === DATA.startKey), 0);
let selCat = null;
let flow = 'all';               // money direction shown: all | out (spend) | in (income)
let sort = { k: 0, dir: -1 };   // default: date, newest first
let theme = 'auto';             // auto | light | dark
// insight drill-down. selCat/flow/mi already cover category, direction and month; this
// covers the two things they cannot express: an explicit merchant set, and "still ❔".
let pick = null;   // { merchants: [...], uncat: bool, label: '...' } | null

/* ---------- keep your place across the reload every edit triggers ---------- */
// Saving a category rebuilds the page and reloads it; without this you'd be thrown
// back to the overview on the default month after every single correction.
const UI_KEY = 'kaspion.ui';
function saveUi() {
  try {
    sessionStorage.setItem(UI_KEY, JSON.stringify({
      view, month: DATA.months[mi] ? DATA.months[mi].key : null,
      selCat, sort, flow, search: $('s') ? $('s').value : '', theme, pick,
    }));
  } catch (e) { /* private mode — never fail an edit over bookkeeping */ }
}
function restoreUi() {
  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(UI_KEY) || 'null'); } catch (e) { return; }
  if (!saved) return;
  if (VIEWS[saved.view]) view = saved.view;
  // resolve the month by KEY, never by a stored index: importing a statement can add
  // months and silently shift every index underneath us
  const idx = DATA.months.findIndex(m => m.key === saved.month);
  if (idx >= 0) mi = idx;
  selCat = saved.selCat || null;
  if (['all', 'in', 'out'].includes(saved.flow)) flow = saved.flow;
  if (saved.sort && typeof saved.sort.k === 'number') sort = saved.sort;
  if (saved.search && $('s')) $('s').value = saved.search;
  if (['auto', 'light', 'dark'].includes(saved.theme)) theme = saved.theme;
  // a drill-down must survive the reload an edit triggers, or fixing a category from
  // inside one silently dumps you back to the whole month
  if (saved.pick && (Array.isArray(saved.pick.merchants) || saved.pick.uncat)) {
    pick = saved.pick;
  }
}
function applyTheme() {
  document.documentElement.dataset.theme = theme === 'auto' ? '' : theme;
  $('themebtn').textContent = isDark() ? '☀️ מצב בהיר' : '🌙 מצב כהה';
}
$('themebtn').onclick = () => {
  theme = isDark() ? 'light' : 'dark';
  applyTheme(); saveUi(); render();   // charts re-read PALETTE()
};
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (theme === 'auto') { applyTheme(); render(); }
});
function applyView() {
  document.querySelectorAll('#side nav a')
    .forEach(x => x.classList.toggle('on', x.dataset.v === view));
  document.querySelectorAll('.view')
    .forEach(s => s.classList.toggle('on', s.id === 'v-' + view));
}

/* ---------- editing (one version for everyone; talks to the local server) ---------- */
const API = location.protocol.startsWith('http') ? '' : 'http://127.0.0.1:8765';
{
  const sel = $('a-cat');
  sel.innerHTML = DATA.categories.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
  sel.value = 'other';
  $('a-date').value = new Date().toISOString().slice(0, 10);
  $('a-go').onclick = async () => {
    const desc = $('a-desc').value.trim(), amt = parseFloat($('a-amt').value);
    if (!desc || !(amt > 0)) { $('a-msg').textContent = 'צריך תיאור וסכום חיובי'; return; }
    await api('/api/add', { description: desc, amount: amt,
                            category: sel.value, date: $('a-date').value });
  };
}
async function api(path, payload, msgId = 'a-msg', busy = 'שומר…') {
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  $(msgId).textContent = busy;
  try {
    const r = await fetch(API + path, { method: 'POST', body: JSON.stringify(payload) });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || 'failed');
    location.reload();
  } catch (e) {
    $(msgId).textContent = e.message.includes('fetch')
      ? 'השרת לא פועל — הריצו במסוף: python3 -m kaspion.serve'
      : 'שגיאה: ' + e.message;
    document.querySelectorAll('button').forEach(b => b.disabled = false);
  }
}

$('syncbtn').onclick = () =>
  api('/api/sync', {}, 'syncmsg', 'מסנכרן… זה יכול לקחת כמה דקות עם בנק אמיתי');

/* ---------- managing the category list ---------- */
function renderCatManager() {
  const custom = DATA.categories.filter(c => c.custom);
  $('nc-list').innerHTML = custom.length
    ? `<div class="hint" style="margin-bottom:6px">קטגוריות שהוספתם:</div>` + custom.map(c =>
        `<span class="ctag">${c.name}
           <button class="ncdel" data-id="${escAttr(c.id)}" data-name="${escAttr(c.name)}"
                   title="מחיקת הקטגוריה">✕</button></span>`).join('')
    : '<div class="hint">עדיין לא הוספתם קטגוריות משלכם</div>';
  document.querySelectorAll('.ncdel').forEach(b => b.onclick = () => {
    // deleting moves anything filed under it back to "אחר" — say so before doing it
    if (!confirm(`למחוק את "${b.dataset.name}"? תנועות שסווגו אליה יחזרו ל"אחר".`)) return;
    api('/api/delete-category', { category_id: b.dataset.id }, 'nc-msg', 'מוחק…');
  });
}
$('nc-go').onclick = () => {
  const name = $('nc-name').value.trim();
  const id = $('nc-id').value.trim().toLowerCase();
  if (!name || !id) { $('nc-msg').textContent = 'צריך שם ומזהה באנגלית'; return; }
  api('/api/add-category', { category_id: id, name }, 'nc-msg', 'מוסיף…');
};

// Upload Isracard statements. Files go up one at a time so a bad file names itself
// in the error instead of failing the whole batch anonymously.
$('u-go').onclick = async () => {
  const files = [...$('u-file').files];
  if (!files.length) { $('u-msg').textContent = 'בחרו קובץ Excel שהורדתם מאתר ישראכרט'; return; }
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  let added = 0, updated = 0;
  try {
    for (const [i, file] of files.entries()) {
      $('u-msg').textContent = `טוען ${i + 1}/${files.length} — ${file.name}…`;
      const b64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1]);
        reader.onerror = () => reject(new Error(`לא ניתן לקרוא את ${file.name}`));
        reader.readAsDataURL(file);
      });
      const res = await fetch(API + '/api/upload', {
        method: 'POST', body: JSON.stringify({ filename: file.name, data: b64 }),
      });
      const out = await res.json();
      if (!out.ok) throw new Error(`${file.name}: ${out.error || 'failed'}`);
      added += out.added || 0;
      updated += out.updated || 0;
    }
    $('u-msg').textContent = `✔ ${added} תנועות חדשות · ${updated} עודכנו — מרענן…`;
    setTimeout(() => location.reload(), 1200);
  } catch (e) {
    $('u-msg').textContent = e.message.includes('fetch')
      ? 'השרת לא פועל — הריצו במסוף: python3 -m kaspion.serve'
      : 'שגיאה: ' + e.message;
    document.querySelectorAll('button').forEach(b => b.disabled = false);
  }
};

/* ---------- navigation ---------- */
document.querySelectorAll('#side nav a').forEach(a => a.onclick = () => {
  view = a.dataset.v;
  applyView();
  render();
  window.scrollTo({ top: 0 });
});
function renderMonths() {
  const multiYear = new Set(DATA.months.map(x => x.label.split(' ')[1])).size > 1;
  $('months').innerHTML = [...DATA.months].reverse().map(x => {
    const i = DATA.months.indexOf(x);
    const [name, year] = x.label.split(' ');
    return `<button class="mchip ${i === mi ? 'sel' : ''}" data-i="${i}">
      ${name}${multiYear ? ' ' + year.slice(2) + '׳' : ''}${x.isCurrent ? '<span class="now"></span>' : ''}
    </button>`;
  }).join('');
  document.querySelectorAll('.mchip').forEach(b => b.onclick = () => { mi = +b.dataset.i; render(); });
}

/* ---------- render ---------- */
function render() {
  const m = DATA.months[mi];
  $('vtitle').innerHTML = `${VIEWS[view]} — <span id="mtitle">${m.label}</span>`;
  $('subline').textContent = m.isCurrent ? 'החודש הנוכחי · מתעדכן בכל sync' : 'חודש שהסתיים';
  renderMonths();
  if (view === 'overview') renderOverview(m);
  if (view === 'cats') renderCats(m);
  if (view === 'txns') { renderChip(); renderTxns(); }
  if (view === 'trends') renderTrends(m);
  saveUi();
}

function renderSources() {
  // staleness is measured against the newest TRANSACTION, not the load time: a sync
  // that runs nightly but silently returns nothing would otherwise look healthy
  $('srcgrid').innerHTML = (DATA.sources || []).map(s => {
    const iss = issuerOf(s.src);
    const age = s.staleDays <= 3 ? 'ok' : s.staleDays <= 14 ? 'warn' : 'old';
    const ageTxt = s.staleDays <= 0 ? 'היום'
                 : s.staleDays === 1 ? 'אתמול'
                 : `לפני ${s.staleDays} ימים`;
    // one compact row: dot+name, freshness pill, an ISOLATED date range (.num — this
    // is the bug site: a date range is two LTR runs, and without isolation the bidi
    // algorithm reorders them), transaction count. Load time moves into the title
    // tooltip instead of its own line — it's detail, not something read at a glance.
    return `<div class="srcrow" title="נטען לאחרונה: ${escAttr(s.loaded)} · ${escAttr(s.account)}">
      <span class="srcname"><i style="background:${iss.color}"></i>${iss.label}</span>
      <span class="srcage ${age}">${ageTxt}</span>
      <span class="num srcrange">${s.from} – ${s.to}</span>
      <span class="srccount"><b class="num">${s.n.toLocaleString('he-IL')}</b> תנועות</span>
    </div>`;
  }).join('') || '<div class="hint">אין עדיין נתונים</div>';
}

function openInsight(link) {
  if (!link || !VIEWS[link.view]) return;
  // resolve the month by KEY, never by a stored index: importing a statement adds months
  // and shifts every index underneath us
  if (link.month) {
    const idx = DATA.months.findIndex(m => m.key === link.month);
    if (idx >= 0) mi = idx;
  }
  // Reset every filter the link does not set. gotoCat() skips this and leaves a stale
  // search box narrowing the result; here that bug would hide the very rows the insight
  // is pointing at, which is the whole point of the click.
  selCat = link.cat || null;
  flow = link.flow || 'all';
  pick = (link.merchants || link.uncat)
    ? { merchants: link.merchants || [], uncat: !!link.uncat, label: link.label || '' }
    : null;
  if ($('s')) $('s').value = '';
  view = link.view;
  applyView();
  render();
  window.scrollTo({ top: 0 });
}

function renderInsights() {
  // Insights describe the whole history, not the month chip that happens to be selected,
  // so they are rendered straight from DATA and never re-filtered per month.
  const box = $('insights'), items = DATA.insights || [];
  box.innerHTML = '';
  if (!items.length) return;               // no history yet: show nothing, not an empty box
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // every amount is an LTR run inside RTL text: without isolation "₪29,192" beside a
  // month name renders reversed — the bug that started the redesign
  const nums = s => s.replace(/₪[\d,]+|\d[\d,]*(?:\.\d+)?%?/g,
                              t => `<span class="num">${t}</span>`);
  box.innerHTML = items.map((i, n) =>
    `<div class="ins ${i.tone}${i.link ? ' go' : ''}" data-n="${n}"${
       i.link ? ' title="לחצו כדי לראות את התנועות שמאחורי התובנה"' : ''
     }><span class="ins-dot"></span><span class="ins-txt">${nums(esc(i.text))}</span>${
       i.link ? '<span class="ins-go">‹</span>' : ''}</div>`
  ).join('');
  // insights without a link stay inert rather than looking clickable and doing nothing
  box.querySelectorAll('.ins.go').forEach(el =>
    el.onclick = () => openInsight(items[+el.dataset.n].link));
}

function renderOverview(m) {
  renderSources();
  $('spent').textContent = ils(m.spent);
  $('income').textContent = ils(m.income);
  // what's left of what came in — the number a household actually plans around
  const left = m.income - m.spent;
  $('saved').textContent = (left < 0 ? '−' : '') + ils(Math.abs(left));
  $('saved').className = 'val ' + (left >= 0 ? 'good' : 'bad');
  // The budget/pace line is gone from here: the banner already says whether the month
  // is in good shape, and the per-category budgets live on the קטגוריות page.
  const underPace = m.pace >= 0;
  const kotzev = m.isCurrent ? 'לקצב' : 'לתקציב';
  $('saved-sub').textContent = m.income
    ? `${Math.round(left / m.income * 100)}% מההכנסה`
    : 'אין הכנסות בחודש זה';
  // a month with no income is almost always missing data, not a month without pay
  $('income-sub').textContent = m.income ? 'נכנס החודש' : 'לא נטענו הכנסות';

  // The banner answers the question the household actually asks: did we live within
  // what came in this month? It falls back to the budget pace only when there is no
  // income loaded, where an income comparison would be meaningless.
  if (!m.income) {
    $('banner').className = 'banner ' + (underPace ? 'good' : 'bad');
    $('banner').textContent = underPace
      ? `✅ מעולה! ${m.isCurrent ? 'אתם' : 'הייתם'} ${ils(m.pace)} מתחת ${kotzev}`
      : `⚠️ שימו לב — ${m.isCurrent ? 'אתם' : 'הייתם'} ${ils(-m.pace)} מעל ${kotzev}`;
  } else if (left >= 0) {
    $('banner').className = 'banner good';
    $('banner').textContent = `✅ מעולה! נכנס יותר ממה שיצא — ${
      m.isCurrent ? 'נשארו לכם' : 'נשארו'} ${ils(left)} מתוך ${ils(m.income)}`;
  } else {
    $('banner').className = 'banner bad';
    $('banner').textContent = `⚠️ שימו לב — הוצאתם ${ils(-left)} יותר ממה שנכנס החודש`;
  }
  renderInsights();

  // donut: top 6 categories + "אחרים"
  const cats = [...m.cats].sort((a, b) => b.actual - a.actual);
  const top = cats.slice(0, 6);
  const rest = cats.slice(6).reduce((s, c) => s + c.actual, 0);
  const parts = [...top.map(c => ({ name: c.name, v: c.actual })),
                 ...(rest > 0 ? [{ name: 'אחרים', v: rest }] : [])];
  const total = parts.reduce((s, p) => s + p.v, 0) || 1;
  const R = 80, C = 2 * Math.PI * R, pal = PALETTE();
  let off = 0, svg = '';
  parts.forEach((p, i) => {
    const frac = p.v / total;
    svg += `<circle cx="105" cy="105" r="${R}" fill="none" stroke="${pal[i % pal.length]}"
      stroke-width="30" stroke-dasharray="${(frac * C).toFixed(1)} ${C.toFixed(1)}"
      stroke-dashoffset="${(-off * C).toFixed(1)}"></circle>`;
    off += frac;
  });
  $('donut').innerHTML = svg || '';
  $('donut-total').textContent = ils(m.spent);
  $('legend').innerHTML = parts.map((p, i) =>
    `<div class="leg" data-cat="${p.name}">
       <span class="dot" style="background:${pal[i % pal.length]}"></span>
       <span class="nm">${p.name}</span><span class="am">${ils(p.v)}</span>
       <span class="hint">${Math.round(p.v / total * 100)}%</span></div>`).join('')
    || '<div class="hint">אין עדיין הוצאות החודש 🎉</div>';
  document.querySelectorAll('.leg').forEach(el => el.onclick = () => gotoCat(el.dataset.cat));

  // biggest EXPENSES — m.txns now carries income too, and a salary would otherwise
  // sit at the top of a list titled "the 5 biggest expenses"
  $('top5').tBodies[0].innerHTML = [...m.txns].filter(t => !t[10]).sort((a, b) => b[4] - a[4]).slice(0, 5)
    .map(t => `<tr><td class="num">${t[1]}</td><td>${t[2]}</td><td>${t[3]}</td><td class="amt nums">${ils(t[4])}</td></tr>`)
    .join('') || '<tr><td colspan="4" class="hint">אין תנועות</td></tr>';
}

function renderCats(m) {
  $('cats').innerHTML = m.cats.map(c => {
    const pct = c.budget ? Math.min(c.actual / c.budget * 100, 100) : 100;
    const color = c.status === 'under' ? 'var(--green)' : c.status === 'over' ? 'var(--red)' : 'var(--gray)';
    return `<div class="cat" data-cat="${c.name}">
      <div class="cat-line"><span>${c.name}</span>
        <span class="cat-amt">${ils(c.actual)}
          <small>מתוך תקציב של</small>
          <input type="number" class="budget-edit" data-id="${c.id}" value="${c.budget || ''}"
                 min="0" step="50" placeholder="—" title="שינוי התקציב החודשי — נשמר אוטומטית">
          <small>₪</small>${c.suggested
            ? `<span class="sugg-tag" title="חושב אוטומטית מהממוצע של 3 החודשים האחרונים — כל שינוי ידני יחליף אותו לצמיתות">מוצע</span>`
            : ''}</span></div>
      <div class="bar"><div class="fill" style="width:${pct}%;background:${color}"></div></div></div>`;
  }).join('') || '<div class="hint">אין עדיין הוצאות החודש 🎉</div>';
  document.querySelectorAll('.cat').forEach(el => el.onclick = e => {
    if (e.target.classList.contains('budget-edit')) return;  // editing, not navigating
    gotoCat(el.dataset.cat);
  });
  // change a budget -> saved to state.budgets, pacing recalculated
  document.querySelectorAll('.budget-edit').forEach(inp => inp.onchange = () => {
    const amount = parseFloat(inp.value);
    if (amount >= 0) api('/api/set-budget', { category: inp.dataset.id, amount });
  });
  renderCatManager();
}

function gotoCat(name) {
  if (name === 'אחרים') return;
  selCat = name;
  // clears any insight drill-down (openInsight sets `pick`) — this is a fresh, independent
  // navigation, not a refinement of one, and a leftover merchant filter would silently
  // intersect with it and hide rows the category actually contains
  pick = null;
  document.querySelector('#side nav a[data-v="txns"]').click();
}

function renderChip() {
  const labels = [pick && pick.label, selCat].filter(Boolean);
  $('chip').className = 'chip' + (labels.length ? ' on' : '');
  $('chip').textContent = labels.length ? `מציג רק: ${labels.join(' · ')} ✕` : '';
}

function renderTxns() {
  const m = DATA.months[mi];
  const v = $('s').value.trim();
  // keep the segmented control in step with `flow`, including after a restore
  document.querySelectorAll('#fseg button')
    .forEach(b => b.classList.toggle('on', b.dataset.f === flow));
  const rows = m.txns
    .filter(t => flow === 'all' || (flow === 'in' ? t[10] : !t[10]))
    .filter(t => !selCat || t[3] === selCat)
    // t[11] is merchant_key, t[5] the '🤖'/'✅'/'❔' glyph — see _collect()'s row layout
    .filter(t => !pick || (pick.uncat ? (t[5] === '❔' && !t[10])
                                      : pick.merchants.includes(t[11])))
    // search matches merchant, category, and the card it came from ("מקס", "ישראכרט"…)
    .filter(t => !v || t[2].includes(v) || t[3].includes(v) || issuerOf(t[8]).label.includes(v))
    .sort((a, b) => {
      // the כרטיס column renders the Hebrew label, so it must sort by that and not by
      // the internal key ('isracard', 'onezero'), which produces a baffling order
      const val = t => sort.k === 8 ? issuerOf(t[8]).label : t[sort.k];
      const x = val(a), y = val(b);
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'he')) * sort.dir;
    });
  // Income keeps its category as plain text: the dropdown lists spend categories only
  // (dim_category minus 'income'), so rendering one here would show the wrong option
  // selected and let a salary be filed under "groceries".
  const catCell = t => t[10]
    ? `<td><span class="catname">${t[3]}</span></td>`
    : `<td><select class="recat" data-m="${escAttr(t[2])}">${DATA.categories.map(c =>
      `<option value="${c.id}" ${c.id === t[7] ? 'selected' : ''}>${c.name}</option>`).join('')}</select></td>`;
  const issCell = t => {
    const s = issuerOf(t[8]);
    return `<td><span class="iss" title="${escAttr(t[9] || s.label)}">
      <i style="background:${s.color}"></i>${s.label}</span></td>`;
  };
  $('t').tBodies[0].innerHTML = rows.map(t =>
    `<tr><td class="num">${t[1]}</td><td>${t[2]}</td>${issCell(t)}${catCell(t)}
     <td class="amt nums ${t[10] ? 'in' : ''}">${t[10] ? '+' : ''}${ils(t[4])}</td><td>${t[5]}</td>
     <td><button class="del" title="הסתרת התנועה" data-id="${t[6]}">🗑</button></td></tr>`).join('')
    || '<tr><td colspan="7" class="hint">לא נמצאו תנועות</td></tr>';
  document.querySelectorAll('#t .del').forEach(b => b.onclick = () => {
    if (confirm('להסתיר את התנועה מכל החישובים?')) api('/api/remove', { transaction_id: b.dataset.id });
  });
  // change a category -> saved as an override for this merchant, forever
  document.querySelectorAll('#t .recat').forEach(s => s.onchange = () =>
    api('/api/recategorize', { merchant: s.dataset.m, category: s.value }));
  document.querySelectorAll('#t th.sortable').forEach(th => {
    th.querySelector('.arr').textContent =
      +th.dataset.k === sort.k ? (sort.dir === 1 ? '▲' : '▼') : '';
  });
  // search, sort and the category chip re-render only this table, never render(),
  // so they need their own save or those choices are lost on the next edit
  saveUi();
}

document.querySelectorAll('#t th.sortable').forEach(th => th.onclick = () => {
  const k = +th.dataset.k;
  sort = { k, dir: sort.k === k ? -sort.dir : (k === 4 ? -1 : 1) };
  renderTxns();
});
$('chip').onclick = () => { selCat = null; pick = null; renderChip(); renderTxns(); };
document.querySelectorAll('#fseg button').forEach(b => b.onclick = () => {
  flow = b.dataset.f;
  document.querySelectorAll('#fseg button').forEach(x => x.classList.toggle('on', x === b));
  renderTxns();
});
$('s').addEventListener('input', renderTxns);

function renderTrends(m) {
  // one shared scale for both series — income and spend are the same unit, so they
  // must never get separate axes or the comparison between them is meaningless
  const TH = 130;
  const maxT = Math.max(...DATA.months.map(x => Math.max(x.spent, x.income)), 1);
  $('trend').innerHTML = DATA.months.map((x, i) => {
    const overspent = x.income > 0 && x.spent > x.income;
    return `<div class="tcol ${i === mi ? 'sel' : ''}" data-i="${i}">
       <div class="tval">${ils(x.spent)}</div>
       <div class="tplot" style="height:${TH}px">
         <div class="tbar" style="height:${Math.max(x.spent / maxT * TH, 4)}px"></div>
         ${x.income ? `<div class="tinc ${overspent ? 'over' : ''}"
              style="bottom:${x.income / maxT * TH}px"
              title="הכנסות: ${ils(x.income)}"><span>${ils(x.income)}</span></div>` : ''}
       </div>
       <div class="tlab">${x.label.split(' ')[0]}</div>
       ${x.income ? `<div class="tsave ${overspent ? 'bad' : 'good'}">${
         overspent ? '−' : '+'}${ils(Math.abs(x.income - x.spent))}</div>` : ''}
       </div>`;
  }).join('');
  document.querySelectorAll('.tcol').forEach(el => el.onclick = () => { mi = +el.dataset.i; render(); });

  $('save').tBodies[0].innerHTML = [...DATA.months].reverse().map(x =>
    `<tr><td>${x.label}</td><td class="num nums">${ils(x.income)}</td><td class="num nums">${ils(x.spent)}</td>
     <td class="num nums ${x.saved >= 0 ? 'pos' : 'neg'}">${x.saved >= 0 ? '+' : '−'}${ils(Math.abs(x.saved))}</td></tr>`).join('');

  // per-category small multiples: bars per month, colored by budget status
  const cats = {};
  DATA.months.forEach((x, i) => x.cats.forEach(c => {
    if (!cats[c.name]) cats[c.name] = { name: c.name, total: 0, series: Array(DATA.months.length).fill(null) };
    cats[c.name].series[i] = c;
    cats[c.name].total += c.actual;
  }));
  const list = Object.values(cats).filter(c => c.total > 0).sort((a, b) => b.total - a.total);
  $('catgrid').innerHTML = list.map(c => {
    const budget = [...c.series].reverse().find(s => s && s.budget)?.budget || 0;
    // each card scales to ITS OWN spending, never stretched out by a budget the
    // household is comfortably under — a housing budget of 8,500 next to real
    // spend of ~1,000 would otherwise flatten every real bar to a sliver.
    // Only fold the target into the scale when it's in the same ballpark as
    // actual spend (≤40% above the highest month) — otherwise skip drawing the
    // line (the exact target is still in the footer text) so the bars keep full
    // resolution instead of leaving 80% of the chart empty above them.
    const actualMax = Math.max(...c.series.map(s => s ? s.actual : 0), 1);
    const showLine = budget > 0 && budget <= actualMax * 1.4;
    const rawScale = showLine ? Math.max(actualMax, budget) : actualMax;
    const scale = niceCeil(rawScale); // clean axis top (e.g. 3,000, not 2,526)
    const withBudget = c.series.filter(s => s && s.status !== 'no_budget').length;
    const under = c.series.filter(s => s && s.status === 'under').length;
    const CH = 68; // chart height in px — must match .cc-chart { height }
    const bars = c.series.map((s, i) => {
      const v = s ? s.actual : 0;
      const col = !s || s.status === 'no_budget' ? 'var(--accent)'
                : s.status === 'under' ? 'var(--green)' : 'var(--red)';
      return `<div class="mb" title="${DATA.months[i].label}: ${ils(v)}"
                   style="height:${Math.max(v / scale * CH, 3)}px;background:${col}"></div>`;
    }).join('');
    // the target value rides in the footer text, never floating over the bars — a label
    // positioned inside the chart collides with whichever bar happens to sit at that height
    const tline = showLine
      ? `<div class="tline" style="bottom:${budget / scale * CH}px" title="יעד חודשי: ${ils(budget)}"></div>`
      : '';
    // each card's own scale, so a ₪150 category and a ₪3,000 one both use full
    // chart height — reading the axis is how you tell them apart, not bar size.
    // The target gets an axis tick only when its line is drawn AND it clears the
    // 0 and max labels; a target near either end would print on top of them.
    // Draw the tick whenever the line is drawn; whether it actually fits between the
    // 0 and max labels is decided by measuring after layout (see below) rather than
    // by a pixel threshold, which depends on font metrics we don't control here.
    const tgtY = showLine ? budget / scale * CH : 0;
    const axis = `<div class="cc-axis"><span>${ils(scale)}</span>${showLine
        ? `<span class="tgt" style="bottom:${tgtY}px">${ils(budget)}</span>` : ''
      }<span>${ils(0)}</span></div>`;
    // 3-letter month names (מאי · יונ · יול · אוג · ספט) — the full ones overflow
    // once a card is showing five or more months side by side
    const months = `<div class="cc-months">${c.series.map((s, i) =>
      `<span class="${DATA.months[i].isCurrent ? 'now' : ''}">${
        DATA.months[i].label.split(' ')[0].slice(0, 3)}</span>`).join('')}</div>`;
    const ratio = under / Math.max(withBudget, 1);
    const badge = ratio === 1 ? 'ok' : ratio >= 0.5 ? 'mid' : 'bad';
    // with the target on the axis the footer keeps only two facts, one per side, so
    // it stays on a single line instead of wrapping raggedly
    // "החודש" means the month the page is showing (mi) — NOT the last month in the
    // data. Using .at(-1) made every card read ₪0 whenever the newest month happened
    // to be empty, while its own bars clearly showed spending.
    const latest = ils((c.series[mi] || { actual: 0 }).actual);
    return `<div class="catcard" data-cat="${c.name}">
      <div class="cc-head"><span>${c.name}</span>
        <span class="badge ${badge}">${under}/${withBudget} בתקציב</span></div>
      <div class="cc-chart">
        <div class="cc-plot"><div class="cc-bars">${bars}${tline}</div>${months}</div>
        ${axis}
      </div>
      <div class="cc-now"><span><b>${latest}</b> החודש${budget
        ? `<span class="tgt-fb"${showLine ? ' hidden' : ''}> · יעד ${ils(budget)}</span>` : ''
      }</span><span>סה"כ ${ils(c.total)}</span></div>
    </div>`;
  }).join('');
  // A target sitting near 0 or near the top would print straight through the axis's
  // own end labels. Rather than guess a pixel threshold, measure the rendered boxes:
  // if they actually intersect, drop the tick and fall back to the footer's "יעד".
  document.querySelectorAll('.catcard').forEach(card => {
    const tick = card.querySelector('.cc-axis .tgt');
    if (!tick) return;
    const box = tick.getBoundingClientRect();
    const hits = [...card.querySelectorAll('.cc-axis > span:not(.tgt)')].some(end => {
      const r = end.getBoundingClientRect();
      return box.bottom > r.top && box.top < r.bottom;
    });
    if (hits) {
      tick.remove();
      const fallback = card.querySelector('.tgt-fb');
      if (fallback) fallback.hidden = false;
    }
  });
  document.querySelectorAll('.catcard').forEach(el => el.onclick = () => gotoCat(el.dataset.cat));
}

restoreUi();
applyTheme();
applyView();
render();
</script>
</body></html>"""


def build_report() -> Path:
    data = _collect()
    html = TEMPLATE.replace("__GENERATED__", data["generated"]).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False)
    )
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(f"dashboard written -> {build_report()}")
