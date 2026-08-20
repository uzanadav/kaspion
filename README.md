# kaspion 💰

**A local-only, privacy-first household finance dashboard for Israeli banks** — built as a
data-engineering pipeline: DuckDB warehouse, dbt models with tests, AI categorization with
merchant memory, and a Hebrew, family-friendly dashboard generated as a single HTML file.

Your financial data **never leaves your computer**. No cloud, no accounts, no telemetry.

## What it does

Collects your bank & credit-card transactions — automatically via
[israeli-bank-scrapers](https://github.com/eshaham/israeli-bank-scrapers), or by dropping the
monthly statement file onto the dashboard — models them with dbt on DuckDB, detecting
inter-account transfers and the monthly card debit (חיוב) **so a card statement is never
counted twice**, categorizes merchants automatically (built-in Israeli merchant rules first,
local AI via Ollama for the rest, your manual corrections always win and are remembered
forever), and renders an interactive Hebrew dashboard: income vs. spending, budgets with
monthly pacing, per-category trends, savings tracking, and inline editing (recategorize, add
expenses, hide transactions, set budgets, add categories) — all from the browser.

Multiple people's accounts merge into one household view, and any chart or table can be
filtered down to a single card.

```
bank / credit card ─┬─ scraper (Node)      ─┐
                    └─ statement upload     ├─▶ raw.transactions ─▶ dbt (staging → transfer &
                       (.xlsx / .xls)      ─┘      (DuckDB)          card-debit detection →
                                                              │      marts + budget pacing)
                              your overrides > Israeli merchant rules > local AI (Ollama)
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

The only network calls the tool can ever make: your bank (scraping, TLS) and — only if you
explicitly choose the paid provider — the Anthropic API (merchant *names* only, never
amounts or accounts). The default AI (Ollama) is fully offline. See `SECURITY.md`.

## Quickstart (fake data, 2 minutes)

Requires Python 3.10+. Node.js 18+ is needed only for the real bank scraper.
No AI model required — a low-RAM/low-storage PC runs everything.

**Mac / Linux:**

```bash
git clone <this-repo> && cd kaspion
bash scripts/setup.sh        # venv + deps + sample data + full pipeline, with logs
python3 -m kaspion.serve     # dashboard at http://127.0.0.1:8765
```

**Windows:** double-click `scripts\setup.bat` (one-time), then `scripts\serve.bat`
to open the dashboard. In terminal commands below, use `python` instead of `python3`
and `.venv\Scripts\activate` instead of `source .venv/bin/activate`.

You now have a working dashboard with 6 months of realistic fake data — explore it,
click things, nothing is real.

## Running it with YOUR data

1. **AI categorization (optional, free):** install [Ollama](https://ollama.com), then
   `ollama pull llama3.2:3b` (~2GB disk, ~4GB RAM while running). **Skip this entirely on a
   weak machine** — run with `--provider none`: built-in Israeli merchant rules categorize
   the common stuff for free, and the rest is a one-time dropdown fix in the dashboard.
2. **Connect a bank or card:** run `python3 -m kaspion.serve` and press
   **➕ הוספת חשבון** in the sidebar — pick the institution, fill in the fields it asks
   for, press the button. The login is verified before anything is saved, then 90 days
   of history is pulled and the page reloads with real data. Isracard/Amex (reCAPTCHA)
   and ONE ZERO (needs 2FA enrollment) show up greyed out with a 🔒 rather than as a
   working login — upload their statement from the **תנועות** page instead. Terminal
   equivalent: `python3 -m
   kaspion.ingest.crypto`. Full walkthrough incl. verification steps:
   `docs/SCRAPER_SETUP.md`.
3. **Scraper (one time):** `cd scraper && npm install && cd ..`
4. **Wipe the fake data, pull the real thing:**
   ```bash
   python3 -m kaspion.cli reset-sample-data
   python3 sync.py --source scraper
   ```
5. **Set your budgets:** on the קטגוריות page — every target is an editable field.

Daily use after that: click **🔄 סנכרון** in the dashboard sidebar (or `python3 sync.py
--source scraper`, or a cron job). Fix any miscategorized merchant from the dropdown —
each fix is permanent.

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
| `sync.py` | the one entrypoint: ingest → dbt → categorize → dashboard |
| `kaspion/report.py` | SQL → data, then renders `dashboard.html` from the assets below |
| `kaspion/assets/` | the actual frontend: `app.html` + `app.css` + `app.js`, inlined at build time into one self-contained file |
| `kaspion/insights.py` | deterministic Hebrew observations (pure functions, no DB, no AI) |
| `kaspion/ingest/` | seed generator, scraper wrapper, statement importers, credential encryption |
| `kaspion/ingest/statements.py` | upload dispatcher — detects the bank from the file itself |
| `kaspion/ai/` | rules layer + providers: ollama (default) / claude / none |
| `kaspion/serve.py` | local edit server (add/hide/recategorize/budgets/categories/upload/sync) |
| `kaspion/cli.py` | terminal equivalents |
| `dbt/` | staging → intermediate → marts, all tests |
| `tests/` | pytest — insights, chart inputs, transaction-id assignment |
| `evals/` | hand-labeled ground truth for categorization accuracy |
| `scraper/` | Node wrapper around israeli-bank-scrapers |
| `docs/AGENT_HANDOFF.md` | **read first if you're an AI agent** — state, invariants, known traps |
| `docs/` | how it works, scraper setup, full spec & build plan |

### Working on it

```bash
python3 -m pytest tests/ -q                 # 44 tests
python3 -m ruff check .                     # config pinned in pyproject.toml
python3 -m kaspion.pipeline build -q        # 20/20 — every build runs the data tests
python3 -c "from kaspion.report import build_report; build_report()"
node --check kaspion/assets/app.js          # the frontend is a real file, not a string
```

Edit `kaspion/assets/app.js` and `app.css` directly — they're ordinary files with syntax
highlighting and tooling, inlined into `dashboard.html` only at build time.

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
