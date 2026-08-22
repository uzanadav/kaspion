const DATA = __DATA__;
// validated (dataviz/scripts/validate_palette.js) categorical palettes, one per theme —
// same hue order, re-stepped for each surface so CVD separation holds in both
const PALETTE_LIGHT = ['#0e9f6e','#c2410c','#2563eb','#dc2626','#7c3aed','#ca8a04','#0d9488','#65a30d'];
const PALETTE_DARK  = ['#12ad82','#dd6b30','#4a86e8','#e04a48','#9268e0','#a67c1a','#0f9488','#78a028'];
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
  amex:     { label: 'אמריקן',   idx: 1 },
  leumi:    { label: 'לאומי',    idx: 0 },
  hapoalim: { label: 'הפועלים',  idx: 3 },
  beinleumi:{ label: 'הבינלאומי',  idx: 7 },
  // both spellings: the scraper's company id is camelCase, the file importer's
  // account_id is lowercase — they must land on the same badge
  oneZero:  { label: 'ONE ZERO', idx: 6 },
  onezero:  { label: 'ONE ZERO', idx: 6 },
  manual:   { label: 'ידני',     idx: null },
};
const issuerOf = k => {
  const e = ISSUERS[k] || { label: k || '—', idx: null };
  return { label: e.label, color: e.idx == null ? (isDark() ? NEUTRAL_DARK : NEUTRAL_LIGHT) : PALETTE()[e.idx] };
};
// Every account that has ever appeared, not just the selected month's: a card with no
// transactions this month stays on screen, because a vanishing pill reads as "that card
// is gone" rather than "that card was quiet". Labelled by issuer, disambiguated by the
// account suffix ONLY when one issuer holds several accounts — the shipped seed database
// has leumi-main and leumi-savings, which would otherwise be two identical "לאומי" pills.
// 'onezero' carries no dash at all, hence the `|| id` fallback.
// color is deliberately NOT cached here: issuerOf reads PALETTE() at call time, so a
// baked-in color would freeze the dots on the old palette after a theme toggle.
const ACCOUNTS = (() => {
  const seen = new Map();                  // account_id -> issuer key, first appearance
  for (const m of DATA.months) for (const t of m.txns) if (!seen.has(t[9])) seen.set(t[9], t[8]);
  const per = new Map();
  for (const iss of seen.values()) per.set(iss, (per.get(iss) || 0) + 1);
  return [...seen].map(([id, iss]) => ({
    id, iss,
    label: per.get(iss) > 1
      ? `${issuerOf(iss).label} ${id.split('-').slice(1).join('-') || id}`
      : issuerOf(iss).label,
  })).sort((a, b) => a.label.localeCompare(b.label, 'he'));
})();
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
// Spend rows, exactly as fct_budget_pacing counts them. t[10] is `amount > 0`, so it does
// NOT catch a negative row filed under 'income' (a PAYBOX reversal, a card fee, interest) —
// pacing excludes category_id='income' outright, and a chart that keeps those rows totals
// ₪761 more than the figure printed above it. Verified against all five months.
const isSpend = t => !t[10] && t[7] !== 'income';
// Charts are drawn in real pixels, never a stretched viewBox: a viewBox scaled to its
// container scales the type with it, and an 11px label becomes 6px on a phone. Safe to
// measure here because applyView() always runs before render(), so #v-trends is on screen
// whenever renderTrends does.
const chartW = el => Math.max(el.clientWidth || 640, 300);
const pathOf = pts => pts.map((p, i) =>
  (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
// element-content escaping (escAttr covers attributes only) — merchant names are free text
// from the bank and go into <title> elements
const escTxt = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

let view = 'overview';
let mi = Math.max(DATA.months.findIndex(m => m.key === DATA.startKey), 0);
let selCat = null;
let flow = 'all';               // money direction shown: all | out (spend) | in (income)
let sort = { k: 0, dir: -1 };   // default: date, newest first
let theme = 'auto';             // auto | light | dark
// insight drill-down. selCat/flow/mi already cover category, direction and month; this
// covers the two things they cannot express: an explicit merchant set, and "still ❔".
let pick = null;   // { merchants: [...], uncat: bool, label: '...' } | null
// which cards the table is limited to: FULL account_ids (t[9]), empty = every card.
// Filtering on the full id rather than the issuer prefix (t[8]) keeps two cards from
// one institution separable — the seed database already has two leumi accounts.
let accs = [];
// which months the totals report sums. Month KEYS, never indices — importing a statement
// adds months and shifts every index. [] means "every month that has already happened".
let sumMonths = [];

/* ---------- keep your place across the reload every edit triggers ---------- */
// Saving a category rebuilds the page and reloads it; without this you'd be thrown
// back to the overview on the default month after every single correction.
const UI_KEY = 'kaspion.ui';
function saveUi() {
  try {
    sessionStorage.setItem(UI_KEY, JSON.stringify({
      view, month: DATA.months[mi] ? DATA.months[mi].key : null,
      selCat, sort, flow, search: $('s') ? $('s').value : '', theme, pick, accs, sumMonths,
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
  // drop account ids that no longer exist (card removed, database rebuilt): a stale id
  // would silently filter the table down to nothing with no visible cause
  if (Array.isArray(saved.accs)) accs = saved.accs.filter(a => ACCOUNTS.some(x => x.id === a));
  // drop month keys that no longer exist, same reason as accs above: a stale key would
  // silently sum nothing with no visible cause
  if (Array.isArray(saved.sumMonths)) {
    sumMonths = saved.sumMonths.filter(k => DATA.months.some(m => m.key === k));
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
const SERVER_URL = 'http://127.0.0.1:8765';
const API = location.protocol.startsWith('http') ? '' : SERVER_URL;
// last resort, shown only if the one-click start below never brings the server up
const SERVER_DOWN_MSG = 'לא הצלחנו להפעיל את כספיון מכאן. ' +
  'לחצו פעמיים על הקובץ kaspion בתיקיית ההתקנה, ואז נסו שוב.';
const isDown = e => e.message.includes('fetch');   // failed to connect at all

// A page cannot start a process, but it can open a URL: the launcher registers a
// kaspion:// handler (Kaspion.app on macOS, HKCU\Software\Classes on Windows) that runs
// the launcher, so "kaspion isn't running" is one button instead of a terminal command.
function showServerDown() {
  $('down-msg').textContent = '';
  $('downgo').disabled = false;
  if (!$('downdlg').open) $('downdlg').showModal();
}
$('downgo').onclick = () => {
  $('downgo').disabled = true;
  $('down-msg').textContent = 'מפעילים… (אם נפתחת שאלה של הדפדפן, אשרו אותה)';
  location.href = 'kaspion://start';
  let tries = 0;
  const t = setInterval(async () => {
    try {
      await fetch(API + '/api/sync-status');   // any answer at all means it's up
      clearInterval(t);
      location.href = SERVER_URL;              // land on the served page, edit mode on
    } catch (e) {
      // ~60s: a cold start builds the report before it binds the port
      if (++tries > 60) {
        clearInterval(t);
        $('downgo').disabled = false;
        $('down-msg').textContent = SERVER_DOWN_MSG;
      }
    }
  }, 1000);
};
{
  const sel = $('a-cat');
  sel.innerHTML = DATA.categories.map(c =>
    `<option value="${escAttr(c.id)}">${escTxt(c.name)}</option>`).join('');
  sel.value = 'other';
  $('a-date').value = new Date().toISOString().slice(0, 10);
  $('a-go').onclick = async () => {
    const desc = $('a-desc').value.trim(), amt = parseFloat($('a-amt').value);
    if (!desc || !(amt > 0)) { $('a-msg').textContent = 'צריך תיאור וסכום חיובי'; return; }
    await api('/api/add', { description: desc, amount: amt,
                            category: sel.value, date: $('a-date').value });
  };
}
// server-side error_type -> Hebrew, for endpoints where the failure kind matters
// (an add-account attempt is the only caller today; scrape.js's own codes)
const ERROR_TYPE_HE = {
  INVALID_PASSWORD: 'שם המשתמש או הסיסמה שגויים — בדקו באתר הבנק ונסו שוב',
  CHANGE_PASSWORD: 'הבנק דורש החלפת סיסמה — החליפו באתר שלו ונסו שוב',
  ACCOUNT_BLOCKED: 'החשבון נחסם על ידי הבנק — יש לפנות אליו',
  TIMEOUT: 'ההתחברות ארכה זמן רב מדי — נסו שוב מאוחר יותר',
  UNKNOWN: 'ההתחברות נכשלה. לפעמים הבנק חוסם התחברות אוטומטית — נסו שוב מאוחר יותר',
};
async function api(path, payload, msgId = 'a-msg', busy = 'שומר…') {
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  $(msgId).textContent = busy;
  try {
    const r = await fetch(API + path, { method: 'POST', body: JSON.stringify(payload) });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error_type ? (ERROR_TYPE_HE[j.error_type] || ERROR_TYPE_HE.UNKNOWN)
                                             : (j.error || 'failed'));
    location.reload();
  } catch (e) {
    document.querySelectorAll('button').forEach(b => b.disabled = false);
    if (isDown(e)) { $(msgId).textContent = ''; showServerDown(); return; }
    const msg = 'שגיאה: ' + e.message;
    $(msgId).textContent = msg;
    // msgId's own text is enough when the caller's form is on screen (add-transaction,
    // add-category); everything else — deleting a row, recategorizing, editing a budget —
    // has no visible message div nearby, so the failure needs a surface that is never
    // hidden inside a collapsed panel or a scrolled-past section
    $('toast').textContent = msg + ' · לסגירה, לחצו כאן';
    $('toast').className = 'toast on';
  }
}

// live progress while a sync runs, shown in a centered dialog (same pattern as
// add-account): the /api/sync POST itself doesn't resolve until the whole pipeline
// (scrape every institution + dbt + categorize) is done, which can take minutes — this
// polls a separate, lightweight status endpoint so "מקס — 12 רשומות חדשות" shows up per
// institution as it happens, not as one message at the very end. Each line's leading
// mark (✓/✗ from scraper_loader.py's STATUS:: lines) decides its color; plain
// "מתחברים אל…"/stage lines stay neutral.
function renderSyncLog(lines) {
  $('sync-log').innerHTML = lines.map(l => {
    const cls = l.startsWith('✓') || l.startsWith('✔') ? 'ok' : l.startsWith('✗') ? 'err' : '';
    return `<div class="syncline ${cls}">${escTxt(l)}</div>`;
  }).join('');
  $('sync-log').scrollTop = $('sync-log').scrollHeight;
}
$('syncbtn').onclick = async () => {
  $('sync-log').innerHTML = '';
  $('sync-icon').className = 'sync-icon spin';
  $('sync-icon').textContent = '';
  $('syncdlg').showModal();
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  let started = false;
  const poll = setInterval(async () => {
    try {
      const r = await fetch(API + '/api/sync-status');
      const j = await r.json();
      if (j.running) started = true;
      renderSyncLog(j.lines);
      // only stop once OUR run has been seen starting and then finishing — a stray
      // early tick that catches the server between runs must not cut polling short
      if (started && !j.running) clearInterval(poll);
    } catch (e) { /* transient poll failure — the main request below still settles */ }
  }, 1000);
  try {
    const r = await fetch(API + '/api/sync', { method: 'POST', body: '{}' });
    const j = await r.json();
    if (!j.ok) { const err = new Error(j.error || 'failed'); err.detail = j.detail; throw err; }
    clearInterval(poll);
    $('sync-icon').className = 'sync-icon ok';
    $('sync-icon').textContent = '✓';
    setTimeout(() => location.reload(), 700); // let the green confirmation register first
  } catch (e) {
    clearInterval(poll);
    document.querySelectorAll('button').forEach(b => b.disabled = false);
    if (isDown(e)) { $('syncdlg').close(); showServerDown(); return; }
    $('sync-icon').className = 'sync-icon err';
    $('sync-icon').textContent = '✗';
    // the raw output (a Python traceback, usually) is real information for whoever
    // has to fix it and noise for everyone else — collapsed, never the headline
    $('sync-log').innerHTML += `<div class="syncline err">${escTxt(e.message)}</div>` +
      (e.detail ? `<details class="det"><summary>פרטים טכניים</summary>` +
                  `<pre>${escTxt(e.detail)}</pre></details>` : '');
  }
};

/* ---------- managing the category list ---------- */
function renderCatManager() {
  const custom = DATA.categories.filter(c => c.custom);
  $('nc-list').innerHTML = custom.length
    ? `<div class="hint" style="margin-bottom:6px">קטגוריות שהוספתם:</div>` + custom.map(c =>
        `<span class="ctag">${escTxt(c.name)}
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
    $('u-msg').textContent = e.message.includes('fetch') ? SERVER_DOWN_MSG : 'שגיאה: ' + e.message;
    document.querySelectorAll('button').forEach(b => b.disabled = false);
  }
};

/* ---------- add-account dialog ---------- */
// Institutions marked "blocked" (isracard/amex: reCAPTCHA; oneZero: needs interactive
// 2FA enrollment) sit in their own disabled optgroup rather than being offered as a
// working login — their statement upload lives on the transactions view instead.
//
// A company can have more than one saved connection (a bank/card both people in the
// household use, each with their own login) — DATA.connected is a list of
// {id, company, label}, not a set of company ids. Choosing an institution ALWAYS opens
// a blank form; there is no "select to edit". To fix a bad login, remove it from the
// connected list and add it again.
let acctPick = null;
const connLabel = c => {
  const inst = DATA.institutions.find(i => i.id === c.company);
  const base = inst ? inst.label : c.company;
  // label the owner gave it, else the numeric suffix of a :2/:3 connection id, else
  // nothing extra — a company's only connection needs no disambiguation
  const extra = c.label || (c.id.includes(':') ? c.id.split(':')[1] : '');
  return extra ? `${base} (${extra})` : base;
};
function renderAccountPicker() {
  const byCompany = {};
  DATA.connected.forEach(c => (byCompany[c.company] ??= []).push(c));
  // escTxt for text content (escapes <), escAttr for attribute values (escapes ").
  // They are NOT interchangeable — connLabel() below embeds an owner-typed free-text
  // label, so text content built with escAttr would let "<img onerror=…>" execute.
  const opt = i => {
    const n = (byCompany[i.id] || []).length;
    const mark = n > 1 ? ` — ${n} מחוברים` : n === 1 ? ' ✓' : '';
    return `<option value="${escAttr(i.id)}">${escTxt(i.label)}${mark}</option>`;
  };
  const pickable = t => DATA.institutions.filter(i => i.type === t && !i.blocked);
  // blocked ones get their own group: the label carries the reason once, and the two
  // real groups stay free of rows that cannot be chosen
  const blocked = DATA.institutions.filter(i => i.blocked);
  $('acct-select').innerHTML = `
    <option value="" disabled selected hidden>בחרו בנק או כרטיס אשראי…</option>
    <optgroup label="חשבונות בנק">${pickable('bank').map(opt).join('')}</optgroup>
    <optgroup label="כרטיסי אשראי">${pickable('credit_card').map(opt).join('')}</optgroup>
    <optgroup label="🔒 רק דרך טעינת קובץ (בעמוד תנועות)">${
      blocked.map(i => `<option disabled>${escTxt(i.label)}</option>`).join('')
    }</optgroup>`;
  $('acct-select').onchange = () => {
    acctPick = DATA.institutions.find(i => i.id === $('acct-select').value);
    renderAccountForm();
    $('acct-form').scrollIntoView({ block: 'nearest' });
  };
  // Its own container, never rewritten by picking an institution. This is the only
  // place connected accounts are visible now that a closed <select> shows nothing —
  // it is load-bearing, not decoration.
  $('acct-connected').innerHTML = DATA.connected.length ? `
    <div class="hint" style="margin:14px 0 6px">חשבונות מחוברים כרגע</div>
    <div>${DATA.connected.map(c => `<span class="ctag">${escTxt(connLabel(c))}
        <button class="acctdel" data-id="${escAttr(c.id)}" data-label="${escAttr(connLabel(c))}"
                title="הסרת החיבור">✕</button></span>`).join('')}</div>` : '';
  document.querySelectorAll('.acctdel').forEach(b => b.onclick = () => {
    if (!confirm(`להסיר את החיבור ל"${b.dataset.label}"? תנועות שכבר נשמרו יישארו.`)) return;
    api('/api/remove-account', { connection: b.dataset.id }, 'acct-msg', 'מסיר…');
  });
}
function renderAccountForm() {
  if (!acctPick) { $('acct-form').innerHTML = ''; return; }
  const n = DATA.connected.filter(c => c.company === acctPick.id).length;
  $('acct-form').innerHTML = `
    <div style="font-weight:700; margin:10px 0">${escAttr(acctPick.label)}</div>
    ${n > 0 ? `<input class="acct-meta" id="acct-label"
        placeholder="תווית (למשל: שלי / של אשתי) — אופציונלי">` : ''}
    ${acctPick.fields.map(f => `<input class="acct-f" data-f="${escAttr(f.name)}"
        type="${f.secret ? 'password' : 'text'}" autocomplete="new-password" spellcheck="false"
        placeholder="${escAttr(f.label)}">`).join('')}
    <div class="hint" style="margin:8px 0">ההתחברות ומשיכת ההיסטוריה לוקחות 1–3 דקות —
      נא לא לסגור את הדף</div>
    <button id="acct-go">${n > 0 ? 'חיבור חשבון נוסף' : 'התחברות ושמירה'}</button>`;
  $('acct-go').onclick = async () => {
    const credentials = {};
    document.querySelectorAll('.acct-f').forEach(inp => { credentials[inp.dataset.f] = inp.value.trim(); });
    if (Object.values(credentials).some(v => !v)) { $('acct-msg').textContent = 'יש למלא את כל השדות'; return; }
    const label = $('acct-label') ? $('acct-label').value.trim() : '';
    // clear before the request, not after — nothing survives into the reload
    document.querySelectorAll('.acct-f').forEach(inp => { inp.value = ''; });
    if ($('acct-label')) $('acct-label').value = '';
    await api('/api/add-account', { company: acctPick.id, credentials, label },
      'acct-msg', 'מתחברים ומושכים תנועות… (1–3 דקות)');
  };
}
$('addacct').onclick = () => {
  acctPick = null;
  renderAccountPicker();
  $('acct-form').innerHTML = '';
  $('acct-msg').textContent = '';
  $('acctdlg').showModal();
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

// First-run state: no transactions yet, so every month-keyed view has nothing to draw.
// The #empty panel is static markup in app.html — shown/hidden here rather than written
// over a view, so nothing is destroyed and the views work the moment data arrives.
function renderEmptyState() {
  $('subline').textContent = '';
  $('months').innerHTML = '';
  // תנועות stays fully reachable and rendered: it hosts the file-upload form, which is
  // one of only two ways to get data in (➕ הוספת חשבון is the other) — and the welcome
  // text points at it, so making it unreachable would be a dead end.
  const showTxns = view === 'txns';
  $('vtitle').textContent = showTxns ? VIEWS[view] : 'ברוכים הבאים לכספיון';
  $('empty').hidden = showTxns;
  document.querySelectorAll('.view')
    .forEach(s => s.classList.toggle('on', showTxns && s.id === 'v-txns'));
  if (showTxns) { renderChip(); renderTxns(); }
  saveUi();
}

/* ---------- render ---------- */
function render() {
  // A brand-new install has no transactions. Every renderer below assumes a month
  // object exists (DATA.months[mi]), so this is handled once here rather than
  // guarded in each of them.
  if (!DATA.months.length) return renderEmptyState();
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
  accs = link.accs || [];        // an insight points at specific rows, so a standing card
                                 // filter is cleared unless the link is ABOUT a card
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
  // every amount is an LTR run inside RTL text: without isolation "₪29,192" beside a
  // month name renders reversed — the bug that started the redesign
  const nums = s => s.replace(/₪[\d,]+|\d[\d,]*(?:\.\d+)?%?/g,
                              t => `<span class="num">${t}</span>`);
  box.innerHTML = items.map((i, n) =>
    `<div class="ins ${i.tone}${i.link ? ' go' : ''}" data-n="${n}"${
       i.link ? ' title="לחצו כדי לראות את התנועות שמאחורי התובנה"' : ''
     }><span class="ins-dot"></span><span class="ins-txt">${nums(escTxt(i.text))}</span>${
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
    `<div class="leg" data-cat="${escAttr(p.name)}">
       <span class="dot" style="background:${pal[i % pal.length]}"></span>
       <span class="nm">${escTxt(p.name)}</span><span class="am">${ils(p.v)}</span>
       <span class="hint">${Math.round(p.v / total * 100)}%</span></div>`).join('')
    || '<div class="hint">אין עדיין הוצאות החודש 🎉</div>';
  document.querySelectorAll('.leg').forEach(el => el.onclick = () => gotoCat(el.dataset.cat));

  // biggest EXPENSES — m.txns now carries income too, and a salary would otherwise
  // sit at the top of a list titled "the 5 biggest expenses". isSpend also excludes a
  // negative row filed under 'income' (a PAYBOX reversal, a card fee) — it is not an
  // expense either, and fct_budget_pacing already leaves it out of the ₪ total above this.
  $('top5').tBodies[0].innerHTML = [...m.txns].filter(isSpend).sort((a, b) => b[4] - a[4]).slice(0, 5)
    .map(t => `<tr><td class="num">${t[1]}</td><td>${escTxt(t[2])}</td><td>${escTxt(t[3])}</td>
       <td class="amt nums">${ils(t[4])}</td></tr>`)
    .join('') || '<tr><td colspan="4" class="hint">אין תנועות</td></tr>';
}

// Where the budget sits on every bullet track, as a % of its width. Fixed rather than
// per-row so the target lines form one straight column, and the space beyond it is the
// headroom an over-budget row spills into.
const BUDGET_MARK = 72;

function renderCats(m) {
  $('cats').innerHTML = m.cats.map(c => {
    const ratio = c.budget ? c.actual / c.budget : 0;
    const inPct = Math.min(ratio, 1) * BUDGET_MARK;
    // Overflow is compressed: twice the budget fills the headroom completely, and worse
    // than that saturates. The exact shekel figure rides in the badge, so the cap costs
    // emphasis, never information.
    const overPct = ratio > 1 ? Math.min(ratio - 1, 1) * (100 - BUDGET_MARK) : 0;
    const over = c.budget > 0 && c.actual > c.budget;
    // Status is never colour alone: each badge carries a glyph AND words AND the number
    // that says what to do about it.
    const badge = !c.budget
      ? '<span class="badge none">ללא תקציב</span>'
      : over
        ? `<span class="badge bad">⚠ חריגה ${ils(c.actual - c.budget)}</span>`
        : `<span class="badge ok">✓ נשאר ${ils(c.budget - c.actual)}</span>`;
    return `<div class="cat" data-cat="${escAttr(c.name)}">
      <div class="cat-line">
        <span class="cat-name">${escTxt(c.name)}</span>
        <span class="cat-actual num">${ils(c.actual)}</span>
        ${c.budget ? `<span class="cat-pct">${Math.round(ratio * 100)}%</span>` : ''}
        <span class="cat-budget">
          <span>תקציב</span>
          <input type="number" class="budget-edit" data-id="${escAttr(c.id)}" value="${c.budget || ''}"
                 min="0" step="50" placeholder="—" title="שינוי התקציב החודשי — נשמר אוטומטית">
          <span>₪</span>${c.suggested
            ? '<span class="sugg-tag" title="חושב אוטומטית מהממוצע של 3 החודשים האחרונים — כל שינוי ידני יחליף אותו לצמיתות">מוצע</span>'
            : ''}</span>
        ${badge}
      </div>
      <div class="bullet" title="${escAttr(c.budget
          ? `${Math.round(ratio * 100)}% מהתקציב` : 'לא הוגדר תקציב')}">
        <div class="track">
          <i class="b-in${overPct ? ' split' : ''}" style="width:${inPct}%"></i>
          ${overPct ? `<i class="b-over" style="width:${overPct}%"></i>` : ''}
        </div>
        ${c.budget ? `<span class="tick" style="inset-inline-start:${BUDGET_MARK}%"></span>` : ''}
      </div>
    </div>`;
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

// Counts are measured against `base`: every other active filter applied, this control's
// OWN selection not applied. Applying accs here would zero every unselected pill the
// moment one card is picked, making it impossible to see what adding a second would add.
function renderAccPills(base) {
  const n = id => base.reduce((c, t) => c + (t[9] === id ? 1 : 0), 0);
  $('accseg').innerHTML =
    `<button data-a="" class="${accs.length ? '' : 'on'}">הכל <span class="num">${base.length}</span></button>` +
    ACCOUNTS.map(a => `<button data-a="${escAttr(a.id)}" class="${accs.includes(a.id) ? 'on' : ''}"
      title="${escAttr(a.id)}"><span class="iss"><i style="background:${issuerOf(a.iss).color}"></i>${
      a.label}</span> <span class="num">${n(a.id)}</span></button>`).join('');
  $('accseg').querySelectorAll('button').forEach(b => b.onclick = () => {
    const id = b.dataset.a;
    if (!id) accs = [];                                        // "הכל" clears the selection
    else accs = accs.includes(id) ? accs.filter(x => x !== id) : [...accs, id];
    renderTxns();                                              // re-renders these pills too
  });
}

function renderTxns() {
  // `|| { txns: [] }` covers the fresh-install case: renderEmptyState() still renders
  // this view (for the upload form) when there are no months at all.
  const m = DATA.months[mi] || { txns: [] };
  const v = $('s').value.trim();
  // keep the segmented control in step with `flow`, including after a restore
  document.querySelectorAll('#fseg button')
    .forEach(b => b.classList.toggle('on', b.dataset.f === flow));
  // every filter EXCEPT the card pills — this is what the pill counts are measured against
  const base = m.txns
    .filter(t => flow === 'all' || (flow === 'in' ? t[10] : !t[10]))
    .filter(t => !selCat || t[3] === selCat)
    // t[11] is merchant_key, t[5] the '🤖'/'✅'/'❔' glyph — see _collect()'s row layout
    .filter(t => !pick || (pick.uncat ? (t[5] === '❔' && !t[10])
                                      : pick.merchants.includes(t[11])))
    // search matches merchant, category, and the card it came from ("מקס", "ישראכרט"…)
    .filter(t => !v || t[2].includes(v) || t[3].includes(v) || issuerOf(t[8]).label.includes(v));
  renderAccPills(base);
  const rows = base
    // t[9] is the FULL account_id; an empty selection means every card
    .filter(t => !accs.length || accs.includes(t[9]))
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
    ? `<td><span class="catname">${escTxt(t[3])}</span></td>`
    : `<td><select class="recat" data-m="${escAttr(t[2])}">${DATA.categories.map(c =>
      `<option value="${escAttr(c.id)}" ${c.id === t[7] ? 'selected' : ''}>${escTxt(c.name)}</option>`
      ).join('')}</select></td>`;
  const issCell = t => {
    const s = issuerOf(t[8]);
    return `<td><span class="iss" title="${escAttr(t[9] || s.label)}">
      <i style="background:${s.color}"></i>${s.label}</span></td>`;
  };
  $('t').tBodies[0].innerHTML = rows.map(t =>
    `<tr><td class="num">${t[1]}</td><td>${escTxt(t[2])}</td>${issCell(t)}${catCell(t)}
     <td class="amt nums ${t[10] ? 'in' : ''}">${t[10] ? '+' : ''}${ils(t[4])}</td><td>${t[5]}</td>
     <td><button class="del" title="הסתרת התנועה" data-id="${escAttr(t[6])}">🗑</button></td></tr>`).join('')
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

// the SVG charts are sized in real pixels, so a window resize has to redraw them
let rszT;
addEventListener('resize', () => {
  clearTimeout(rszT);
  rszT = setTimeout(() => { if (view === 'trends') renderTrends(DATA.months[mi]); }, 150);
});

// 5 gridlines (0/25/50/75/100% of the axis top), 4 labelled — a lone top figure over an
// otherwise bare chart leaves every point floating with nothing to read its value against.
const yTicks = (Y, top, W) => {
  const fracs = [0, .25, .5, .75, 1];
  return fracs.map(f => `<line class="grid" x1="0" y1="${Y(top * f).toFixed(1)}" x2="${
      W}" y2="${Y(top * f).toFixed(1)}"></line>`).join('')
    + fracs.filter(f => f > 0).map(f => `<text class="fax" x="${W - 3}" y="${
        (Y(top * f) - 6).toFixed(1)}" text-anchor="end">${ils(top * f)}</text>`).join('');
};

/* ---------- trends: income vs spend on ONE scale ----------
   Same unit, so never two axes: the whole point is the distance between the lines. */
const FLOW_H = 210;
function drawFlow() {
  const el = $('trend'), W = chartW(el), H = FLOW_H;
  const PT = 30, PB = 26, PX = 44;              // room for the axis top and the month row
  const ms = DATA.months, n = ms.length;
  const top = niceCeil(Math.max(...ms.map(v => Math.max(v.spent, v.income)), 1));
  // RTL: the month strip, .cc-bars and every other chart on this page run right-to-left,
  // so index 0 sits at the RIGHT edge and x counts DOWN from W.
  const X = i => n < 2 ? W / 2 : W - PX - i * (W - 2 * PX) / (n - 1);
  const Y = v => PT + (1 - v / top) * (H - PT - PB);
  // income 0 means "never loaded", not "earned nothing" — the same rule insights.py runs
  // on — so it becomes a GAP. Plotting it as zero invents a month with no income.
  const inc = ms.map(v => v.income > 0 ? v.income : null);
  const sp = ms.map(v => v.spent);

  // The band between the lines, built as RUNS of constant sign with the crossing point
  // interpolated. One quad per month would be shorter but two quads that merely touch
  // leave a hairline antialiasing seam down every shared edge.
  const band = [];
  let run = null;
  const closeRun = () => {
    if (run && run.a.length > 1) band.push(`<path d="${
      pathOf([...run.a, ...[...run.b].reverse()])}Z" fill="${
      run.s > 0 ? 'var(--pos)' : 'var(--neg)'}" opacity=".14"></path>`);
    run = null;
  };
  for (let i = 0; i < n; i++) {
    const a = ms[i], b = ms[i + 1];
    if (inc[i] == null) { closeRun(); continue; }        // no income loaded -> no band
    const s = a.income - a.spent >= 0 ? 1 : -1;
    if (!run || run.s !== s) { closeRun(); run = { s, a: [], b: [] }; }
    run.a.push([X(i), Y(a.income)]); run.b.push([X(i), Y(a.spent)]);
    if (!b || inc[i + 1] == null) { closeRun(); continue; }
    const d0 = a.income - a.spent, d1 = b.income - b.spent;
    if (d0 * d1 < 0) {                                    // the lines cross inside this segment
      const t = d0 / (d0 - d1);                           // 0..1 along it
      const cx = X(i) + t * (X(i + 1) - X(i));
      const cy = Y(a.income) + t * (Y(b.income) - Y(a.income));
      run.a.push([cx, cy]); run.b.push([cx, cy]);         // both series meet here
      closeRun();
      run = { s: -s, a: [[cx, cy]], b: [[cx, cy]] };
    }
  }
  closeRun();

  // one <path> per segment: a single path cannot carry two dash patterns, and drawing a
  // partial month solid would claim data the month does not have
  const line = (vals, color, name, dy) => {
    let out = '', last = -1;
    for (let i = 0; i + 1 < n; i++) {
      if (vals[i] == null || vals[i + 1] == null) continue;
      const solid = ms[i].complete && ms[i + 1].complete;
      out += `<path d="${pathOf([[X(i), Y(vals[i])], [X(i + 1), Y(vals[i + 1])]])}" fill="none"
        stroke="${color}" stroke-width="2.5" stroke-linecap="round"${
        solid ? '' : ' stroke-dasharray="5 4"'}></path>`;
    }
    for (let i = 0; i < n; i++) {
      if (vals[i] == null) continue;
      last = i;
      // hollow = this month is not over, so the point is not final
      out += `<circle cx="${X(i).toFixed(1)}" cy="${Y(vals[i]).toFixed(1)}" r="4.5" fill="${
        ms[i].complete ? color : 'var(--surface)'}" stroke="${color}" stroke-width="2"></circle>`;
    }
    if (last >= 0) {
      // clamped into a safe band so a value near the baseline (Sept spend is ₪291) never
      // prints the label on top of the month-tick row below it, and a value near the top
      // never prints it on top of the axis figure above it
      const ly = Math.min(Math.max(Y(vals[last]) + dy, PT + 10), H - PB - 6);
      out += `<text class="flab" x="${X(last).toFixed(1)}" y="${
        ly.toFixed(1)}" fill="${color}" text-anchor="middle">${name}</text>`;
    }
    return out;
  };

  // full-height hit box per month: the native tooltip, the hover highlight and the month
  // click the old bars carried. Newlines below are REAL line breaks inside a template
  // literal, not an escape sequence — this whole file is a Python triple-quoted string.
  const hw = n < 2 ? W : (W - 2 * PX) / (n - 1);
  const hit = ms.map((v, i) => `<rect class="hit ${i === mi ? 'sel' : ''}" data-i="${i}"
      x="${(X(i) - hw / 2).toFixed(1)}" y="0" width="${hw.toFixed(1)}" height="${H - PB + 8}"
      fill="transparent"><title>${escTxt(v.label)}${v.complete ? '' : ' (חודש חלקי)'}
הכנסות: ${v.income ? ils(v.income) : 'לא נטענו'}
הוצאות: ${ils(v.spent)}${v.income ? `
${v.saved >= 0 ? 'נשאר' : 'חריגה'}: ${ils(Math.abs(v.saved))}` : ''}</title></rect>`).join('');

  const labs = ms.map((v, i) => `<text class="fmon ${i === mi ? 'sel' : ''}" x="${
    X(i).toFixed(1)}" y="${H - 7}" text-anchor="middle">${
    v.label.split(' ')[0].slice(0, 3)}</text>`).join('');

  // band first (behind), income last of the two lines (it is the figure to land on),
  // hit boxes on top of everything
  el.innerHTML = `<svg class="fsvg" width="${W}" height="${H}">
    ${yTicks(Y, top, W)}
    ${band.join('')}${line(sp, 'var(--neg)', 'הוצאות', 17)}${line(inc, 'var(--pos)', 'הכנסות', -11)}
    ${labs}${hit}</svg>`;
  el.querySelectorAll('.hit').forEach(r => r.onclick = () => { mi = +r.dataset.i; render(); });
}

/* ---------- trends: how fast the month is being spent ---------- */
const PACE_H = 190, PACE_DAYS = 31;
function drawPace() {
  const el = $('pace'), W = chartW(el), H = PACE_H;
  const PT = 18, PB = 24, PX = 40;
  // partial months are excluded outright: a month whose data starts on the 7th draws a
  // flat first week and reads as a frugal start rather than as missing data
  const ms = DATA.months.filter(v => v.complete || v.isCurrent).slice(-6);
  if (!ms.length) {
    el.innerHTML = '<div class="hint">אין עדיין חודש שלם להשוואה</div>';
    $('placegend').innerHTML = ''; return;
  }
  const series = ms.map(v => {
    const per = Array(PACE_DAYS + 2).fill(0);
    for (const t of v.txns) if (isSpend(t)) per[+t[0].slice(8, 10)] += t[4];
    const cum = []; let acc = 0;
    for (let d = 1; d <= PACE_DAYS; d++) { acc += per[d]; cum.push(acc); }
    // the running month stops at TODAY. A card charge dated the 27th is already on the
    // statement, and drawing it would show money as spent that has not left yet.
    return { m: v, cum, upto: v.isCurrent ? Math.min(DATA.curDay || PACE_DAYS, PACE_DAYS) : PACE_DAYS };
  });
  const top = niceCeil(Math.max(...series.map(s => s.cum[s.upto - 1]), 1));
  const X = d => W - PX - (d - 1) * (W - 2 * PX) / (PACE_DAYS - 1);   // day 1 at the RIGHT
  const Y = v => PT + (1 - v / top) * (H - PT - PB);
  // the running month is the one question this chart answers ("am I ahead of usual?"), so
  // it gets the neutral high-contrast ink colour, not a semantic red — pace itself isn't
  // bad. Finished months are context, individually identifiable from the same categorical
  // palette every other chart on this page uses, not indistinguishable shades of one grey.
  const cur = 'var(--ink)', pal = PALETTE();
  const pastColor = k => pal[k % pal.length];

  const lines = series.map((s, k) => {
    const pts = [];
    for (let d = 1; d <= s.upto; d++) pts.push([X(d), Y(s.cum[d - 1])]);
    const isCur = s.m.isCurrent;
    const color = isCur ? cur : pastColor(k);
    const o = isCur ? 1 : 0.75;
    return `<path d="${pathOf(pts)}" fill="none" stroke="${color}"
      stroke-width="${isCur ? 2.5 : 1.8}" stroke-linecap="round" opacity="${o}"></path>`
      + (pts.length ? `<circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${
         pts[pts.length - 1][1].toFixed(1)}" r="${isCur ? 4.5 : 3}" fill="${color}"
         opacity="${o}"></circle>` : '')
      + (isCur ? `<text class="flab" x="${pts[pts.length - 1][0].toFixed(1)}" y="${
         (pts[pts.length - 1][1] - 10).toFixed(1)}" fill="${cur}" text-anchor="middle">${
         s.m.label.split(' ')[0]}</text>` : '');
  }).join('');

  // one hit column per day, listing every month at that day — the crosshair tooltip, for
  // free, from a native <title>. The line break in the join() below is a real newline
  // inside the Python source, carrying straight through into the JS template literal.
  const hw = (W - 2 * PX) / (PACE_DAYS - 1);
  const hit = Array.from({ length: PACE_DAYS }, (_, k) => {
    const d = k + 1;
    const rows = series.filter(s => d <= s.upto)
      .map(s => `${s.m.label.split(' ')[0]}: ${ils(s.cum[d - 1])}`).join('\n');
    return `<rect class="hit" x="${(X(d) - hw / 2).toFixed(1)}" y="0" width="${hw.toFixed(1)}"
      height="${H - PB + 6}" fill="transparent"><title>יום ${d}
${rows}</title></rect>`;
  }).join('');

  const ticks = [1, 7, 14, 21, 28].map(d =>
    `<text class="fmon" x="${X(d).toFixed(1)}" y="${H - 7}" text-anchor="middle">${d}</text>`).join('');

  el.innerHTML = `<svg class="fsvg" width="${W}" height="${H}">
    ${yTicks(Y, top, W)}
    ${lines}${ticks}${hit}</svg>`;
  $('placegend').innerHTML = series.map((s, k) =>
    `<span class="tkey"><i style="border-color:${s.m.isCurrent ? cur : pastColor(k)}"></i>${
      s.m.label.split(' ')[0]}${s.m.isCurrent ? ` (עד ${s.upto} בחודש)` : ''}</span>`).join('');
}

/* ---------- trends: spend by card ---------- */
const CARDS_H = 150;      // must match .sbar { height } in the stylesheet
function drawCards() {
  const ms = DATA.months;
  const per = ms.map(v => {
    const by = new Map();
    for (const t of v.txns) if (isSpend(t)) by.set(t[9], (by.get(t[9]) || 0) + t[4]);
    return by;
  });
  // isSpend() is the same rule fct_budget_pacing applies, so every stack totals its own
  // month's `spent` exactly and the columns agree with the ₪ figures everywhere else
  const top = niceCeil(Math.max(...per.map(by => [...by.values()].reduce((a, b) => a + b, 0)), 1));
  // ACCOUNTS order, identical in every column, so the eye can follow one card across time.
  // issuerOf() is called HERE and never cached — a baked-in colour freezes the old palette
  // after a theme toggle.
  $('cards').innerHTML = ms.map((v, i) => {
    const segs = ACCOUNTS.filter(a => per[i].get(a.id) > 0).map(a => {
      const amt = per[i].get(a.id);
      return `<div class="sseg" data-i="${i}" data-a="${escAttr(a.id)}"
        title="${escAttr(v.label + ' · ' + a.label)} — ${ils(amt)}"
        style="height:${Math.max(amt / top * CARDS_H, 4).toFixed(1)}px;background:${
        issuerOf(a.iss).color}"></div>`;
    }).join('');
    return `<div class="scol"><div class="sbar">${segs}</div>
      <div class="tlab ${i === mi ? 'sel' : ''}">${v.label.split(' ')[0].slice(0, 3)}</div></div>`;
  }).join('');
  $('cards').querySelectorAll('.sseg').forEach(s => s.onclick = () =>
    openInsight({ view: 'txns', month: ms[+s.dataset.i].key, accs: [s.dataset.a] }));
  $('clegend').innerHTML = ACCOUNTS.map(a =>
    `<span class="tkey"><b style="background:${issuerOf(a.iss).color}"></b>${a.label}</span>`).join('');
}

/* ---------- trends: where the money went ---------- */
function drawDests() {
  const ds = DATA.destinations || [];
  const top = Math.max(...ds.map(d => d.total), 1);
  $('dests').innerHTML = ds.map((d, i) => `<div class="dest" data-i="${i}"
      title="${escAttr(d.label)} — ${ils(d.total)}${d.keys.length > 1
        ? ` · ${d.keys.length} חיובים באותה סדרה` : ''}">
      <span class="dname">${escTxt(d.label)}</span>
      <span class="dbar"><i style="width:${(d.total / top * 100).toFixed(1)}%"></i></span>
      <span class="damt num nums">${ils(d.total)}</span></div>`).join('')
    || '<div class="hint">אין עדיין הוצאות</div>';
  $('dests').querySelectorAll('.dest').forEach(el => el.onclick = () => {
    const d = ds[+el.dataset.i];
    // the transactions table is always scoped to ONE month, so land on the month this
    // destination is biggest in — filtering the currently selected month could open an
    // empty table for a payee that simply did not charge that month
    let best = DATA.months[mi], bv = -1;
    for (const v of DATA.months) {
      const t = v.txns.reduce((s, r) =>
        s + (isSpend(r) && d.keys.includes(r[11]) ? r[4] : 0), 0);
      if (t > bv) { bv = t; best = v; }
    }
    openInsight({ view: 'txns', month: best.key, merchants: d.keys, label: d.label });
  });
}

/* ---------- trends: savings rate ---------- */
const RATE_H = 110;       // must match .rbars { height }; the zero line sits at half of it
function drawRate() {
  // income 0 is missing data, not a month without pay, and a partial month's rate is an
  // artifact of when its data starts — May's −8,590% would flatten every honest bar to
  // nothing. Both exclusions ride on flags the other charts already use.
  const ms = DATA.months.filter(v => v.income > 0 && (v.complete || v.isCurrent));
  if (!ms.length) {
    $('rate').innerHTML = '<div class="hint">אין עדיין חודש שלם עם הכנסות</div>'; return;
  }
  const pcts = ms.map(v => v.saved / v.income * 100);
  // capped so one freak month cannot flatten the rest. The % is printed on every bar, so
  // a clamped bar still states its own value.
  const lim = Math.min(Math.max(...pcts.map(Math.abs), 10), 150), HALF = RATE_H / 2;
  $('rate').innerHTML = ms.map((v, k) => {
    const p = pcts[k], up = p >= 0, i = DATA.months.indexOf(v);
    const h = Math.max(Math.min(Math.abs(p) / lim, 1) * HALF, 3);
    return `<div class="rcol" data-i="${i}" title="${escTxt(v.label)}${
        v.isCurrent ? ' (לפי הנתונים עד כה)' : ''} — ${up ? 'נשאר' : 'חריגה'} ${
        ils(Math.abs(v.saved))} מתוך ${ils(v.income)}">
      <div class="rbars"><div class="rbar ${up ? 'up' : 'dn'}${v.isCurrent ? ' prov' : ''}"
        style="height:${h.toFixed(1)}px"></div></div>
      <div class="rpct num ${up ? 'pos' : 'neg'}">${Math.round(p)}%</div>
      <div class="tlab ${i === mi ? 'sel' : ''}">${v.label.split(' ')[0].slice(0, 3)}</div></div>`;
  }).join('');
  $('rate').querySelectorAll('.rcol').forEach(c =>
    c.onclick = () => { mi = +c.dataset.i; render(); });
}

// Totals across a chosen set of months. Reads the per-month figures report.py already
// computed (m.income / m.spent) rather than re-deriving them from raw txns rows.
function renderSumReport() {
  // Default ("הכל") deliberately EXCLUDES future months: they hold only installments that
  // have not been charged yet, so counting them would inflate the expense total. Same rule
  // _destinations() follows in report.py.
  const chosen = sumMonths.length
    ? DATA.months.filter(m => sumMonths.includes(m.key))
    : DATA.months.filter(m => !m.isFuture);
  const income = chosen.reduce((s, m) => s + m.income, 0);
  const spent = chosen.reduce((s, m) => s + m.spent, 0);
  const net = income - spent;

  $('sum-income').textContent = ils(income);
  $('sum-spent').textContent = ils(spent);
  // ils() is only ever given positive numbers elsewhere, so carry the sign by hand
  $('sum-net').textContent = (net < 0 ? '−' : '+') + ils(Math.abs(net));
  $('sum-net').className = 'val ' + (net < 0 ? 'bad' : 'good');

  // a partial month must never be presented as a finished one
  $('sum-note').textContent = chosen.length
    ? `מבוסס על ${chosen.length} ${chosen.length === 1 ? 'חודש' : 'חודשים'}` +
      (chosen.some(m => m.isCurrent) ? ' · כולל את החודש הנוכחי, שטרם הסתיים' : '')
    : 'לא נבחרו חודשים';

  // newest first, like the month strip at the top of the page (RTL reads right to left)
  $('sumseg').innerHTML =
    `<button data-k="" class="${sumMonths.length ? '' : 'on'}">הכל</button>` +
    [...DATA.months].reverse().map(m =>
      `<button data-k="${escAttr(m.key)}" class="${sumMonths.includes(m.key) ? 'on' : ''}">${m.label}</button>`
    ).join('');
  $('sumseg').querySelectorAll('button').forEach(b => b.onclick = () => {
    const k = b.dataset.k;
    if (!k) sumMonths = [];                          // "הכל" clears the selection
    else sumMonths = sumMonths.includes(k) ? sumMonths.filter(x => x !== k) : [...sumMonths, k];
    renderSumReport();                               // re-renders these pills too
    saveUi();                                        // this control re-renders itself, not render()
  });
}

function renderTrends(m) {
  drawFlow();
  renderSumReport();

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
    return `<div class="catcard" data-cat="${escAttr(c.name)}">
      <div class="cc-head"><span>${escTxt(c.name)}</span>
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

  drawPace(); drawCards(); drawDests(); drawRate();
}

$('toast').onclick = () => { $('toast').className = 'toast'; };
restoreUi();
applyTheme();
applyView();
render();
