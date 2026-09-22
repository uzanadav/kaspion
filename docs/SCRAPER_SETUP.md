# Connecting a real bank or credit card

Step-by-step guide for when you're ready to switch from sample data to real data.
Nothing here needs to happen now — the whole pipeline works on the seed until you do this.

## The easy way — from the dashboard

Open the dashboard (`python3 -m kaspion.serve`) and press **➕ הוספת חשבון** in the
sidebar. Pick the institution, fill in the fields it asks for, press the button. The
server verifies the login before saving anything, then pulls 90 days of history and
reloads the page with the account showing real data — no terminal needed. This is the
supported path for a non-technical household member; the rest of this document is the
manual/terminal equivalent, useful mainly for scripting a first bulk setup or debugging
a failed login.

**Isracard and Amex are the exception** — their login is blocked by reCAPTCHA (see
`docs/AGENT_HANDOFF.md` §4) and appear greyed out in the dialog. Upload their statement
`.xlsx` with the **📄 טעינת קובץ** sidebar button instead. **ONE ZERO** needs a one-time 2FA enrollment
the dialog can't do either — use its PDF statement (or the older `.xls` export) the same way.

## What you'll set up (terminal path)

```
any bank/card israeli-bank-scrapers   ─▶ israeli-bank-scrapers ─▶ raw.transactions ─▶ everything else, unchanged
supports (leumi, max, beinleumi, …)          (Node, local)
```

The scraper logs into each institution's website with your credentials (encrypted on disk),
downloads recent transactions, and writes them into the same table the sample data used.
Nothing downstream changes.

## Prerequisites

- Node.js 18+ (`node --version`)
- Your login credentials for each institution (the same ones you use on their website/app)

## Step 1 — Install the scraper library (one time)

```bash
cd scraper && npm install && cd ..   # end users get this from `install`
```

This downloads `israeli-bank-scrapers` + a headless Chromium (~300 MB, used to drive the bank sites).

## Step 2 — Save credentials (encrypted)

```bash
python3 -m kaspion.ingest.crypto
```

It prompts per institution. `kaspion.ingest.crypto.COMPANY_FIELDS` lists every
institution it knows (17, copied from `israeli-bank-scrapers` itself) with the exact
fields each one needs — the prompt shows them for a known id. A few examples:

| Company id | Type | Credential fields | Notes |
|---|---|---|---|
| `leumi` | bank | `username`, `password` | your leumi website login |
| `beinleumi` | bank | `username`, `password` | הבינלאומי / FIBI |
| `max` | credit_card | `username`, `password` | login for max.co.il |
| `visaCal` | credit_card | `username`, `password` | כאל |
| `isracard` | credit_card | `id`, `card6Digits`, `password` | תעודת זהות, 6 ספרות אחרונות של הכרטיס, סיסמת האתר — **login is blocked by reCAPTCHA, use the XLSX upload instead** |

Credentials are encrypted with AES-256-GCM into `data/credentials.json.enc`; the key file
`data/.kaspion_key` gets 0600 permissions. Both are gitignored. Nothing is ever logged or
passed on a command line.

Start with ONE institution, verify, then add the rest.

## Step 3 — First real run

```bash
python3 sync.py --skip-categorize
```

Expect this to take 1–3 minutes per institution (it's driving a real browser).

## Step 4 — Verify before trusting the numbers (important, once per institution)

```bash
python3 - <<'EOF'
from kaspion.db import connect
con = connect()
# 1. sign convention: charges/debits must be NEGATIVE
print(con.execute("""
    select source, case when amount < 0 then 'outflow' else 'inflow' end, count(*), round(sum(amount))
    from raw.transactions where source != 'seed' group by 1,2 order by 1,2
""").fetchall())
# 2. the monthly card debit (חיוב) must be flagged, not counted as spend
print(con.execute("select raw_description, amount from main.int_card_payments order by posted_date desc limit 5").fetchall())
con.close()
EOF
```

- If an institution reports charges as **positive**, negate its amounts in
  `scraper/scrape.js` (marked with a comment) — never downstream.
- If your card debit description isn't caught, extend the regex in
  `dbt/models/intermediate/int_card_payments.sql`. `dbt/tests/assert_card_payments_excluded.sql`
  will fail if a bank-side card debit ever slips through uncaught into spend — that's the
  test to watch after adding a new institution.

## Step 5 — Clean out the sample data

```bash
python3 - <<'EOF'
from kaspion.db import connect
con = connect()
con.execute("DELETE FROM raw.transactions WHERE source = 'seed'")
con.execute("DELETE FROM state.ai_proposals")   # proposals learned from seed merchants
con.close()
print("seed data removed")
EOF
python3 sync.py    # rebuild + categorize real merchants
```

## Step 6 — Make it routine

```bash
# manual: run whenever you want fresh numbers
python3 sync.py

# or automatic daily at 07:00 (macOS/Linux cron):
crontab -e
# 0 7 * * * cd ~/Desktop/kaspion && ./.venv/bin/python3 sync.py >> ~/kaspion-sync.log 2>&1
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `INVALID_PASSWORD` | credentials typo — rerun `python3 -m kaspion.ingest.crypto` |
| `CHANGE_PASSWORD` | the bank forces a password change — do it on their site first |
| Login hangs / captcha | banks sometimes challenge automation; retry later, or watch it happen with `KASPION_SHOW_BROWSER=1 python3 sync.py` |
| `INVALID_PASSWORD` but the same credentials work in your browser | the library reports every non-success login code as `INVALID_PASSWORD`. Isracard/Amex in particular are known to block automated logins (bot detection / Cloudflare WAF). Run with `KASPION_SHOW_BROWSER=1` to see whether a block page or verification step is what's actually returned. |
| 2FA / OTP prompt | some accounts require SMS codes; israeli-bank-scrapers has limited OTP support per bank — check its README for your institution |
| Duplicate transactions | shouldn't happen (dedup by transaction id) — if it does, the institution changed its id format; check `_assign_ids` in `kaspion/ingest/scraper_loader.py` |

## Notes

- Scraping may violate the banks' Terms of Service. Own accounts, own machine, own risk.
- The scraper talks only to the bank, over TLS. Your credentials and data never go anywhere else.
- Each institution's site changes occasionally and the library updates to match —
  if a scrape suddenly breaks, try `cd scraper && npm update israeli-bank-scrapers`.
