# How kaspion works — step by step

Plain-language guide: what each step does, which tool does it, and why it exists.
(Full design: `kaspion_spec.md` · full build plan: `kaspion_implementation_plan.md`)

## The big picture

```
get transactions → store them → clean & model them → categorize them → show them
     (scraper)      (DuckDB)         (dbt)          (merchant rules)  (dashboard.html)
```

One command runs the whole chain: `python3 sync.py`. Everything happens on this computer — nothing is uploaded anywhere.

---

## Step 1 — Get transactions

| | |
|---|---|
| **Tool** | `israeli-bank-scrapers` (free Node library) — or the seed generator while testing |
| **Command** | `python3 sync.py` (real — the default) · `python3 sync.py --source seed` (synthetic) |
| **What it does** | Logs into the bank/credit-card site with your encrypted credentials and downloads recent transactions. The fake generator creates realistic sample data so you can build/test without touching real accounts. |
| **Why** | Automates what you'd do manually on the bank site every week. |

## Step 2 — Store them

| | |
|---|---|
| **Tool** | DuckDB — a free database that lives in one file: `finance.duckdb`, in your per-user data folder (see the table at the bottom) |
| **Command** | (automatic, part of `sync.py`) |
| **What it does** | Saves every transaction once (duplicates are detected and skipped, so re-running is always safe). Also holds your corrections and budgets. |
| **Why** | One private file = easy to back up (`cp`), impossible to leak. Like a tiny personal Snowflake. |

## Step 3 — Clean & model

| | |
|---|---|
| **Tool** | dbt — turns raw data into clean, tested tables using SQL |
| **Command** | (automatic, part of `sync.py`) — manually: `python3 -m kaspion.pipeline build` |
| **What it does** | Three smart things: **(a)** finds transfers between your own accounts and removes them from "spending" (moving money isn't spending); **(b)** finds the monthly credit-card debit (חיוב) on the bank account and removes it too — otherwise every shekel on the card would be counted twice; **(c)** computes budget pacing: "given it's the 12th of the month, are we ahead or behind?" |
| **Why** | This is what makes the numbers on the dashboard *true*. Every rule is a tested model — 21 automatic checks run on every build. |

## Step 4 — Categorize

| | |
|---|---|
| **Tool** | Built-in Israeli merchant rules. **No AI by default** — nothing to install, works on any machine. Ollama or Claude are opt-in via `--provider`. |
| **Command** | (automatic, part of `sync.py`) |
| **What it does** | Looks at each NEW merchant name ("רמי לוי", "NETFLIX.COM") and assigns a category (groceries, subscriptions…). ~70 common Israeli merchants are known outright; anything else lands in "other" until you fix it once from the dashboard dropdown. It only ever asks about merchants it hasn't seen — known ones are answered from memory instantly. |
| **Why** | Nobody wants to tag 200 transactions by hand every month — and nobody should need a 2GB model on a laptop to avoid it. |

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
| **Command** | (automatic, part of `sync.py`) — `python3 -m kaspion.serve` opens it for you |
| **What it does** | One Hebrew, phone-friendly page: are we over/under budget (one glance), per-category budget bars, biggest expenses, month-by-month history. Fully interactive — arrows or the trend chart switch months, clicking a category filters the transactions, plus live search. |
| **Why** | This is the part your wife uses. No server, no app, no login — double-click a file. Refresh the tab after every `sync.py`. |

---

## Daily / weekly routine

```bash
python3 sync.py    # pull new transactions + rebuild everything + regenerate the dashboard
```

Then refresh the dashboard tab in the browser. That's it. Fix any 🤖 miscategorizations you spot on the תנועות page with `recategorize`, and adjust budgets anytime:

```bash
python3 -m kaspion.cli set-budget groceries 3200
```

## One-time setup checklist

**Not a developer?** Ignore this list — double-click `install` once, then `kaspion`.
See [INSTALL.md](../INSTALL.md).

1. **Mac/Linux:** `bash scripts/setup.sh` · **Windows:** double-click `scripts\setup.bat` —
   either one checks Python, creates the venv, installs dependencies and prepares an
   **empty** database. Add `--demo` (or `-Demo` on Windows) to load the synthetic dataset
   instead. (Windows day-to-day: `scripts\serve.bat`; use `python` instead of `python3`.)
2. Connect a bank from the dashboard's **➕ הוספת חשבון**, or from the terminal with
   `python3 -m kaspion.ingest.crypto` — full walkthrough in `docs/SCRAPER_SETUP.md`.
3. `python3 sync.py` — pulls the real data. Categorization is rules-only by default.
4. *(optional)* AI categorization for the merchants the rules miss: install
   [Ollama](https://ollama.com), `ollama pull llama3.2:3b` (~2GB — 1b was tested and
   failed on Hebrew merchants, don't bother), then `python3 sync.py --provider ollama`.
   Best quality: `KASPION_OLLAMA_MODEL=llama3.1:8b`. If Ollama isn't running, `sync.py`
   won't fail — it finishes the pipeline and prints how to categorize.

The dashboard needs no setup — `python3 -m kaspion.serve` regenerates it and opens your
browser. Remember: `source .venv/bin/activate` in every new terminal.

## Where things live

Your data lives **outside** the app folder, in the standard per-user location for your
system — so uninstalling is deleting the app folder, and your data is a separate,
easy-to-back-up folder:

| System | Your data folder |
|---|---|
| macOS | `~/Library/Application Support/kaspion/` |
| Windows | `%LOCALAPPDATA%\kaspion\` |
| Linux | `~/.local/share/kaspion/` |

| Path | What's inside |
|---|---|
| `finance.duckdb` (data folder) | ALL your data — back this file up |
| `dashboard.html` (data folder) | the dashboard — regenerated on every sync, safe to delete |
| `dbt/models/` (app folder) | the SQL rules (transfers, card debits, budgets) |
| `kaspion/` (app folder) | the Python glue (ingest, AI, dashboard generator, CLI) |
| `docs/` | the full spec + build plan |
