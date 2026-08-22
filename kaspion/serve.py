"""Optional edit mode: serve the dashboard on 127.0.0.1 with add/remove enabled.

    python3 -m kaspion.serve          # then open http://127.0.0.1:8765

Opening dashboard.html directly (file://) stays read-only — perfect for viewing.
Through this server the dashboard shows an add-transaction form and per-row
hide buttons; every change rebuilds dbt + regenerates the page. Stdlib only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kaspion.cli import (
    add_category,
    add_transaction,
    delete_category,
    recategorize,
    remove_transaction,
    set_budget,
)
from kaspion.ingest.crypto import COMPANY_FIELDS, remove_credentials
from kaspion.ingest.scraper_loader import ScrapeError, add_institution
from kaspion.pipeline import run_dbt
from kaspion.report import OUT

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", 8765
# the page works identically served (http://127.0.0.1:8765) or opened as a file;
# for the file case we must allow its "null" origin — and nothing else.
ALLOWED_ORIGINS = {None, "null", f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# ThreadingHTTPServer so one idle browser tab cannot hang every other request. This lock
# puts the serial guarantee back only where it is needed: DuckDB allows a single
# read-write connection, so no two requests may run dbt/report subprocesses at once.
_DB_LOCK = threading.Lock()
# live sync progress, polled by GET /api/sync-status while a POST /api/sync is still in
# flight — that POST takes minutes, so it is the only way to show per-institution
# progress rather than one message at the very end.
_sync_status: dict = {"running": False, "lines": []}
_sync_lock = threading.Lock()


class SyncError(RuntimeError):
    """A sync that exited non-zero. A traceback is not an error message for a household
    member, so the user-facing sentence and the raw output tail travel separately — the
    dashboard shows the sentence and hides the tail behind "פרטים טכניים"."""

    def __init__(self, detail: str) -> None:
        super().__init__("הסנכרון לא הושלם — ראו את שורות הסטטוס שלמעלה")
        self.detail = detail


def _build_report() -> None:
    # always regenerate in a FRESH process so a long-running server can never
    # render the page from stale, in-memory code after the repo was updated
    subprocess.run([sys.executable, "-m", "kaspion.report"], cwd=ROOT, check=True)


def _rebuild() -> None:
    run_dbt()
    _build_report()


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
    def do_GET(self) -> None:
        if self.path in ("/", "/dashboard.html"):
            if not OUT.exists():
                # A data directory that holds a database but no dbt models (an install
                # interrupted between the two, or KASPION_DATA_DIR moved) cannot build a
                # report. Unguarded, that raised once PER REQUEST: a window full of
                # tracebacks and a page that never loads. Say what to do instead.
                try:
                    # under _DB_LOCK like every other DB-touching path: this spawns a
                    # process that opens the DuckDB file read-write, and a sync holding
                    # the lock has it open already — unsynchronised, the page load fails
                    # with a DuckDB "file is locked" that explains nothing to the reader
                    with _DB_LOCK:
                        if not OUT.exists():  # another thread may have built it while we waited
                            _build_report()
                except subprocess.CalledProcessError:
                    self.send_error(
                        500,
                        "kaspion is not set up yet",
                        "לא ניתן לבנות את הדשבורד — ייתכן שההתקנה לא הושלמה.\n"
                        "הריצו שוב את install, או מהטרמינל: python3 -m kaspion.cli init",
                    )
                    return
            body = OUT.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/sync-status":
            # deliberately outside _DB_LOCK: this must stay responsive WHILE a POST
            # /api/sync holds that lock for the whole scrape, or polling could never see
            # any progress until the very end — same defeats the purpose it exists for.
            origin = self.headers.get("Origin")
            if origin not in ALLOWED_ORIGINS:
                self.send_error(403)
                return
            with _sync_lock:
                body = json.dumps({"running": _sync_status["running"],
                                    "lines": list(_sync_status["lines"])},
                                   ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
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
        # serializes DB/dbt-touching work across threads (see _DB_LOCK above); reading
        # the request body above happens OUTSIDE the lock so a slow client doesn't hold
        # other requests hostage — only the actual mutation is exclusive.
        with _DB_LOCK:
            try:
                if self.path == "/api/sync":
                    # full pipeline: ingest -> dbt -> categorize -> dashboard.
                    # sync.py rebuilds the report itself, so no _rebuild() here.
                    #
                    # The source defaults to 'scraper', NEVER 'seed': once a household
                    # has real transactions, a sync button that quietly re-injects the
                    # synthetic sample data corrupts every figure on the dashboard. A
                    # brand-new install with no credentials yet still hits this path —
                    # load_from_scraper() handles "nothing connected yet" itself,
                    # printing a status line rather than crashing or falling back to
                    # fake data.
                    #
                    # Popen + a live line-by-line read (not subprocess.run) so
                    # /api/sync-status has something to report while this request is
                    # still in flight. "-u" forces sync.py's stdout unbuffered — piped
                    # (non-tty) stdout is block-buffered by default, which would hold
                    # every line back until the process exits and defeat the point.
                    with _sync_lock:
                        _sync_status["running"] = True
                        _sync_status["lines"] = []
                    output: list[str] = []
                    try:
                        proc = subprocess.Popen(
                            [sys.executable, "-u", str(ROOT / "sync.py"),
                             "--source", payload.get("source") or "scraper"],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            # explicit, not the platform default: Windows decodes with
                            # the local ANSI codepage otherwise, and sync.py prints
                            # Hebrew status lines this loop reads live
                            text=True, encoding="utf-8",
                        )
                        for line in proc.stdout:
                            line = line.rstrip("\n")
                            output.append(line)
                            # STATUS:: lines are Hebrew, written for the dashboard —
                            # everything else here is the same output a terminal run
                            # of sync.py has always printed, just also captured for
                            # the error message below if the process fails.
                            if line.startswith("STATUS::"):
                                with _sync_lock:
                                    _sync_status["lines"].append(line[len("STATUS::"):])
                        proc.wait()
                        if proc.returncode != 0:
                            raise SyncError("\n".join(output[-15:]))
                    finally:
                        with _sync_lock:
                            _sync_status["running"] = False
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
                    # Isracard statement (.xlsx) uploaded from the dashboard — the
                    # scraper can't log in past their reCAPTCHA, so the file is the
                    # supported path.
                    result = _import_upload(payload["filename"], payload["data"])
                elif self.path == "/api/add-account":
                    # company must be a known id — never free text — so only
                    # whitelisted field names are ever read out of the payload and
                    # passed to the scraper
                    company = payload.get("company")
                    if company not in COMPANY_FIELDS:
                        raise ValueError("unknown institution")
                    inst = COMPANY_FIELDS[company]
                    if inst.get("blocked"):
                        raise ValueError("this institution requires the file-upload path")
                    sent = payload.get("credentials") or {}
                    creds = {f: str(sent.get(f, "")).strip() for f in inst["fields"]}
                    if not all(creds.values()):
                        raise ValueError("missing fields")
                    label = str(payload.get("label") or "").strip()
                    added = add_institution(company, creds, inst["type"], label)
                    _rebuild()
                    result = {"ok": True, "added": added}
                elif self.path == "/api/remove-account":
                    # removes the saved login only — transactions already pulled with
                    # it stay in the database untouched, same as disconnecting any
                    # other source
                    conn_id = payload.get("connection")
                    if not isinstance(conn_id, str) or not conn_id:
                        raise ValueError("missing connection id")
                    remove_credentials(conn_id)
                    _build_report()  # no dbt changes, just refresh what the dialog offers
                else:
                    self.send_error(404)
                    return
                body = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
            except ScrapeError as exc:
                # error_type lets the frontend show a Hebrew message per failure kind
                # (bad password vs. forced password change vs. timeout); the
                # exception's own text is scraper-generated and never contains the
                # credential values.
                body = json.dumps({"ok": False, "error": str(exc),
                                    "error_type": exc.error_type}, ensure_ascii=False).encode()
                self.send_response(400)
            # any endpoint's failure (bad payload, failed subprocess, missing file)
            # must reach the UI as a message, never crash the server or hang the request
            except Exception as exc:  # noqa: BLE001 - see above
                body = json.dumps({"ok": False, "error": str(exc),
                                    "detail": getattr(exc, "detail", "")},
                                   ensure_ascii=False).encode()
                self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        pass


def _already_serving(port: int) -> bool:
    """Is a kaspion server already answering on this port?

    Only ours counts: /api/sync-status is this app's own endpoint, and a bare request
    carries no Origin header, which ALLOWED_ORIGINS permits. Anything else holding the
    port (another app, a stale socket) fails to answer it and we move to the next port.
    """
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/sync-status", timeout=1) as r:
            return "running" in json.loads(r.read())
    # every failure means "not our server here": refused, timed out, wrong app, bad JSON.
    # There is nothing to distinguish and nothing to report — we just try the next port.
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    global ALLOWED_ORIGINS

    # A second launch must JOIN the running dashboard, never start a rival one. Two
    # servers on one DuckDB file is not a cosmetic problem: DuckDB gives read-write to a
    # single process, so the second instance's first sync fails. It also silently moves
    # the dashboard to another port, so a double-click looks like it "did nothing" while
    # the browser sits on the old URL.
    if _already_serving(PORT):
        url = f"http://{HOST}:{PORT}"
        print(f"kaspion is already running: {url}")
        webbrowser.open(url)
        return

    # Try a few ports up from the default: a second instance used to die with an
    # unhandled "Address already in use".
    server = None
    port = PORT
    last_err: OSError | None = None
    for _ in range(10):
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
            break
        except OSError as e:
            last_err = e
            port += 1
    if server is None:
        raise SystemExit(f"could not bind a port near {PORT} on {HOST}: {last_err}")
    # ALLOWED_ORIGINS embeds the port, so it must be recomputed for whichever one we
    # actually bound or every edit request 403s. Handler reads this name as a module
    # global at call time, so reassigning it here (not at import) is enough.
    ALLOWED_ORIGINS = {None, "null", f"http://{HOST}:{port}", f"http://localhost:{port}"}
    server.daemon_threads = True  # a stuck request thread must not block shutdown

    # Bind first, build second: a report error must not stop the server from starting —
    # better a running server showing a stale page than no server and no explanation.
    try:
        _build_report()
    except subprocess.CalledProcessError as e:
        print(f"warning: could not build the dashboard ({e}) — fix the error and sync again")

    url = f"http://{HOST}:{port}"
    print(f"kaspion dashboard: {url}  (Ctrl+C to stop)")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
