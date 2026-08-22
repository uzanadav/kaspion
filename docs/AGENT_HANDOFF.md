# kaspion — handoff for an AI coding agent

Read this before touching anything. It covers what the project is, what state it is
actually in (which differs from the original spec in important ways), the invariants
that must not be broken, and the traps that have already caused real bugs here.

`docs/kaspion_spec.md` and `docs/kaspion_implementation_plan.md` are the ORIGINAL design
documents and are now largely historical — they describe packages (`kaspion.agent`,
`kaspion.mcp`, `kaspion.semantic`) that were never built and have been deleted. **This
file wins wherever they disagree.**

---

## 1. What it is

A local-only household finance dashboard for Israeli banks/cards, built as a data
pipeline: statements → DuckDB → dbt models with tests → AI categorization → a single
self-contained Hebrew/RTL `dashboard.html`. Nothing leaves the machine. There is no
cloud, no accounts, no telemetry.

It now tracks **two people's** accounts (the owner's and his wife's) in one household
view. The wife is a non-technical user. The dashboard is the product; the stack is
secondary. When a change trades simplicity for sophistication, choose simplicity.

## 2. Running it

```bash
cd ~/Desktop/kaspion
bash scripts/setup.sh              # venv + deps + an EMPTY database
bash scripts/setup.sh --demo       # ...or with the 341-row synthetic dataset
source .venv/bin/activate
python3 -m kaspion.serve           # http://127.0.0.1:8765 (edit mode); opens the browser
python3 sync.py                    # scrape all institutions, rebuild, categorize, regenerate
```

Python **3.10–3.13** (the `<3.14` pin in `pyproject.toml` is load-bearing: dbt dies on
3.14 with a mashumaro `UnserializableField`, and it declares no upper bound of its own,
so nothing else catches it). Node arrives as a Python dependency via `nodejs-wheel` —
**do not tell anyone to install Node**. Categorization defaults to `none`: built-in
merchant rules only, no model. Ollama/Claude are opt-in via `--provider`.

`KASPION_DATA_DIR` relocates the database — it must be set **before** Python starts,
because `db.py`/`crypto.py`/`report.py` resolve their paths into module constants at
import time.

**End users never see any of the above.** They double-click `install` once, then
`kaspion` (see `INSTALL.md`); those scripts vendor uv into the app folder and bring
their own Python, Node and Chromium.

## 3. Data flow

```
statements ─┬─ scraper (Node: max, beinleumi, visaCal) ─┐
            ├─ .xlsx upload (Isracard)                  ├─▶ raw.transactions ─▶ dbt ─▶ dashboard.html
            └─ .xls upload (ONE ZERO)                   ─┘
```

- `raw.*` — written by ingest only.
- `state.*` — mutable app state (`merchant_overrides`, `budgets`, `ai_proposals`,
  `excluded_transactions`, `categories`). **dbt declares these as sources and only
  reads them.** dbt must NEVER materialize or truncate a `state.*` table; a
  `dbt build --full-refresh` losing an owner's correction is a critical bug.
- dbt models: `staging → intermediate → marts`, rebuilt freely.

`kaspion/db.py` `connect()` runs the DDL, so **it must be called before dbt** on a fresh
database (`sync.py` does this). A bare `dbt build` on a virgin DB fails on missing
`state.*` tables. `connect()` takes **no arguments** — it is always read-write, because
DuckDB's Python driver caches the database per process and errors if the same file is
opened with different configs.

## 4. Where each account comes from — and why

Five accounts, two people:

| Source | Whose | Method | Why |
|---|---|---|---|
| **Max** | owner | scraper (automatic) | works |
| **ONE ZERO** | owner | manual `.xls` upload | scraper needs 2FA enrollment; not built |
| **Isracard** | owner | manual `.xlsx` upload | **login blocked by reCAPTCHA** |
| **הבינלאומי / Beinleumi** | wife | scraper (automatic) | works |
| **Visa CAL** | wife | scraper (automatic) | works |

`beinleumi` reads the **checking account only** — FIBI issues no cards of its own, so
her card charges arrive via the separate `visaCal` scraper and her bank shows only the
monthly lump debit.

**Connecting a new scraper-backed institution is a dashboard action, not a terminal
one.** The **➕ הוספת חשבון** button in the sidebar (`app.js: renderAccountPicker` /
`renderAccountForm`) opens a `<dialog>` whose picker is a native grouped `<select>`
(`#acct-select`, three `<optgroup>`s: banks, cards, blocked) listing every institution in
`crypto.COMPANY_FIELDS` (17, copied verbatim from `israeli-bank-scrapers`' own
`SCRAPERS` export — see `tests/test_company_fields.py`), posts to `/api/add-account`,
which calls `scraper_loader.add_institution()`: **the 90-day scrape runs BEFORE anything
is written to disk**, so a bad login raises with nothing saved; only then are the
credentials merged into `credentials.json.enc` and the rows ingested. (It used to run a
short 7-day probe first and then scrape again — dropped because the full fetch already
raises on a bad login, so the probe bought nothing and cost a second browser login plus
a second failed-login attempt against banks that lock an account after three.) `isracard`/`amex`/`oneZero` sit in their own
disabled `<optgroup>` (`"blocked": "recaptcha"` for the first two, `"2fa"` for
oneZero — its login needs interactive OTP enrollment a one-shot form can't do), unpickable
client-side **and** rejected server-side if the client check is ever bypassed (`serve.py`
checks `inst.get("blocked")` before calling `add_institution`). All three stay on the
file-upload path. The `python3 -m kaspion.ingest.crypto` terminal prompt
(`docs/SCRAPER_SETUP.md`) still works and is the only path when the server isn't running.

**A `<select>` was chosen deliberately over a custom pill-grid picker (which shipped and
was then replaced) or a Plaid-style searchable logo grid.** The pill grid needed two
rounds of fixes — clicking a pill could land on the wrong element after the dialog
recomputed its centered position, because a box that resizes to its content recenters
every time the picked institution's field count changes the form's height. A native
`<select>` sidesteps that at the source: its closed state is one fixed-height row
regardless of which option the open (browser-native, out-of-flow) list highlights, so
picking an institution can no longer change the picker's on-page height. **A searchable
logo grid (the Plaid Link pattern) was considered and rejected** — it solves discovery
across thousands of institutions via brand-logo recognition, and this app has 17
institutions plus a standing design decision to ship **no bank logos**, so it would
undermine the single-file/no-external-request guarantee to fix a problem this app
doesn't have. The dialog's own `height:min(80vh,620px)` (not `max-height`/`fit-content`)
still matters — the credential *form* below the select still varies in height with field
count, and a resizing dialog box would still recenter regardless of what triggered the
resize; **do not switch it back to `max-height` or `fit-content`.** The "חשבונות מחוברים
כרגע" list (`#acct-connected`, own container, independent of the select) is
**load-bearing, not decorative**: a closed select hides connected-state entirely, so
that list is the only place it is visible — do not remove it as "redundant" with the
select's inline `✓`/`— N מחוברים` markers.

**A company can have more than one saved connection** — a bank/card both people in the
household use, each with their own login (two Max accounts, for example). Credentials
are keyed by CONNECTION id, not company id: the first connection to an institution keeps
the plain company id (`"max"`), so every credential file saved before this existed reads
back unchanged; a second login gets `"max:2"`, a third `"max:3"` (`company_of()` /
`next_connection_id()` in `crypto.py`). `DATA.connected` is a **list** of
`{id, company, label}`, not a set of company ids — the picker groups by `company` to
show a count badge (`· N`, only for N>1) and always opens a **blank** form on click,
never a pre-filled "edit" one; a bad login is fixed by removing it (✕ in the "חשבונות
מחוברים כרגע" list, `/api/remove-account`) and adding it again, not by editing in place.

**Do not try to make the Isracard scraper work.** It fails with `INVALID_PASSWORD`,
a misleading catch-all — the credentials are correct. The real cause is reCAPTCHA v3 on
`digital.isracard.co.il` refusing an automated browser (upstream issue #1140). Driving
the login form was tried and reached a filled, correct form before the backend refused.
**Defeating the CAPTCHA is out of bounds.** The XLSX import is the supported path.
`isracard` has been removed from the saved scraper credentials entirely so `sync.py`
no longer wastes a browser session failing on it.

`KASPION_SHOW_BROWSER=1` opens a visible browser for debugging a failing login.

## 5. Invariants — breaking these silently corrupts money figures

1. **Amount sign: negative = outflow, positive = inflow.** Normalize at the ingest
   boundary, never downstream. Card statements list charges as positive (negate them);
   ONE ZERO arrives already signed (don't).
2. **"Spend" is `amount < 0` AND `category_id != 'income'`.** A negative row filed under
   `income` (a PAYBOX reversal, `דמי כרטיס`, `* ריבית *`) is **not** an expense.
   `fct_budget_pacing` excludes `income` outright, so any client-side filter that only
   checks the sign totals ₪761–961/month more than the figure printed above it. In
   `app.js` this is the shared `isSpend(t)` helper — use it, never a bare `!t[10]`.
3. **Bank-side card debits must never count as spend.** A bank account contains the
   monthly חיוב for each card. `int_card_payments.sql` detects these and `fct_spend`
   drops them; the card-side charges are the real spend. Its regex must match **three**
   wordings: `חיוב <issuer>`, a bare issuer name (ONE ZERO omits "חיוב"), and a generic
   `כרטיסי אשראי` with no issuer at all (Beinleumi's `4825 - כרטיסי אשראי לי`).
   Guarded by `dbt/tests/assert_card_payments_excluded.sql`.
4. **`transaction_id` is the dedup key and must be stable across re-imports.** Changing
   the scheme re-inserts every existing row as a duplicate.
5. **Content identity — `(account_id, posted_date, amount, raw_description)` —
   always wins over any raw reference number a bank/scraper hands back, including a
   "trusted" one.** `kaspion.db.assign_natural_ids()` is the ONLY place transaction ids
   get minted or an incoming row gets dropped as already-known; both `scraper_loader.
   _ingest()` and `statements.upsert_rows()` route through it, and it runs its
   database-content check on **every** row, not only ones missing an id. This is
   deliberately stricter than "trust the bank's own reference": found and fixed 9 real
   duplicate groups across every institution — FIBI/Beinleumi reuses one reference
   number for every occurrence of a recurring standing order (would collapse 19
   transactions into 6 if trusted blindly, hence the "exactly one (date, amount) per
   reference" check that still runs first and mints a stable id when trustworthy);
   separately, a same-batch scrape has handed back the exact same real transaction
   twice under two *different* internal ids (a pending + settled pair, most likely),
   and an id scheme that depended on a row's position within a batch was not stable
   across separate sync runs — the same transaction could mint a second id later and
   duplicate. **The first version of this fix still had a bug**: it only ran the
   existing-content check for id-less rows, so a row that already carried a trusted id
   sailed through unchecked and re-duplicated on the very next sync — caught only by
   actually re-running a real sync after the "fix" and re-checking for duplicates, not
   by trusting a clean first result. Covered by `tests/test_db.py` and
   `tests/test_scraper_loader.py`. **Trade-off, stated explicitly**: two genuinely
   separate real transactions sharing the exact same day, amount, and description text
   will now collapse into one row. This is deliberate — that coincidence is rare, and
   for a finance app, silently duplicating real money is worse than silently
   under-counting a rare true coincidence.
6. **Owner corrections always win and are never re-asked.** `merchant_overrides` >
   `ai_proposals` > default.
7. **Installments belong to the month they are CHARGED**, not the original purchase
   date. All 12 payments carry the same purchase date in the statement; dating by it
   piles a year of payments onto one past month.
8. **`income == 0` means "not loaded", not "earned nothing"** — never plot it as zero.
   Same rule `insights.py` runs on.
9. **Credentials submitted from the dashboard follow the same rules as terminal-entered
   ones.** `/api/add-account` (`serve.py`) accepts a POST body only — never a query
   string, argv, or a log line (`Handler.log_message` is a permanent no-op). `company`
   is checked against `COMPANY_FIELDS` before anything else runs, and only the field
   names that institution's entry lists are ever read out of the payload — extra keys in
   the request are silently dropped, not stored. `add_institution()` **completes its
   scrape before calling `save_credentials()`** — a bad login raises with nothing on
   disk; do not reorder those two, whatever else changes — and merges into the existing file
   (`load_credentials() | {company: cfg}`) — it must never overwrite the other saved
   institutions. Every error response carries `error_type`/a message from the scraper's
   own `{error, message}` JSON, never the credential values that were sent.

## 6. Partial and future months

`_flag_months()` in `report.py` stamps every month; the charts and insights depend on it:

| flag | meaning |
|---|---|
| `isCurrent` | the running month — incomplete, spend only grows |
| `isFuture` | `key > current_key` — holds only future-dated installments/card charges |
| `firstDay` | day-of-month the data actually starts |
| `complete` | a whole month of data; **only the first month** can be truncated by when collection started, hence `(i > 0 or 0 < firstDay <= 3)` |

`DATA.curDay` is baked in from Python, not read from the browser clock: the page is a
static snapshot, so the cut must be one too — otherwise opening August's file in
September clips August's pace line at the 3rd.

Deliberately distinct from `insights._finished()` (MIN_TXNS ≥ 10), which answers a
different question. Do not merge them.

## 7. Traps that have already caused real bugs here

- **The sync button used to default to `--source seed`** and re-injected 341 rows of
  synthetic data into a live household database. It now defaults to `scraper` unless the
  DB has never held real data (`_default_source()`).
- **`SystemExit` inside `kaspion/cli.py` kills the server.** It is a `BaseException` and
  escapes `serve.py`'s `except Exception`. Command functions must raise `ValueError`;
  `__main__` converts it back for the terminal.
- **Merchant names are free text and contain quotes** (`ד"ר`, `בע"מ`). Any interpolation
  into an HTML attribute must go through `escAttr`, or the attribute terminates early.
  The same quotes broke **AI categorization**: the model was asked to echo merchant names
  back as JSON keys and produced invalid JSON on every sync. `providers.py` now sends a
  JSON-**schema**-constrained request returning an ordered array of category ids, so the
  model never reproduces the merchant string. A length mismatch discards the batch rather
  than risk pairing a category with the wrong merchant.
- **`escAttr` and `escTxt` are not interchangeable — a real bug shipped from confusing
  them.** `escAttr` (app.js) escapes only `&`/`"`, correct for *attribute values*
  (`title="..."`, `data-*="..."`). `escTxt` escapes `&`/`<`/`>`, needed for *text
  content*, or `<` in a string opens a real tag. The connected-accounts chip in the
  add-account dialog rendered `connLabel(c)` — which embeds the owner-typed free-text
  account label — as text content via `escAttr`, so a label containing `<img
  onerror=…>` would execute. Fixed to `escTxt` when the picker was rewritten
  (`renderAccountPicker`); low severity (local-only, self-inflicted), but any new
  interpolation of free text into innerHTML must pick the right one on purpose.
- **Reference numbers fragment merchant identity.** Four `חיוב צק/17672/00500XX/18` keys
  are one check series; three `דמי מנוי - .../founderpluss` keys are one subscription.
  `insights.merchant_label()` strips the reference from keys `_is_real_merchant()`
  rejects, collapsing each family. Real merchant names are returned byte-identical.
- **ONE ZERO stores Hebrew reversed** behind a U+202D override. Reversing the whole
  string fixes the words but flips digits too. Reverse Hebrew runs only, and skip rows
  that lack the override — they are already correct.
- **Statement section positions move between files.** Isracard exports have
  `עסקאות למועד חיוב`, `עסקאות לידיעה` and `עסקאות שטרם נקלטו` at different rows per
  month. Scan for header rows; never hardcode row numbers.
- **`dashboard.html` reloads after every edit.** UI state (view, month, category filter,
  card filter `accs`, merchant drill-down `pick`, flow, sort, search, theme) is persisted
  in `sessionStorage` — the month is stored by KEY, never index, because importing a
  statement adds months and shifts indices.
- **A failed `/api/*` call used to report into a hidden div.** `#a-msg` lives inside the
  collapsed "➕ הוספת הוצאה" toolbar, so a failed delete/recategorize/budget-edit looked
  like nothing happened. `api()` now also writes to a fixed `#toast`. Most common real
  cause: the page was opened as a plain file, or `kaspion.serve` isn't running — that
  case now opens the "כספיון לא פועל" dialog instead, whose button opens `kaspion://`,
  a scheme the launchers register (`Kaspion.app` on macOS, `HKCU\Software\Classes` on
  Windows) so a non-technical user never needs a terminal to bring the server up.
- **`fill="none"` receives no pointer events** in SVG — that is why the old `.tinc`
  tooltip never fired. Hit rects need `fill="transparent"` **and** `pointer-events:all`.
- **`serve.py` uses `ThreadingHTTPServer`, not `HTTPServer` — this was a real hang, not a
  hypothetical.** A plain `HTTPServer` blocks its single thread on ANY open connection
  until that client sends its next request; a browser tab left idle on the dashboard was
  enough, by itself, to freeze every other request server-wide (reproduced: a `curl` to
  `/api/remove-account` hung indefinitely with nothing else happening — `sample <pid>`
  showed the main thread parked in `recvfrom` on the idle tab's socket). Threading fixes
  that, but reopens a DIFFERENT hole — DuckDB allows only one process a read-write
  connection at a time, so two requests must never run dbt/report subprocesses
  concurrently. `_DB_LOCK` (a plain `threading.Lock`) wraps the whole mutating dispatch
  in `do_POST` to restore that serial guarantee; do not remove it when adding new
  DB-touching endpoints, and do not read the request body inside it (that part stays
  outside the lock so one slow client can't hold others hostage).
  `_scrape_company()` separately bounds every scraper subprocess with
  `SCRAPE_TIMEOUT = 240` so one hung login can't occupy the lock forever — do not remove
  it, and do not raise it casually.

### 7b. Packaging traps — every one of these shipped broken before it was caught

None of these are visible on the developer's Mac. All were found by actually running the
installer end to end, and all are enforced by `.github/workflows/windows-check.yml`.

- **`requires-python` must keep its `<3.14` upper bound.** dbt declares only `>=3.10` but
  dies on 3.14 (`UnserializableField: Field "schema" ... is not serializable`, out of
  mashumaro). `uv sync` installs the newest *allowed* Python, so without the ceiling every
  fresh install is broken while a developer on 3.11 sees nothing wrong. Raise it only
  after actually running dbt on the new version.
- **The scraper's Chromium lives in `.puppeteer/` inside the app folder**, not the shared
  `~/.cache/puppeteer`. `PUPPETEER_CACHE_DIR` is set by the installers **and** by
  `scraper_loader.PUPPETEER_CACHE` at run time — **these two must stay equal**, or the
  install downloads a browser the app then cannot find. The shared cache was abandoned
  because a half-finished download there (from any project) makes installs fail
  *permanently*: puppeteer sees the folder, finds no executable, and errors instead of
  re-fetching, so re-running fails identically. The installers clear and retry once,
  which is what makes "safe to re-run" true rather than aspirational.
- **`scripts/install.ps1` must keep its UTF-8 BOM.** Windows PowerShell 5.1 — what
  `powershell` launches, and what most users have — reads a BOM-less `.ps1` as ANSI. The
  Hebrew turned to mojibake and the script failed to *parse* ("The string is missing the
  terminator"). `setup.ps1` never hit this because it is English-only. The `.bat` files
  `chcp 65001` for the same reason; do **not** give a `.bat` a BOM, cmd mis-executes it.
- **Never hardcode `npm.cmd` / `npm.exe`.** `nodejs-wheel` ships npm/npx as console-script
  shims whose extension is pip/uv's business. Put `.venv/Scripts` (or `bin`) on PATH and
  call bare `npm`/`npx`.
- **Fetch the browser explicitly** (`npx puppeteer browsers install`) rather than trusting
  puppeteer's postinstall hook: npm 12 blocks install scripts by default, which would
  otherwise yield a "successful" install with no browser and every scrape failing later.
- **Anything that writes must go through `kaspion/paths.py`.** Writing into the source
  tree breaks an installed copy and is what would let a distributed zip carry someone
  else's data.

### 7c. Never clamp a bar to its target

The קטגוריות rows are a **bullet chart**: `BUDGET_MARK` (72%) is where the budget sits on
every track, so the target ticks form one column and an over-budget row runs visibly past
its own tick. The obvious-looking `Math.min(actual / budget * 100, 100)` shipped here for
months and made the chart useless: 347%-of-budget and 99%-of-budget drew **identical full
bars**, and a category with no budget drew a full bar too — the encoding said nothing
about precisely the rows that need attention. The overflow segment is deliberately
compressed (2× budget saturates the headroom) with the exact shekel variance in the
badge, so the cap costs emphasis and never information.

Status on those rows is never colour alone — every badge carries a glyph, words and the
number (`⚠ חריגה ₪2,220`). Keep it that way: colour-only state is unreadable to a
colour-blind household member and invisible in a screenshot printed in grey.

**Verify chart geometry by measuring, not by looking** — compare each rendered mark's
width against the value it encodes (this is how 18/18 rows were confirmed), because a
wrong bar and a right bar look equally plausible in a screenshot.

## 8. Layout

```
install.command/.bat    what an end user double-clicks once: vendors uv into the app
kaspion.command/.bat    folder, syncs Python+deps, npm-installs the scraper + Chromium,
                        then `kaspion init`. The second pair just starts the server.
kaspion/
  paths.py               45 — the per-user data dir (DB, key, credentials, dashboard).
                        PURE: returns paths, never creates them; callers mkdir.
  pipeline.py            44 — the ONLY place dbt is invoked; sets KASPION_DB_PATH +
                        DBT_PROFILES_DIR. `python3 -m kaspion.pipeline build` to run it
                        by hand. A bare `dbt` cannot work — see §10.
  report.py             265 — SQL → DATA dict, month flags, destinations, build_report()
  assets/app.html       271 — page skeleton with __CSS__ / __JS__ / __DATA__ slots
  assets/app.css        467 — design tokens (light+dark), all component styles
  assets/app.js        1215 — the whole client: state, 4 views, 7 charts, edit calls,
                        and renderEmptyState() for a brand-new install (§6)
  insights.py           285 — deterministic Hebrew observations (NO AI — see §9)
  db.py                 124 — connect() + DDL + assign_natural_ids() (the shared
                        dedup/id-assignment every ingest path routes through)
  serve.py              352 — local edit server; every /api/* rebuilds dbt + the report
  cli.py                250 — terminal equivalents, plus `init` (fresh empty install)
  ingest/               statements.py (dispatcher) · isracard_file · onezero_file
                        scraper_loader (ScrapeError, add_institution, _node_bin,
                        PUPPETEER_CACHE) · crypto (COMPANY_FIELDS, FIELD_LABELS)
                        · generate_seed
  ai/                   known_merchants.py rules → providers (none/ollama/claude)
dbt/models/             staging → intermediate → marts
tests/                  test_insights · test_report_charts · test_scraper_loader ·
                        test_db · test_crypto · test_paths · test_company_fields
                        (skipped without scraper/node_modules)
scripts/                setup.sh/.ps1 (developer) · install.ps1 (end user, MUST keep its
                        UTF-8 BOM) · build-release.sh (zip + personal-data leak check)
.github/workflows/      windows-check.yml — the dev machine is an arm64 Mac, so every
                        Windows path/encoding claim is only ever proven here
```

**The frontend lives in `kaspion/assets/`, not inside a Python string.** `build_report()`
reads the three files and substitutes: `__CSS__`, `__JS__`, `__GENERATED__`, then
`__DATA__` **last** — the payload is real bank text, and inserting it last makes it inert
by construction. Edit `app.js`/`app.css` directly; `node --check kaspion/assets/app.js`
works on the source. Output is still one self-contained `dashboard.html` that runs from
`file://`.

> Before this split, the CSS+JS were one 1,465-line non-raw Python string, and Python ate
> backslashes before JS saw them — that produced two page-killing `SyntaxError`s, one of
> them inside the comment warning about it. The split removed the bug class entirely.
> **Do not move the frontend back into a Python string.**

## 9. Insights are computed, never generated

`kaspion/insights.py` is pure functions — no DB, no network, no imports from the rest of
kaspion. A local LLM was evaluated for this job and produced confident, wrong numbers
(dropped digits, invented currency). **Never route insight text through a model.**
Two rules run through it: the current month is incomplete (so "already more than" is
safe but "less than" is not yet knowable), and `income == 0` means not-loaded.

## 10. Working rules

- **Always rebuild and verify after a change:**
  ```bash
  python3 -m pytest tests/ -q                 # 51 tests
  python3 -m ruff check .                     # must be clean; config is pinned in pyproject
  python3 -m kaspion.pipeline build -q        # 27/27 (7 models + 2 seeds + 18 data tests)
  python3 -c "from kaspion.report import build_report; build_report()"
  node --check kaspion/assets/app.js
  ```
  **Never run a bare `dbt`.** `dbt/profiles.yml` reads the database location from
  `KASPION_DB_PATH`; only `kaspion.pipeline` sets it (from `kaspion/paths.py`). A bare
  `dbt` fails to parse the profile rather than silently building into the wrong database.
- **Verify by measuring, not by eyeballing.** Chart geometry, colours and totals have all
  been wrong here in ways a screenshot did not reveal. Query the DB; read computed
  styles; reconcile chart totals against `m.spent`.
- **A test that cannot fail is worse than no test.** `assert_card_debit_matches_statement`
  was deleted for this reason: it joined on seed account ids (`max-1234`) that no live row
  has, so it always passed while claiming to guard card double-counting. Before trusting a
  new test, break the thing it guards and confirm it goes red.
- **Never invent financial figures.** If data is missing, say so in the UI rather than
  rendering a confident zero.
- Charts must read `PALETTE()` / `issuerOf()` **at render time**, never cache the colour —
  a baked-in value freezes on the old palette after a theme toggle.
- The AI categorizer drops merchants it is unsure about; re-running picks them up. That is
  expected. Its output is a *proposal* — spot-check it, `llama3.2:3b` is often wrong on
  unfamiliar Hebrew merchants.
- Credentials live in `data/credentials.json.enc` + `data/.kaspion_key` (AES-256-GCM,
  0600, gitignored). `.claude/settings.json` denies reading them. Never print, log, or
  echo credential values; entering a real login — whether the terminal
  `python3 -m kaspion.ingest.crypto` prompt or the dashboard's ➕ הוספת חשבון dialog — is
  the owner's job, not the agent's. See invariant 9 (§5) for what the add-account
  endpoint itself must guarantee.
