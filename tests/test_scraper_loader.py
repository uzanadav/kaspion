import subprocess

import duckdb
import pytest

from kaspion.db import DDL
from kaspion.ingest.scraper_loader import _assign_ids


def _con():
    con = duckdb.connect(":memory:")
    con.execute(DDL)
    return con


def _row(source_id, posted_date, amount, raw_description="x", account_id="a"):
    return {"source_id": source_id, "posted_date": posted_date, "amount": amount,
            "raw_description": raw_description, "account_id": account_id}


def test_reused_source_id_falls_back_to_natural_key():
    """FIBI/Beinleumi reuses one reference for every occurrence of a recurring order —
    each occurrence (different date/amount) must still get its own id, not collapse
    into one row."""
    rows = [
        _row("99400", "2026-05-30", -2750),
        _row("99400", "2026-06-01", -1650),
        _row("99400", "2026-06-23", -470),
    ]
    kept = _assign_ids(rows, _con())
    assert len(kept) == 3
    assert len({r["transaction_id"] for r in kept}) == 3


def test_genuinely_unique_source_id_still_trusted():
    """A real per-transaction bank id (one date+amount per reference) keeps the stable,
    rerun-idempotent hash — unaffected by the recurring-order fallback above."""
    kept1 = _assign_ids([_row("555", "2026-06-01", -100)], _con())
    kept2 = _assign_ids([_row("555", "2026-06-01", -100)], _con())
    assert kept1[0]["transaction_id"] == kept2[0]["transaction_id"]


def test_same_day_same_amount_same_description_collapses_to_one():
    """Two rows with identical content (date, amount, description, account) are
    treated as ONE transaction, not two — a real bug found in this household's data:
    a bank scrape returned the same movement twice in a single fetch (most likely a
    pending + settled pair), and there is no reliable signal to distinguish that from
    a genuine same-day coincidence. See kaspion.db.assign_natural_ids for the trade-off."""
    rows = [
        _row(None, "2026-06-01", -50, "coffee"),
        _row(None, "2026-06-01", -50, "coffee"),
    ]
    kept = _assign_ids(rows, _con())
    assert len(kept) == 1


def test_rescraping_the_same_transaction_does_not_duplicate_it():
    """A natural-key id must be stable ACROSS separate calls (separate sync runs) — the
    actual bug this scheme replaced: a transaction already in the database must never
    be assigned a second, different id and inserted again."""
    con = _con()
    first = _assign_ids([_row(None, "2026-06-01", -50, "coffee")], con)
    con.execute(
        "INSERT INTO raw.transactions "
        "(transaction_id, account_id, account_type, posted_date, amount, "
        " raw_description, source) VALUES (?, 'a', 'bank', '2026-06-01', -50, 'coffee', 'x')",
        [first[0]["transaction_id"]],
    )
    second = _assign_ids([_row(None, "2026-06-01", -50, "coffee")], con)
    assert second == []  # already known by content — nothing new to insert


def test_vendored_browser_cache_is_only_forced_when_it_exists(tmp_path, monkeypatch):
    """Pointing puppeteer at a .puppeteer folder that isn't there (an install predating
    the vendored browser, or a dev checkout) made EVERY bank fail with UNKNOWN."""
    from kaspion.ingest import scraper_loader as sl

    seen: dict = {}

    def fake_run(cmd, **kw):
        seen.update(kw["env"])
        raise subprocess.TimeoutExpired(cmd, 1)   # stop before any real scraping

    monkeypatch.setattr(sl.subprocess, "run", fake_run)
    cfg = {"credentials": {}, "type": "bank"}

    monkeypatch.setattr(sl, "PUPPETEER_CACHE", tmp_path / "missing")
    with pytest.raises(sl.ScrapeError):
        sl._scrape_company("max", cfg, 7)
    assert "PUPPETEER_CACHE_DIR" not in seen

    seen.clear()
    monkeypatch.setattr(sl, "PUPPETEER_CACHE", tmp_path)
    with pytest.raises(sl.ScrapeError):
        sl._scrape_company("max", cfg, 7)
    assert seen["PUPPETEER_CACHE_DIR"] == str(tmp_path)


def test_zero_amount_placeholder_is_replaced_by_the_settled_charge(tmp_path, monkeypatch):
    """A pending Max purchase arrives as 0 and settles later under the same id; without
    the purge, ON CONFLICT DO NOTHING would leave ₪0 on the dashboard forever."""
    from kaspion.ingest import scraper_loader as sl

    db = tmp_path / "t.duckdb"
    monkeypatch.setattr(sl, "connect", lambda: duckdb.connect(str(db)))
    con = duckdb.connect(str(db))
    con.execute(DDL)
    con.execute("INSERT INTO raw.transactions (transaction_id, account_id, account_type,"
                " posted_date, amount, currency, raw_description, source) VALUES "
                "('abc', 'max-1', 'credit_card', DATE '2026-08-18', 0, 'ILS', 'בריכה', 'max')")
    con.close()

    sl._ingest([{"source_id": "abc", "account_id": "max-1", "account_type": "credit_card",
                 "posted_date": "2026-08-18", "amount": -160.0, "currency": "ILS",
                 "raw_description": "בריכה", "source": "max"}])

    con = duckdb.connect(str(db))
    assert con.execute("SELECT amount FROM raw.transactions").fetchall() == [(-160,)]
