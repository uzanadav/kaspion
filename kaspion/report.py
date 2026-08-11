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
               p.budget_to_date_ils, p.pace_status, p.category_id
        from main.fct_budget_pacing p join main.dim_category c using (category_id)
        where p.category_id != 'income'
        order by p.actual_ils desc
    """)
    txns = q("""
        select strftime(posted_month, '%Y-%m'), strftime(posted_date, '%Y-%m-%d'),
               strftime(posted_date, '%d.%m'), raw_description, c.name_he, spend_ils,
               case category_source when 'ai' then '🤖' when 'override' then '✅' else '❔' end,
               f.transaction_id, f.category_id
        from main.fct_spend f join main.dim_category c using (category_id)
        order by posted_date desc
    """)
    categories = q("""
        select category_id, name_he from main.dim_category
        where category_id != 'income' order by name_he
    """)
    income = q("""
        select strftime(date_trunc('month', posted_date), '%Y-%m'), sum(amount)
        from main.int_categorized
        where amount > 0 and not is_transfer
        group by 1
    """)
    con.close()

    months: dict[str, dict] = {}

    def month(key: str) -> dict:
        return months.setdefault(
            key, {"key": key, "label": _label(key), "spent": 0.0, "budget": 0.0,
                  "toDate": 0.0, "income": 0.0, "cats": [], "txns": []}
        )

    for key, name, actual, budget, to_date, status, cat_id in pacing:
        m = month(key)
        actual, budget = float(actual), float(budget or 0)
        m["spent"] += actual
        m["budget"] += budget
        m["toDate"] += float(to_date or 0)
        m["cats"].append({"id": cat_id, "name": name, "actual": actual, "budget": budget, "status": status})

    for key, iso, d, desc, cat, amt, src, txn_id, cat_id in txns:
        month(key)["txns"].append([iso, d, desc, cat, float(amt), src, txn_id, cat_id])

    for key, inc in income:
        if key in months:
            months[key]["income"] = float(inc)

    ordered = [months[k] for k in sorted(months)]
    current_key = datetime.now().strftime("%Y-%m")
    for m in ordered:
        m["isCurrent"] = m["key"] == current_key
        m["pace"] = round(m["toDate"] - m["spent"], 2)
        m["saved"] = round(m["income"] - m["spent"], 2)
    return {
        "months": ordered,
        "categories": [{"id": c, "name": n} for c, n in categories],
        "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "startKey": current_key if current_key in months else (ordered[-1]["key"] if ordered else ""),
    }


TEMPLATE = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>הכסף שלנו</title>
<style>
:root { --green:#1a9e6c; --red:#e5484d; --gray:#b8b3ab; --ink:#3d3a34; --soft:#8a857c;
        --card:#ffffff; --bg:#faf6f0; --line:#efe9df; --accent:#d9c9a8; --sel:#f3ecdf; }
* { box-sizing:border-box; margin:0 }
html { font-size:17.5px }
body { font-family:-apple-system, "Segoe UI", "Heebo", Arial, sans-serif;
       background:var(--bg); color:var(--ink); padding:24px 260px 60px 36px }

/* ---- sidebar (right rail, RTL-natural; bottom bar on mobile) ---- */
#side { position:fixed; right:0; top:0; bottom:0; width:224px; background:var(--card);
        border-left:1px solid var(--line); padding:26px 14px; display:flex; flex-direction:column }
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
        background:var(--card); font:inherit; font-size:.9rem; cursor:pointer }
#syncbtn:hover { background:var(--sel) }
#syncbtn:disabled { opacity:.55; cursor:wait }

/* ---- header ---- */
/* content hugs the sidebar on the right instead of floating in the middle */
.head { display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;
        max-width:1280px; margin-right:0; margin-left:auto }
h1 { font-size:1.45rem }
/* month strip: every month is one tap away */
.months { display:flex; gap:7px; max-width:1280px; margin:0 0 20px auto; overflow-x:auto;
        padding-bottom:4px; -webkit-overflow-scrolling:touch }
.mchip { flex:none; padding:8px 16px; border-radius:20px; border:1px solid var(--line);
        background:var(--card); font:inherit; font-size:.88rem; cursor:pointer; color:var(--ink) }
.mchip:hover { background:var(--sel) }
.mchip.sel { background:var(--ink); border-color:var(--ink); color:#fff; font-weight:700 }
.mchip .now { display:inline-block; width:7px; height:7px; border-radius:50%;
        background:var(--green); margin-inline-start:6px; vertical-align:middle }
.sub { color:var(--soft); font-size:.85rem; max-width:1280px; margin:0 0 14px auto }
main { max-width:1280px; margin-right:0; margin-left:auto }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:0 22px; align-items:start }
@media (max-width:1000px) { .grid2 { grid-template-columns:1fr } }
.view { display:none } .view.on { display:block }
h2 { font-size:1.05rem; margin:26px 0 12px }
.hint { font-size:.75rem; color:var(--soft) }

/* ---- cards & banner ---- */
.cards { display:grid; grid-template-columns:repeat(3,1fr); gap:10px }
.card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px 14px; text-align:center }
.card .lbl { font-size:.8rem; color:var(--soft) }
.card .val { font-size:1.45rem; font-weight:700; margin-top:4px }
.val.good { color:var(--green) } .val.bad { color:var(--red) }
.banner { margin:14px 0 0; padding:13px 16px; border-radius:14px; font-weight:600; font-size:.95rem }
.banner.good { background:#e7f6ee; color:#116646 } .banner.bad { background:#fdebec; color:#a12b30 }
.panel { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px }

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
.cat { margin-bottom:6px; padding:9px 11px; border-radius:12px; cursor:pointer; transition:background .15s }
.cat:hover { background:var(--bg) }
.cat-line { display:flex; justify-content:space-between; font-size:.92rem; margin-bottom:5px }
.cat-amt small { color:var(--soft); font-weight:400 }
/* progress fill anchors to the RIGHT and grows leftward (natural for Hebrew) */
.bar { height:9px; background:var(--line); border-radius:6px; overflow:hidden;
       display:flex; justify-content:flex-start }
.fill { height:100%; border-radius:6px }

/* ---- trends ---- */
.trend { display:flex; gap:8px; align-items:flex-end; justify-content:space-between; padding-top:8px }
.tcol { flex:1; text-align:center; cursor:pointer }
.tbar { background:var(--accent); border-radius:6px 6px 0 0; transition:background .15s }
.tcol:hover .tbar { background:#c5ae82 }
.tcol.sel .tbar { background:var(--green) }
.tval { font-size:.62rem; color:var(--soft); margin-bottom:3px }
.tlab { font-size:.72rem; color:var(--soft); margin-top:5px }
.tcol.sel .tlab { color:var(--green); font-weight:700 }
.pos { color:var(--green); font-weight:600 } .neg { color:var(--red); font-weight:600 }

/* ---- per-category trend cards ---- */
.catgrid { display:grid; grid-template-columns:repeat(auto-fill, minmax(215px, 1fr)); gap:12px }
.catcard { background:var(--card); border:1px solid var(--line); border-radius:14px;
        padding:13px 14px; cursor:pointer; transition:border-color .15s }
.catcard:hover { border-color:var(--accent) }
.cc-head { display:flex; justify-content:space-between; align-items:center; font-size:.9rem; font-weight:600 }
.badge { font-size:.66rem; font-weight:600; padding:2px 9px; border-radius:10px; white-space:nowrap }
.badge.ok  { background:#e7f6ee; color:#116646 }
.badge.mid { background:#fdf3e0; color:#8a5a00 }
.badge.bad { background:#fdebec; color:#a12b30 }
.cc-bars { display:flex; gap:4px; align-items:flex-end; height:52px; margin-top:10px; position:relative }
.mb { flex:1; border-radius:3px 3px 0 0; min-height:3px }
.tline { position:absolute; left:0; right:0; border-top:2px dashed var(--ink);
        opacity:.4; pointer-events:none }
.tline small { position:absolute; top:-15px; right:0; font-size:.6rem; color:var(--soft);
        background:var(--card); padding:0 3px }
.cc-now { font-size:.74rem; color:var(--soft); margin-top:7px }

/* ---- tables ---- */
table { width:100%; border-collapse:collapse; font-size:.88rem }
th { text-align:right; color:var(--soft); font-weight:500; font-size:.78rem; padding:6px 4px;
     border-bottom:1px solid var(--line) }
th.sortable { cursor:pointer; user-select:none; white-space:nowrap }
th.sortable:hover { color:var(--ink) }
th .arr { font-size:.6rem }
td { padding:8px 4px; border-bottom:1px solid var(--line) }
tr:last-child td { border-bottom:0 }
.amt { font-weight:600; white-space:nowrap }
input { width:100%; padding:10px 14px; border:1px solid var(--line); border-radius:12px;
        font:inherit; background:var(--card); margin-bottom:10px }
.chip { display:none; margin:0 0 10px; padding:7px 14px; background:var(--sel); border:1px solid var(--accent);
        border-radius:20px; font-size:.85rem; cursor:pointer }
.chip.on { display:inline-block }

/* ---- edit mode (only when served via python3 -m kaspion.serve) ---- */
.addrow { display:grid; grid-template-columns:2fr 1fr 1fr 1fr auto; gap:8px }
.addrow select, .addrow button { padding:10px 12px; border:1px solid var(--line); border-radius:12px;
        font:inherit; background:var(--card) }
.addrow button { background:var(--green); color:#fff; border:0; font-weight:700; cursor:pointer }
.addrow button:disabled { opacity:.5 }
button.del { border:0; background:none; cursor:pointer; font-size:.95rem; opacity:.45 }
button.del:hover { opacity:1 }
select.recat { padding:5px 8px; border:1px solid var(--line); border-radius:9px;
        font:inherit; font-size:.82rem; background:var(--card); cursor:pointer }
input.budget-edit { width:5.2em; padding:3px 6px; margin:0; border:1px solid var(--line);
        border-radius:8px; font:inherit; font-size:.82rem; text-align:center; background:var(--bg) }
input.budget-edit:focus { outline:1.5px solid var(--accent); background:var(--card) }
@media (max-width:760px) { .addrow { grid-template-columns:1fr 1fr } }

@media (max-width:760px) {
  body { padding:18px 14px 86px }
  #side { top:auto; bottom:0; left:0; right:0; width:auto; height:64px; flex-direction:row; align-items:center;
          justify-content:space-around; padding:0; border-left:0; border-top:1px solid var(--line); z-index:9 }
  #side .logo, #side .tag, #side .foot, #syncbtn, #syncmsg { display:none }
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
  <div class="foot">עודכן __GENERATED__<br>kaspion · נוצר מ־sync.py</div>
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
    <div class="card"><div class="lbl">הוצאות</div><div class="val" id="spent"></div></div>
    <div class="card"><div class="lbl">תקציב</div><div class="val" id="budget"></div></div>
    <div class="card"><div class="lbl" id="pacelbl"></div><div class="val" id="pace"></div></div>
  </div>
  <div class="banner" id="banner"></div>

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
</section>

<!-- ================= categories ================= -->
<section class="view" id="v-cats">
  <h2 style="margin-top:0">תקציב מול ביצוע <span class="hint">(לחצו על קטגוריה לתנועות שלה · שינוי מספר התקציב נשמר אוטומטית)</span></h2>
  <div class="panel" id="cats"></div>
</section>

<!-- ================= transactions ================= -->
<section class="view" id="v-txns">
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
  <span class="chip" id="chip"></span>
  <input id="s" placeholder="חיפוש בית עסק או קטגוריה… 🔍">
  <div class="panel">
    <table id="t"><thead><tr>
      <th class="sortable" data-k="0">תאריך <span class="arr"></span></th>
      <th class="sortable" data-k="2">בית עסק <span class="arr"></span></th>
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
const PALETTE = ['#1a9e6c','#e0a63a','#5b8def','#e5484d','#8e6fd8','#d97b4f','#4fb3bf','#97a25e','#b8b3ab'];
const VIEWS = { overview:'סקירה', cats:'קטגוריות', txns:'תנועות', trends:'מגמות' };
const ils = x => '₪' + Math.round(x).toLocaleString('he-IL');
const $ = id => document.getElementById(id);

let view = 'overview';
let mi = Math.max(DATA.months.findIndex(m => m.key === DATA.startKey), 0);
let selCat = null;
let sort = { k: 0, dir: -1 };   // default: date, newest first

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

/* ---------- navigation ---------- */
document.querySelectorAll('#side nav a').forEach(a => a.onclick = () => {
  view = a.dataset.v;
  document.querySelectorAll('#side nav a').forEach(x => x.classList.toggle('on', x === a));
  document.querySelectorAll('.view').forEach(s => s.classList.toggle('on', s.id === 'v-' + view));
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
}

function renderOverview(m) {
  $('spent').textContent = ils(m.spent);
  $('budget').textContent = ils(m.budget);
  const under = m.pace >= 0;
  const kotzev = m.isCurrent ? 'לקצב' : 'לתקציב';
  $('pacelbl').textContent = (under ? 'מתחת ' : 'מעל ') + kotzev;
  $('pace').textContent = ils(Math.abs(m.pace));
  $('pace').className = 'val ' + (under ? 'good' : 'bad');
  $('banner').className = 'banner ' + (under ? 'good' : 'bad');
  $('banner').textContent = under
    ? `✅ מעולה! ${m.isCurrent ? 'אתם' : 'הייתם'} ${ils(m.pace)} מתחת ${kotzev}`
    : `⚠️ שימו לב — ${m.isCurrent ? 'אתם' : 'הייתם'} ${ils(-m.pace)} מעל ${kotzev}`;

  // donut: top 6 categories + "אחרים"
  const cats = [...m.cats].sort((a, b) => b.actual - a.actual);
  const top = cats.slice(0, 6);
  const rest = cats.slice(6).reduce((s, c) => s + c.actual, 0);
  const parts = [...top.map(c => ({ name: c.name, v: c.actual })),
                 ...(rest > 0 ? [{ name: 'אחרים', v: rest }] : [])];
  const total = parts.reduce((s, p) => s + p.v, 0) || 1;
  const R = 80, C = 2 * Math.PI * R;
  let off = 0, svg = '';
  parts.forEach((p, i) => {
    const frac = p.v / total;
    svg += `<circle cx="105" cy="105" r="${R}" fill="none" stroke="${PALETTE[i % PALETTE.length]}"
      stroke-width="30" stroke-dasharray="${(frac * C).toFixed(1)} ${C.toFixed(1)}"
      stroke-dashoffset="${(-off * C).toFixed(1)}"></circle>`;
    off += frac;
  });
  $('donut').innerHTML = svg || '';
  $('donut-total').textContent = ils(m.spent);
  $('legend').innerHTML = parts.map((p, i) =>
    `<div class="leg" data-cat="${p.name}">
       <span class="dot" style="background:${PALETTE[i % PALETTE.length]}"></span>
       <span class="nm">${p.name}</span><span class="am">${ils(p.v)}</span>
       <span class="hint">${Math.round(p.v / total * 100)}%</span></div>`).join('')
    || '<div class="hint">אין עדיין הוצאות החודש 🎉</div>';
  document.querySelectorAll('.leg').forEach(el => el.onclick = () => gotoCat(el.dataset.cat));

  $('top5').tBodies[0].innerHTML = [...m.txns].sort((a, b) => b[4] - a[4]).slice(0, 5)
    .map(t => `<tr><td>${t[1]}</td><td>${t[2]}</td><td>${t[3]}</td><td class="amt">${ils(t[4])}</td></tr>`)
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
          <small>₪</small></span></div>
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
}

function gotoCat(name) {
  if (name === 'אחרים') return;
  selCat = name;
  document.querySelector('#side nav a[data-v="txns"]').click();
}

function renderChip() {
  $('chip').className = 'chip' + (selCat ? ' on' : '');
  $('chip').textContent = selCat ? `מציג רק: ${selCat} ✕` : '';
}

function renderTxns() {
  const m = DATA.months[mi];
  const v = $('s').value.trim();
  const rows = m.txns
    .filter(t => !selCat || t[3] === selCat)
    .filter(t => !v || t[2].includes(v) || t[3].includes(v))
    .sort((a, b) => {
      const x = a[sort.k], y = b[sort.k];
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'he')) * sort.dir;
    });
  const catCell = t =>
    `<td><select class="recat" data-m="${t[2]}">${DATA.categories.map(c =>
      `<option value="${c.id}" ${c.id === t[7] ? 'selected' : ''}>${c.name}</option>`).join('')}</select></td>`;
  $('t').tBodies[0].innerHTML = rows.map(t =>
    `<tr><td>${t[1]}</td><td>${t[2]}</td>${catCell(t)}
     <td class="amt">${ils(t[4])}</td><td>${t[5]}</td>
     <td><button class="del" title="הסתרת התנועה" data-id="${t[6]}">🗑</button></td></tr>`).join('')
    || '<tr><td colspan="6" class="hint">לא נמצאו תנועות</td></tr>';
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
}

document.querySelectorAll('#t th.sortable').forEach(th => th.onclick = () => {
  const k = +th.dataset.k;
  sort = { k, dir: sort.k === k ? -sort.dir : (k === 4 ? -1 : 1) };
  renderTxns();
});
$('chip').onclick = () => { selCat = null; renderChip(); renderTxns(); };
$('s').addEventListener('input', renderTxns);

function renderTrends(m) {
  const maxT = Math.max(...DATA.months.map(x => x.spent), 1);
  $('trend').innerHTML = DATA.months.map((x, i) =>
    `<div class="tcol ${i === mi ? 'sel' : ''}" data-i="${i}">
       <div class="tval">${ils(x.spent)}</div>
       <div class="tbar" style="height:${Math.max(x.spent / maxT * 130, 4)}px"></div>
       <div class="tlab">${x.label.split(' ')[0]}</div></div>`).join('');
  document.querySelectorAll('.tcol').forEach(el => el.onclick = () => { mi = +el.dataset.i; render(); });

  $('save').tBodies[0].innerHTML = [...DATA.months].reverse().map(x =>
    `<tr><td>${x.label}</td><td>${ils(x.income)}</td><td>${ils(x.spent)}</td>
     <td class="${x.saved >= 0 ? 'pos' : 'neg'}">${x.saved >= 0 ? '+' : '−'}${ils(Math.abs(x.saved))}</td></tr>`).join('');

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
    // scale to whichever is taller — the biggest month or the target — so the
    // dashed target line always fits inside the chart
    const scale = Math.max(...c.series.map(s => s ? s.actual : 0), budget, 1);
    const withBudget = c.series.filter(s => s && s.status !== 'no_budget').length;
    const under = c.series.filter(s => s && s.status === 'under').length;
    const bars = c.series.map((s, i) => {
      const v = s ? s.actual : 0;
      const col = !s || s.status === 'no_budget' ? 'var(--accent)'
                : s.status === 'under' ? 'var(--green)' : 'var(--red)';
      return `<div class="mb" title="${DATA.months[i].label}: ${ils(v)}"
                   style="height:${Math.max(v / scale * 52, 3)}px;background:${col}"></div>`;
    }).join('');
    const tline = budget
      ? `<div class="tline" style="bottom:${budget / scale * 52}px" title="יעד חודשי: ${ils(budget)}">
           <small>יעד ${ils(budget)}</small></div>`
      : '';
    const ratio = under / Math.max(withBudget, 1);
    const badge = ratio === 1 ? 'ok' : ratio >= 0.5 ? 'mid' : 'bad';
    return `<div class="catcard" data-cat="${c.name}">
      <div class="cc-head"><span>${c.name}</span>
        <span class="badge ${badge}">${under}/${withBudget} בתקציב</span></div>
      <div class="cc-bars">${bars}${tline}</div>
      <div class="cc-now">${ils((c.series.at(-1) || {actual:0}).actual)} החודש · סה"כ ${ils(c.total)}</div>
    </div>`;
  }).join('');
  document.querySelectorAll('.catcard').forEach(el => el.onclick = () => gotoCat(el.dataset.cat));
}

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
