# kaspion — handoff for an AI coding agent

Read this before touching anything. It covers what the project is, what state it is
actually in (which differs from the original spec in important ways), the invariants
that must not be broken, and the traps that have already caused real bugs here.

`docs/kaspion_spec.md` and `docs/kaspion_implementation_plan.md` are the ORIGINAL design
documents. Several decisions in them have since been superseded — this file wins where
they disagree.

---

## 1. What it is

A local-only household finance dashboard for Israeli banks/cards, built as a data
pipeline: statements → DuckDB → dbt models with tests → AI categorization → a single
self-contained Hebrew/RTL `dashboard.html`. Nothing leaves the machine. There is no
cloud, no accounts, no telemetry.

The owner's wife is a non-technical user. The dashboard is the product; the stack is
secondary. When a change trades simplicity for sophistication, choose simplicity.

## 2. Running it

```bash
cd ~/Desktop/kaspion
bash scripts/setup.sh              # venv + deps + sample data + full pipeline
source .venv/bin/activate
python3 -m kaspion.serve           # http://127.0.0.1:8765  (edit mode)
python3 sync.py --source scraper   # pull Max, rebuild, categorize, regenerate
```

Python 3.11 in `.venv`. Node 26 for the scraper. Ollama (`llama3.2:3b`) is optional —
`--provider none` works and built-in merchant rules still run.

## 3. Data flow

```
statements ─┬─ scraper (Node, Max only)      ─┐
            ├─ .xlsx upload (Isracard)        ├─▶ raw.transactions ─▶ dbt ─▶ dashboard.html
            └─ .xls upload (ONE ZERO, bank)  ─┘
```

- `raw.*` — written by ingest only.
- `state.*` — mutable app state (`merchant_overrides`, `budgets`, `ai_proposals`,
  `excluded_transactions`, `categories`). **dbt declares these as sources and only
  reads them.** dbt must NEVER materialize or truncate a `state.*` table; a
  `dbt build --full-refresh` losing an owner's correction is a critical bug.
- dbt models: `staging → intermediate → marts`, rebuilt freely.

`kaspion/db.py` `connect()` runs the DDL, so **it must be called before dbt** on a fresh
database (`sync.py` does this). A bare `dbt build` on a virgin DB fails on missing
`state.*` tables.

## 4. Where each account comes from — and why

| Source | Method | Why |
|---|---|---|
| **Max** | `israeli-bank-scrapers` (automatic) | works; runs in cron |
| **Isracard** | manual `.xlsx` upload | **login is blocked by reCAPTCHA** |
| **ONE ZERO** | manual `.xls` upload | scraper needs 2FA enrollment; not built yet |

**Do not try to make the Isracard scraper work.** It fails with `INVALID_PASSWORD`,
which is a misleading catch-all — the credentials are correct. The real cause is
reCAPTCHA v3 on `digital.isracard.co.il` scoring an automated browser and refusing it
(upstream issue #1140, open since Jul 2026; the WAF PRs #1064/#1082 have been unmerged
since March). Driving the login form was tried and got all the way to a filled, correct
form before the backend refused. **Defeating the CAPTCHA is out of bounds.** The XLSX
import is the supported path and is what the upstream maintainers are moving to.

`KASPION_SHOW_BROWSER=1` opens a visible browser for debugging a failing login.

## 5. Invariants — breaking these silently corrupts money figures

1. **Amount sign: negative = outflow, positive = inflow.** Normalize at the ingest
   boundary, never downstream. Card statements list charges as positive (negate them);
   ONE ZERO arrives already signed (don't).
2. **Bank-side card debits must never count as spend.** A bank account contains the
   monthly חיוב for each card (e.g. ONE ZERO shows `ישראכרט-דיירקט` for the exact
   amount of that month's Isracard statement). `int_card_payments.sql` detects these
   and `fct_spend` drops them; the card-side charges are the real spend. Its regex must
   match two wordings: `חיוב <issuer>` AND a bare issuer name (ONE ZERO omits "חיוב").
3. **`transaction_id` is the dedup key and must be stable across re-imports.** Changing
   the scheme re-inserts every existing row as a duplicate. If you must add entropy,
   add it ONLY to the case that needs it (see `isracard_file.py`, where blank vouchers
   get extra fields but rows with a voucher keep their original hash).
4. **Owner corrections always win and are never re-asked.** `merchant_overrides` >
   `ai_proposals` > default.
5. **Installments belong to the month they are CHARGED**, not the original purchase
   date. All 12 payments of one purchase carry the same purchase date in the statement;
   dating by it piles a year of payments onto one past month.

## 6. Traps that have already caused real bugs here

- **The sync button used to default to `--source seed`** and re-injected 341 rows of
  synthetic data into a live household database, corrupting every figure. It now
  defaults to `scraper` unless the DB has never held real data (`_default_source()`).
- **`SystemExit` inside `kaspion/cli.py` kills the server.** It is a `BaseException`
  and escapes `serve.py`'s `except Exception`. Command functions must raise
  `ValueError`; `__main__` converts it back for the terminal.
- **Merchant names are free text and contain quotes** (`ד"ר`). Any interpolation into
  an HTML attribute must go through `escAttr`, or the attribute terminates early and
  the row's data is silently corrupted.
- **ONE ZERO stores Hebrew reversed** behind a U+202D override. Reversing the whole
  string fixes the words but flips digits too (a 4-digit card number comes back reversed). Reverse Hebrew
  runs only, and skip rows that lack the override — they are already correct.
- **Statement section positions move between files.** Isracard exports have
  `עסקאות למועד חיוב`, `עסקאות לידיעה` and `עסקאות שטרם נקלטו` at different rows per
  month. Scan for header rows; never hardcode row numbers.
- **`assert_card_debit_matches_statement.sql` is a silent no-op.** It maps debits to
  the seed's account ids (`max-1234`, `isracard-5678`) while the real ones are
  the real ones (`max-<digits>`/`isracard-<digits>`), so its join is empty and it always passes. Fixing it
  properly needs statement-period modelling (Isracard's cycle runs ~9th–8th, not a
  calendar month). **Do not trust it as coverage.**
- **`dashboard.html` reloads after every edit.** UI state (view, month, filter, sort,
  search) is persisted in `sessionStorage` — the month is stored by KEY, never index,
  because importing a statement adds months and shifts indices.

## 7. Layout

| Path | What |
|---|---|
| `sync.py` | one entrypoint: ingest → dbt → categorize → dashboard |
| `kaspion/db.py` | connection + DDL; single source of truth for `raw`/`state` schemas |
| `kaspion/ingest/statements.py` | upload dispatcher: sniffs the file, shared upsert |
| `kaspion/ingest/isracard_file.py` | `.xlsx` parser (sections, installments, vouchers) |
| `kaspion/ingest/onezero_file.py` | `.xls` parser (bidi Hebrew, signed amounts) |
| `kaspion/ingest/scraper_loader.py` | runs the Node scraper per institution, isolated |
| `kaspion/ai/` | `known_merchants.py` rules → provider (ollama/claude/none) |
| `kaspion/report.py` | generates `dashboard.html` (all CSS+JS inline, one file) |
| `kaspion/serve.py` | local edit server; every `/api/*` rebuilds dbt + the report |
| `dbt/models/` | staging → intermediate → marts, 21 nodes, all tests must stay green |

## 8. Working rules

- **Always rebuild and verify after a change**: `dbt build -q` then
  `python3 -c "from kaspion.report import build_report; build_report()"`. dbt must
  report **21/21** (12 pass + 9 success).
- **Verify by measuring, not by eyeballing.** Chart geometry, colours and totals have
  all been wrong here in ways a screenshot did not reveal. Query the DB; read computed
  styles; reconcile against the statement totals printed in the source files.
- **Never invent financial figures.** If data is missing (a month outside the export
  range), say so in the UI rather than rendering a confident zero.
- The AI categorizer drops merchants it is unsure about; re-running picks them up.
  That is expected, not a bug.
- Credentials live in `data/credentials.json.enc` + `data/.kaspion_key` (AES-256-GCM,
  0600, gitignored). `.claude/settings.json` denies reading them. Never print, log, or
  echo credential values; the interactive `python3 -m kaspion.ingest.crypto` prompt is
  the owner's job, not the agent's.
