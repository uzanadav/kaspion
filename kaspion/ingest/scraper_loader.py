from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from kaspion.db import assign_natural_ids, connect
from kaspion.ingest.crypto import (
    COMPANY_FIELDS,
    CRED_FILE,
    company_of,
    load_credentials,
    next_connection_id,
    save_credentials,
)

SCRAPER_DIR = Path(__file__).resolve().parents[2] / "scraper"
# a captcha or stuck login leaves the headless browser waiting forever; the server that
# calls this is single-threaded, so an unbounded scrape freezes the whole dashboard
SCRAPE_TIMEOUT = 240


def _node_bin() -> str:
    """Node ships as a Python dependency (nodejs-wheel), so it lives next to the
    interpreter rather than on PATH. Fall back to a system Node for developers who
    installed the package some other way."""
    exe = "node.exe" if os.name == "nt" else "node"
    bundled = Path(sys.executable).parent / exe
    return str(bundled) if bundled.exists() else (shutil.which("node") or exe)


class ScrapeError(Exception):
    """A scrape failed. error_type is the scraper's own code (INVALID_PASSWORD, etc.);
    never put credential values in the message — this reaches the browser as-is."""

    def __init__(self, who: str, error_type: str, message: str):
        self.who, self.error_type = who, error_type
        super().__init__(f"{who}: {message or error_type}")


# Hebrew text for the live sync log (dashboard-facing, not the terminal). Deliberately a
# short subset of app.js's ERROR_TYPE_HE, not the full map — this is a print(), not a
# form; anything not listed here just reads "ההתחברות נכשלה", which is still honest.
_ERROR_TYPE_HE = {
    "INVALID_PASSWORD": "שם משתמש או סיסמה שגויים",
    "CHANGE_PASSWORD": "הבנק דורש החלפת סיסמה",
    "ACCOUNT_BLOCKED": "החשבון נחסם על ידי הבנק",
    "TIMEOUT": "ההתחברות ארכה זמן רב מדי",
}


def _display_name(company: str, cfg: dict) -> str:
    # the owner-typed per-connection label ("אשתי") wins when set; otherwise the
    # institution's own Hebrew name from COMPANY_FIELDS — NOT the bare company id
    # ("max"), which is what a household member would actually see in the log
    return cfg.get("label") or COMPANY_FIELDS.get(company, {}).get("label", company)


def _scrape_company(company: str, cfg: dict, days_back: int) -> list[dict]:
    # disambiguates error messages when a company has more than one saved connection
    # ("מקס (אשתי): ..." vs. a bare, ambiguous "מקס: ...")
    who = _display_name(company, cfg)
    try:
        proc = subprocess.run(
            [_node_bin(), "scrape.js"],
            cwd=SCRAPER_DIR,
            env=dict(
                os.environ,
                KASPION_COMPANY=company,
                KASPION_CREDENTIALS=json.dumps(cfg["credentials"]),
                KASPION_ACCOUNT_TYPE=cfg["type"],
                KASPION_START_DATE=(date.today() - timedelta(days=days_back)).isoformat(),
            ),
            capture_output=True,
            text=True,
            # explicit, not left to the platform default: Windows decodes with the
            # local ANSI codepage otherwise, corrupting the scraper's UTF-8 JSON
            # (Hebrew merchant names in particular)
            encoding="utf-8",
            check=True,
            timeout=SCRAPE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise ScrapeError(who, "TIMEOUT", "scraper timed out") from e
    except subprocess.CalledProcessError as e:
        # stderr is the scraper's own {error, message} json — never contains credentials
        try:
            err = json.loads(e.stderr or "{}")
        except json.JSONDecodeError:
            err = {}
        raise ScrapeError(who, err.get("error", "UNKNOWN"), err.get("message", "")) from e
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ScrapeError(who, "UNKNOWN", "scraper returned unreadable output") from e


def _ingest(rows: list[dict]) -> int:
    con = connect()
    rows = _assign_ids(rows, con)
    before = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    if rows:
        con.executemany(
            """
            INSERT INTO raw.transactions
                (transaction_id, account_id, account_type, posted_date,
                 amount, currency, raw_description, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (transaction_id) DO NOTHING
            """,
            [
                [r["transaction_id"], r["account_id"], r["account_type"], r["posted_date"],
                 r["amount"], r["currency"], r["raw_description"], r["source"]]
                for r in rows
            ],
        )
    after = con.execute("SELECT count(*) FROM raw.transactions").fetchone()[0]
    con.close()
    return after - before


def load_from_scraper(days_back: int = 90) -> int:
    # a brand-new install has no credentials file yet — that must read as "nothing
    # connected yet", not crash with FileNotFoundError. Same guard already used for
    # this exact file elsewhere in this module and in crypto.py.
    creds = load_credentials() if CRED_FILE.exists() else {}
    if not creds:
        print("STATUS::עדיין לא חוברו חשבונות — הוסיפו חשבון מהדשבורד", flush=True)
        return 0
    total_new = 0
    failures: list[str] = []
    succeeded = 0
    for conn_id, cfg in creds.items():
        who = _display_name(company_of(conn_id), cfg)
        # STATUS:: is a second, curated output channel: serve.py's /api/sync handler
        # reads ONLY these lines live (while the request is still in flight) into the
        # dashboard's sync log. Every other print() in this module is unchanged
        # developer/terminal output — do not put anything here you wouldn't want a
        # non-technical household member reading in the browser.
        print(f"STATUS::מתחברים אל {who}…", flush=True)
        # never let one bank's outage throw away another's data: a failure here is
        # reported and skipped, and whatever did scrape still gets ingested below.
        try:
            rows = _scrape_company(company_of(conn_id), cfg, days_back)
        except ScrapeError as e:
            failures.append(str(e))
            print(f"STATUS::✗ {who} — {_ERROR_TYPE_HE.get(e.error_type, 'ההתחברות נכשלה')}",
                  flush=True)
            continue
        # ingested per institution, not batched at the end — this is what makes a
        # per-institution "N new records" figure possible; _assign_ids still only needs
        # to see one institution's own rows to catch its own reused reference numbers
        new = _ingest(rows)
        total_new += new
        succeeded += 1
        print(f"      · {who}: {len(rows)} transactions, {new} new")
        print(f"STATUS::✓ {who} — {new} רשומות חדשות", flush=True)

    for f in failures:
        print(f"      ⚠ {f}")
    # Only a total wipe-out is fatal. Keying this off `total_new`/`succeeded` instead of
    # rows scraped would abort a run where one bank succeeded but legitimately had
    # nothing new — falsely claiming every institution failed, and throwing away the
    # run this isolation exists to save.
    if failures and succeeded == 0:
        raise RuntimeError(
            "all configured institutions failed to scrape:\n  " + "\n  ".join(failures)
        )

    return total_new


def add_institution(company: str, credentials: dict, account_type: str, label: str = "") -> int:
    """Verify a login before saving anything, then pull its history.

    Always creates a NEW connection — a second login to a company already saved (e.g.
    two Max accounts for two family members) gets its own entry, never overwrites the
    first. Raises ScrapeError on a bad login — nothing is written to disk in that case.
    """
    cfg = {"type": account_type, "credentials": credentials, "label": label}
    _scrape_company(company, cfg, days_back=7)  # probe — raises on bad login, no side effect
    creds = load_credentials() if CRED_FILE.exists() else {}
    creds[next_connection_id(creds, company)] = cfg  # merge, never wipe the rest of the file
    save_credentials(creds)
    rows = _scrape_company(company, cfg, days_back=90)
    return _ingest(rows)


def _assign_ids(rows: list[dict], con) -> list[dict]:
    # Some institutions (FIBI/Beinleumi) reuse one reference number for every occurrence
    # of a recurring standing order instead of issuing a per-transaction id — trusting it
    # blindly collapses a whole series into a single row. Only trust source_id when it
    # actually maps to one distinct (date, amount) in this batch; otherwise leave
    # transaction_id unset and let db.assign_natural_ids handle it — including the case
    # where a "trusted" source_id still collides in content with another row (see its
    # docstring for why content wins over a raw reference number either way).
    seen_for_source: dict[str, set] = defaultdict(set)
    for r in rows:
        if r.get("source_id"):
            seen_for_source[str(r["source_id"])].add((r["posted_date"], str(r["amount"])))

    for r in rows:
        sid = r.get("source_id")
        if sid and len(seen_for_source[str(sid)]) == 1:
            r["transaction_id"] = hashlib.sha256(
                f"{r['account_id']}|{sid}".encode()).hexdigest()[:16]

    return assign_natural_ids(rows, con)
