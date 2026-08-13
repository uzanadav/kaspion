"""Optional edit mode: serve the dashboard on 127.0.0.1 with add/remove enabled.

    python3 -m kaspion.serve          # then open http://127.0.0.1:8765

Opening dashboard.html directly (file://) stays read-only — perfect for viewing.
Through this server the dashboard shows an add-transaction form and per-row
hide buttons; every change rebuilds dbt + regenerates the page. Stdlib only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from kaspion.cli import (
    add_category,
    add_transaction,
    delete_category,
    recategorize,
    remove_transaction,
    set_budget,
)
from kaspion.report import OUT

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", 8765
# the page works identically served (http://127.0.0.1:8765) or opened as a file;
# for the file case we must allow its "null" origin — and nothing else.
ALLOWED_ORIGINS = {None, "null", f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _build_report() -> None:
    # always regenerate in a FRESH process so a long-running server can never
    # render the page from stale, in-memory code after the repo was updated
    subprocess.run([sys.executable, "-m", "kaspion.report"], cwd=ROOT, check=True)


def _rebuild() -> None:
    env = dict(os.environ, DBT_PROFILES_DIR=".")
    subprocess.run(["dbt", "build", "-q"], cwd=ROOT / "dbt", env=env, check=True)
    _build_report()


def _default_source() -> str:
    """'scraper' for a live household, 'seed' only for an untouched demo database.

    Guards the sync button: re-ingesting sample_transactions.csv into a database that
    already holds real bank data silently poisons every total on the dashboard.
    """
    from kaspion.db import connect

    con = connect()
    real = con.execute(
        "SELECT count(*) FROM raw.transactions WHERE source NOT IN ('seed', 'manual')"
    ).fetchone()[0]
    con.close()
    return "scraper" if real else "seed"


def _import_upload(filename: str, data_b64: str) -> dict:
    """Import one uploaded statement, then rebuild exactly like a sync would."""
    import base64
    import tempfile

    from kaspion.ingest.statements import import_statement

    if not filename.lower().endswith((".xlsx", ".xls")):
        raise ValueError(f"expected an Excel statement, got '{filename}'")
    blob = base64.b64decode(data_b64)
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
        tmp.write(blob)
        tmp_path = tmp.name
    try:
        # the bank is detected from the file's own contents, not its name
        outcome = import_statement(tmp_path)
        added, updated = outcome["added"], outcome["updated"]
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # new merchants need categories before the rebuild, same as sync.py does.
    # Ollama being down must not fail the import — the rows are already saved.
    categorized = 0
    try:
        from kaspion.ai.categorize import categorize_new_merchants

        by_rules, by_ai = categorize_new_merchants()
        categorized = by_rules + by_ai
    except Exception:  # noqa: BLE001 - AI is optional, the import already succeeded
        pass
    _rebuild()
    return {"ok": True, "source": outcome["source"], "added": added,
            "updated": updated, "categorized": categorized}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/dashboard.html"):
            if not OUT.exists():
                _build_report()
            body = OUT.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin")
        if origin not in ALLOWED_ORIGINS:  # block requests from other websites
            self.send_error(403)
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD_BYTES:  # a card statement is ~15KB; refuse anything wild
            self.send_error(413)
            return
        payload = json.loads(self.rfile.read(length) or b"{}")
        result: dict = {"ok": True}
        try:
            if self.path == "/api/sync":
                # full pipeline: ingest -> dbt -> categorize -> dashboard.
                # sync.py rebuilds the report itself, so no _rebuild() here.
                #
                # The source defaults to 'scraper', NOT 'seed': once a household has
                # real transactions, a sync button that quietly re-injects the
                # synthetic sample data corrupts every figure on the dashboard.
                # _default_source() only falls back to the sample data on a database
                # that has never seen anything else.
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "sync.py"),
                     "--source", payload.get("source") or _default_source()],
                    cwd=ROOT, capture_output=True, text=True,
                )
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout)[-400:])
            elif self.path == "/api/add":
                add_transaction(
                    payload["description"], float(payload["amount"]),
                    payload.get("category", "other"), payload.get("date") or None,
                )
                _rebuild()
            elif self.path == "/api/remove":
                remove_transaction(payload["transaction_id"])
                _rebuild()
            elif self.path == "/api/recategorize":
                # saved as a merchant override: wins over the AI forever,
                # and the AI is never asked about this merchant again
                recategorize(payload["merchant"], payload["category"])
                _rebuild()
            elif self.path == "/api/set-budget":
                set_budget(payload["category"], float(payload["amount"]))
                _rebuild()
            elif self.path == "/api/add-category":
                add_category(payload["category_id"], payload["name"])
                _rebuild()
            elif self.path == "/api/delete-category":
                # anything pointing at it is moved to 'other' first, so the rebuild
                # never sees a transaction referencing a category that's gone
                moved = delete_category(payload["category_id"])
                _rebuild()
                result = {"ok": True, "moved": moved}
            elif self.path == "/api/upload":
                # Isracard statement (.xlsx) uploaded from the dashboard — the scraper
                # can't log in past their reCAPTCHA, so the file is the supported path.
                result = _import_upload(payload["filename"], payload["data"])
            else:
                self.send_error(404)
                return
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as exc:  # surface the reason to the UI
            body = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        pass


def main() -> None:
    _build_report()
    print(f"kaspion dashboard: http://{HOST}:{PORT}  (Ctrl+C to stop)")
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
