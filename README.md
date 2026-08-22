# kaspion 💰 כספיון

**A local-only, privacy-first household finance dashboard for Israeli banks** — built as a
data-engineering pipeline: DuckDB warehouse, dbt models with tests, AI categorization with
merchant memory, and a Hebrew, family-friendly dashboard generated as a single HTML file.

Your financial data **never leaves your computer**. No cloud, no accounts, no telemetry.

> **Just want to use it?** Download the zip from Releases, unzip, and double-click
> `install` once — then `kaspion`. No Python, no Node, no terminal, no admin rights.
> Full Hebrew walkthrough: **[INSTALL.md](INSTALL.md)**.
> The rest of this file is for developing kaspion, not running it.

<div dir="rtl">

## מה זה כספיון?

לוח מחוונים לניהול תקציב המשפחה, שרץ **רק על המחשב שלכם**. הוא מושך את התנועות
מהבנקים ומכרטיסי האשראי, מסדר אותן לקטגוריות, ומראה בעברית לאן הכסף הולך: הכנסות
מול הוצאות, תקציב מול ביצוע, מגמות לאורך זמן ותובנות מחושבות.

הנתונים לא נשלחים לשום מקום. אין ענן, אין חשבון משתמש, אין מעקב — המחשב מדבר רק עם
הבנק עצמו. בסיס הנתונים נשמר בתיקייה האישית שלכם, מחוץ לתיקיית התוכנה, כך שכל מחשב
מתחיל נקי ושום מידע לא עובר בין מחשבים.

**להתקנה ולשימוש — ראו [INSTALL.md](INSTALL.md).** המשך הקובץ הזה מיועד למפתחים.

</div>

## What it does

Collects your bank & credit-card transactions — automatically via
[israeli-bank-scrapers](https://github.com/eshaham/israeli-bank-scrapers), or by dropping the
monthly statement file onto the dashboard — models them with dbt on DuckDB, detecting
inter-account transfers and the monthly card debit (חיוב) **so a card statement is never
counted twice**, categorizes merchants automatically (built-in Israeli merchant rules by default —
no model, no download; local AI via Ollama or Claude is opt-in for the rest — and your
manual corrections always win and are remembered forever), and renders an interactive Hebrew dashboard: income vs. spending, budgets with
monthly pacing, per-category trends, savings tracking, and inline editing (recategorize, add
expenses, hide transactions, set budgets, add categories) — all from the browser.

Multiple people's accounts merge into one household view, and any chart or table can be
filtered down to a single card.

```
bank / credit card ─┬─ scraper (Node)      ─┐
                    └─ statement upload     ├─▶ raw.transactions ─▶ dbt (staging → transfer &
                       (.xlsx / .xls)      ─┘      (DuckDB)          card-debit detection →
                                                              │      marts + budget pacing)
                        your overrides > Israeli merchant rules > optional AI (opt-in)
                                                              │
                                                       dashboard.html
                                              (Hebrew · RTL · interactive · one file)
```

### How each account gets in

Any institution [israeli-bank-scrapers](https://github.com/eshaham/israeli-bank-scrapers)
supports works out of the box — add it from the dashboard's **➕ הוספת חשבון** button (or
the terminal: `python3 -m kaspion.ingest.crypto`). The setup currently running in
production, as an example of the two paths:

| Institution | Method | Why |
|---|---|---|
| **Max** · **הבינלאומי** · **Visa CAL** | scraper, fully automatic (cron-able) | works |
| **Isracard** | upload the monthly `.xlsx` from their site | their login is behind reCAPTCHA — see `docs/AGENT_HANDOFF.md` |
| **ONE ZERO** | upload the `.xls` export from the app | needs one-time 2FA enrollment, not built yet |

Uploading is on the **תנועות** page: pick one or more files and press טעינה. The file's bank
is detected from its contents, re-uploading the same file never creates duplicates, and card
debits inside a bank statement are automatically excluded from spending.

Note that a bank scraper reads the **checking account only**. If that bank's card is issued
by someone else (הבינלאומי's cards come from CAL), add the card issuer as its own source to
get itemized charges — otherwise the card appears as a single monthly lump debit.

## Privacy: what's in this repo vs. what stays on your machine

Your data never lives in this folder at all — it goes in the OS's per-user data
directory (`kaspion/paths.py`), so nothing personal can ride along in a copy or a zip
of the repo:

| macOS | `~/Library/Application Support/kaspion/` |
|---|---|
| **Windows** | `%LOCALAPPDATA%\kaspion\` |
| **Linux** | `~/.local/share/kaspion/` |

| Committed (safe, synthetic) | Your machine only, outside the repo |
|---|---|
| All code, dbt models & tests | `finance.duckdb` — ALL your financial data |
| `dbt/seeds/sample_transactions.csv` — **generated fake data** | `.kaspion_key` + `credentials.json.enc` — encrypted bank logins |
| `evals/ground_truth.csv` — labels for the fake data | `dashboard.html` — generated, contains your real transactions |
| Docs, category list, merchant rules | (`.venv/`, dbt artifacts and logs stay gitignored in the repo) |

`.kaspion_key` sits in that same folder, beside the credentials it decrypts: the
encryption protects a stray copy of `credentials.json.enc` (a backup, a synced folder),
not someone who already has your user account. `finance.duckdb` is not encrypted at all
— it is a plain file, safe to back up, not safe to hand around.

The only network calls the tool can ever make: your bank (scraping, TLS) and — only if you
explicitly opt in to the paid provider — the Anthropic API (merchant *names* only, never
amounts or accounts). Categorization defaults to offline merchant rules with **no AI at
all**. See `SECURITY.md`.

## Installing (end users)

Download the zip, unzip, double-click `install` once, then `kaspion`. That is the whole
flow — see **[INSTALL.md](INSTALL.md)** (Hebrew) for the walkthrough, including the
one-time Gatekeeper/SmartScreen prompt that unsigned apps trigger.

`install` vendors [uv](https://docs.astral.sh/uv/) into the app folder, which brings its
own Python; Node arrives as a Python dependency (`nodejs-wheel`); the scraper's Chromium
lands in the app folder too. Nothing is installed system-wide, no admin rights are needed,
and uninstalling is deleting the app folder and the data folder.

## Developing

Requires Python 3.10–3.13 (dbt breaks on 3.14 — see the pin in `pyproject.toml`).

```bash
git clone <this-repo> && cd kaspion
bash scripts/setup.sh          # venv + deps + an EMPTY database
bash scripts/setup.sh --demo   # ...or with 341 rows of synthetic data to click around
python3 -m kaspion.serve       # dashboard at http://127.0.0.1:8765, opens your browser
```

**Windows:** `scripts\setup.bat` (add `-Demo` for sample data), then `scripts\serve.bat`.
Use `python` instead of `python3` and `.venv\Scripts\activate` to activate.

Point `KASPION_DATA_DIR` at a scratch directory to work against a throwaway database —
it must be set *before* Python starts, since the paths resolve at import time.

### Using it with real data

1. **Connect a bank or card:** press **➕ הוספת חשבון** in the sidebar — pick the
   institution, fill in the fields, press the button. The login is verified before
   anything is saved, then 90 days of history is pulled and the page reloads.
   Isracard/Amex (reCAPTCHA) and ONE ZERO (2FA enrollment) are greyed out with a 🔒 —
   upload their statement from the **תנועות** page instead. Terminal equivalent:
   `python3 -m kaspion.ingest.crypto`. Full walkthrough: `docs/SCRAPER_SETUP.md`.
2. **Scraper dependencies (one time):** `cd scraper && npm install && cd ..`
   (the installer does this for end users).
3. **Pull it:** `python3 sync.py` — defaults to the scraper, and to rules-only
   categorization. Add `--provider ollama` or `--provider claude` to opt in to AI.
4. **Set your budgets:** on the קטגוריות page — every target is an editable field.

Daily use: click **🔄 סנכרון** in the sidebar (or `python3 sync.py`, or cron). Fix any
miscategorized merchant from the dropdown — each fix is permanent and never re-asked.

## Key design decisions

- **DuckDB, not a cloud warehouse** — one household, one file, private, backup = `cp`.
- **No Airflow** — one `sync.py` run per day doesn't need an orchestrator; cron is honest.
- **Transfer & card-debit exclusion as *tested* dbt models** — incl. a net-to-zero
  singular test — not procedural helpers. The dashboard numbers are trustworthy because
  every build runs the full test suite.
- **State vs. dbt separation** — your corrections, budgets, and hidden transactions live in
  `state.*` tables that dbt only reads; `dbt build --full-refresh` can never wipe them.
- **Rules → AI → memory categorization** — ~70 known Israeli merchants are categorized
  deterministically for free; the AI only sees the tail; your corrections override
  everything and are never re-asked.
- **Insights are computed, never generated** — the Hebrew observations on the overview page
  come from plain SQL and Python, not a model. A local LLM was evaluated for the job and
  produced confident, wrong numbers; a finance dashboard can't ship that.
- **The UI is a generated static file** — no frontend framework, no build step, no server
  required to *view* it. A tiny stdlib server (`kaspion.serve`) adds editing.

## Repo map

| Path | What |
|---|---|
| `install.command` / `install.bat` | what an end user double-clicks, once |
| `kaspion.command` / `kaspion.bat` | what they double-click every time after |
| `uninstall.command` / `uninstall.bat` | removes the URL handler and, only on an explicit `DELETE`, the data folder |
| `sync.py` | the one entrypoint: ingest → dbt → categorize → dashboard |
| `kaspion/paths.py` | where the database, key, credentials and dashboard live — **outside** this folder, per user |
| `kaspion/pipeline.py` | the only place dbt is invoked (sets `KASPION_DB_PATH`); run it directly with `python3 -m kaspion.pipeline build` |
| `kaspion/report.py` | SQL → data, then renders `dashboard.html` from the assets below |
| `kaspion/assets/` | the actual frontend: `app.html` + `app.css` + `app.js`, inlined at build time into one self-contained file |
| `kaspion/insights.py` | deterministic Hebrew observations (pure functions, no DB, no AI) |
| `kaspion/ingest/` | seed generator, scraper wrapper, statement importers, credential encryption |
| `kaspion/ingest/statements.py` | upload dispatcher — detects the bank from the file itself |
| `kaspion/ai/` | rules layer + providers: none (default) / ollama / claude |
| `kaspion/serve.py` | local edit server (add/hide/recategorize/budgets/categories/upload/sync) |
| `kaspion/cli.py` | terminal equivalents, plus `init` for a fresh install |
| `dbt/` | staging → intermediate → marts, all tests |
| `tests/` | pytest — insights, chart inputs, transaction-id assignment, paths |
| `evals/` | hand-labeled ground truth for categorization accuracy |
| `scraper/` | Node wrapper around israeli-bank-scrapers |
| `scripts/build-release.sh` | builds the download zip and refuses to ship if it contains personal data |
| `.github/workflows/` | Windows CI — the dev machine is a Mac, so Windows paths/encoding are only ever proven here |
| `INSTALL.md` | the Hebrew end-user guide |
| `docs/AGENT_HANDOFF.md` | **read first if you're an AI agent** — state, invariants, known traps |
| `docs/` | how it works, scraper setup, full spec & build plan |

### Working on it

```bash
python3 -m pytest tests/ -q                 # 57 tests
python3 -m ruff check .                     # config pinned in pyproject.toml
python3 -m kaspion.pipeline build -q        # 27/27 — every build runs the data tests
python3 -c "from kaspion.report import build_report; build_report()"
node --check kaspion/assets/app.js          # the frontend is a real file, not a string
```

Edit `kaspion/assets/app.js` and `app.css` directly — they're ordinary files with syntax
highlighting and tooling, inlined into `dashboard.html` only at build time.

## Cutting a release

```bash
bash scripts/build-release.sh    # git archive → kaspion-<version>.zip
```

It builds from `HEAD` via `git archive`, so anything gitignored — the database,
credentials, key, generated dashboard, `.venv`, `node_modules`, the downloaded browser —
is excluded *by construction* rather than by remembering. `.gitattributes` additionally
drops the synthetic demo dataset. The script then greps the finished archive for personal
data and **deletes it and exits non-zero** if it finds any, so a bad zip can't be
published by accident. Then:

```bash
gh release create vX.Y.Z kaspion-*.zip --notes-file INSTALL.md
```

## Before pushing your fork (privacy self-check)

```bash
git status --ignored | grep -E 'data/|dashboard.html'   # should appear as IGNORED
git ls-files | grep -iE 'duckdb|dashboard\.html|credential|\.enc|^data/.'  # should print NOTHING
grep -rn "$(whoami)" $(git ls-files) 2>/dev/null        # your username shouldn't appear
```

## Disclaimers

Bank scraping may violate your institution's Terms of Service — use with your own accounts,
on your own machine, at your own risk. This is a personal tool, not financial software;
verify important numbers against your bank statements.
