"""Trips — a named date range plus per-trip row exclusions.

The date filtering itself lives in app.js (it runs over rows already in the page); what
is testable here is the validation and the two state tables.
"""
import duckdb
import pytest

from kaspion.cli import trip_row
from kaspion.db import DDL


def _con():
    con = duckdb.connect(":memory:")
    con.execute(DDL)
    return con


def test_valid_trip_is_normalized_and_gets_a_stable_id():
    a = trip_row("  יוון  ", " Greece ", "2026-08-24", "2026-08-31")
    assert a["name"] == "יוון" and a["country"] == "Greece"
    assert a["start_date"] == "2026-08-24" and a["end_date"] == "2026-08-31"
    assert len(a["trip_id"]) == 12
    # same trip entered twice must update, never duplicate
    assert trip_row("יוון", "Greece", "2026-08-24", "2026-08-31")["trip_id"] == a["trip_id"]


def test_a_single_day_trip_is_allowed():
    t = trip_row("יום בים", "", "2026-08-24", "2026-08-24")
    assert t["start_date"] == t["end_date"]


@pytest.mark.parametrize("args", [
    ("", "", "2026-08-24", "2026-08-31"),          # no name
    ("   ", "", "2026-08-24", "2026-08-31"),
    ("יוון", "", "24/08/2026", "2026-08-31"),      # not what <input type="date"> submits
    ("יוון", "", "2026-08-24", ""),
    ("יוון", "", "2026-08-31", "2026-08-24"),      # backwards
])
def test_bad_input_raises_valueerror(args):
    # ValueError, never SystemExit: this runs inside serve.py, whose `except Exception`
    # would not catch a BaseException and the whole server would go down
    with pytest.raises(ValueError):
        trip_row(*args)


def test_exclusions_are_per_trip_and_reversible():
    con = _con()
    con.execute("INSERT INTO state.trips (trip_id, name, country, start_date, end_date) "
                "VALUES ('t1', 'יוון', 'Greece', '2026-08-24', '2026-08-31')")
    con.execute("INSERT INTO state.trip_exclusions VALUES ('t1', 'txn-rent')")
    n = lambda: con.execute("SELECT count(*) FROM state.trip_exclusions").fetchone()[0]  # noqa: E731
    assert n() == 1
    # the same row can be excluded from a second trip without conflicting
    con.execute("INSERT INTO state.trip_exclusions VALUES ('t2', 'txn-rent')")
    assert n() == 2
    con.execute("DELETE FROM state.trip_exclusions WHERE trip_id = 't1' "
                "AND transaction_id = 'txn-rent'")
    assert n() == 1
