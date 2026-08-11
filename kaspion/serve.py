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

from kaspion.cli import add_transaction, recategorize, remove_transaction, set_budget
from kaspion.report import OUT

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", 8765
# the page works identically served (http://127.0.0.1:8765) or opened as a file;
# for the file case we must allow its "null" origin — and nothing else.
ALLOWED_ORIGINS = {None, "null", f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}


def _build_report() -> None:
    # always regenerate in a FRESH process so a long-running server can never
    # render the page from stale, in-memory code after the repo was updated
    subprocess.run([sys.executable, "-m", "kaspion.report"], cwd=ROOT, check=True)


def _rebuild() -> None:
    env = dict(os.environ, DBT_PROFILES_DIR=".")
    subprocess.run(["dbt", "build", "-q"], cwd=ROOT / "dbt", env=env, check=True)
    _build_report()


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
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/api/sync":
                # full pipeline: ingest -> dbt -> categorize -> dashboard.
                # sync.py rebuilds the report itself, so no _rebuild() here.
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "sync.py"),
                     "--source", payload.get("source", "seed")],
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
            else:
                self.send_error(404)
                return
            body = b'{"ok": true}'
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
