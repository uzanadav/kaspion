# How kaspion works — step by step

Plain-language guide: what each step does, which tool does it, and why it exists.
(Full design: `kaspion_spec.md` · full build plan: `kaspion_implementation_plan.md`)

## The big picture

```
get transactions → store them → clean & model them → categorize them → show them
     (scraper)      (DuckDB)         (dbt)              (Ollama AI)   (dashboard.html)
```

One command runs the whole chain: `python3 sync.py`. Everything happens on this computer — nothing is uploaded anywhere.

---

## Step 1 — Get transactions

| | |
|---|---|
| **Tool** | `israeli-bank-scrapers` (free Node library) — or the seed generator while testing |
| **Command** | `python3 sync.py --source scraper` (real) · `python3 kaspion/ingest/generate_seed.py` (fake) |
| **What it does** | Logs into the bank/credit-card site with your encrypted credentials and downloads recent transactions. The fake generator creates realistic sample data so you can build/test without touching real accounts. |
| **Why** | Automates what you'd do manually on the bank site every week. |

## Step 2 — Store them

| | |
|---|---|
| **Tool** | DuckDB — a free database that lives in one file: `data/finance.duckdb` |
| **Command** | (automatic, part of `sync.py`) |
| **What it does** | Saves every transaction once (duplicates are detected and skipped, so re-running is always safe). Also holds your corrections and budgets. |
| **Why** | One private file = easy to back up (`cp`), impossible to leak. Like a tiny personal Snowflake. |

## Step 3 — Clean & model

| | |
|---|---|
| **Tool** | dbt — turns raw data into clean, tested tables using SQL |
| **Command** | (automatic, part of `sync.py`) — manually: `cd dbt && DBT_PROFILES_DIR=. dbt build` |
| **What it does** | Three smart things: **(a)** finds transfers between your own accounts and removes them from "spending" (moving money isn't spending); **(b)** finds the monthly credit-card debit (חיוב) on the bank account and removes it too — otherwise every shekel on the card would be counted twice; **(c)** computes budget pacing: "given it's the 12th of the month, are we ahead or behind?" |
| **Why** | This is what makes the numbers on the dashboard *true*. Every rule is a tested model — 21 automatic checks run on every build. |

## Step 4 — Categorize

| | |
|---|---|
| **Tool** | Ollama — a free AI that runs on your computer, no internet needed |
| **Command** | (automatic, part of `sync.py`) |
| **What it does** | Looks at each NEW merchant name ("רמי לוי", "NETFLIX.COM") and assigns a category (groceries, subscriptions…). It only ever asks about merchants it hasn't seen — known ones are answered from memory instantly. |
| **Why** | Nobody wants to tag 200 transactions by hand every month. |

**Fixing a mistake** (this is the "merchant memory"):

```bash
python3 -m kaspion.cli recategorize "וולט" restaurants
```

The correction is saved forever — the AI is never asked about that merchant again, and your answer always wins.

**Everything is editable from the dashboard itself** (one version, same permissions for
everyone): change any transaction's category from a dropdown (saved forever, applies to all
of that merchant's transactions), add a manual expense with the ➕ form, hide a transaction
with 🗑. The edits are handled by a tiny local server:

```bash
python3 -m kaspion.serve     # keep running; the dashboard lives at http://127.0.0.1:8765
```

If the server isn't running the page still shows everything — edits just prompt you to
start it. Terminal equivalents exist too: `kaspion.cli add / remove / recategorize`.

## Step 5 — Show it

| | |
|---|---|
| **Tool** | `dashboard.html` — a single file the pipeline generates itself (`kaspion/report.py`) |
| **Command** | (automatic, part of `sync.py`) — just open `dashboard.html` in any browser |
| **What it does** | One Hebrew, phone-friendly page: are we over/under budget (one glance), per-category budget bars, biggest expenses, month-by-month history. Fully interactive — arrows or the trend chart switch months, clicking a category filters the transactions, plus live search. |
| **Why** | This is the part your wife uses. No server, no app, no login — double-click a file. Refresh the tab after every `sync.py`. |

---

## Daily / weekly routine

```bash
python3 sync.py --source scraper    # pull new transactions + rebuild everything + regenerate dashboard.html
```

Then refresh the `dashboard.html` tab in the browser. That's it. Fix any 🤖 miscategorizations you spot on the תנועות page with `recategorize`, and adjust budgets anytime:

```bash
python3 -m kaspion.cli set-budget groceries 3200
```

## One-time setup checklist

1. **Mac/Linux:** `bash scripts/setup.sh` · **Windows:** double-click `scripts\setup.bat` —
   either one does everything: checks Python, creates the venv, installs dependencies,
   generates sample data, and runs the full pipeline with step-by-step logs.
   (Windows day-to-day: `scripts\serve.bat` opens the dashboard; use `python` instead of
   `python3` in any command.)
2. *(optional — later)* Install [Ollama](https://ollama.com), `ollama pull llama3.2:3b` (~2GB — we tested 1b and it failed on Hebrew merchants, don't bother), then `python3 sync.py` — AI categorization. Best quality: `llama3.1:8b` via `KASPION_OLLAMA_MODEL=llama3.1:8b`. Until then run `python3 sync.py --provider none`: everything works, transactions just sit in "other" until you categorize them by hand (`recategorize`) or turn AI on. If Ollama isn't running, `sync.py` won't fail — it finishes the pipeline and prints how to categorize.
3. `python3 -m kaspion.ingest.crypto` — save bank credentials (encrypted)
4. Connect the real banks (Max, Isracard, Leumi) — full walkthrough in `docs/SCRAPER_SETUP.md`

The dashboard needs no setup at all — every `sync.py` run writes `dashboard.html`; open it in a browser.

Remember: `source .venv/bin/activate` in every new terminal before running commands.

## Where things live

| Path | What's inside |
|---|---|
| `data/finance.duckdb` | ALL your data — back this file up |
| `dashboard.html` | the dashboard — regenerated on every sync, safe to delete |
| `dbt/models/` | the SQL rules (transfers, card debits, budgets) |
| `kaspion/` | the Python glue (ingest, AI, dashboard generator, CLI) |
| `docs/` | the full spec + build plan |
