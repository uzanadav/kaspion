import duckdb

from kaspion.db import DDL, assign_natural_ids


def _con():
    con = duckdb.connect(":memory:")
    con.execute(DDL)
    return con


def _row(posted_date, amount, raw_description, account_id="a", transaction_id=None):
    r = {"account_id": account_id, "posted_date": posted_date, "amount": amount,
         "raw_description": raw_description}
    if transaction_id:
        r["transaction_id"] = transaction_id
    return r


def test_content_collision_wins_even_over_a_preassigned_id():
    """Two rows sharing identical content but carrying DIFFERENT pre-assigned ids (a
    trusted bank reference or voucher number) still collapse to one — content identity
    always wins. This is what actually fixed a real duplicate: a Max charge came back
    from the scraper twice in one fetch under two different internal identifiers."""
    rows = [
        _row("2026-08-12", "0.00", "החישוק", transaction_id="aaaa"),
        _row("2026-08-12", "0.00", "החישוק", transaction_id="bbbb"),
    ]
    kept = assign_natural_ids(rows, _con())
    assert len(kept) == 1
    assert kept[0]["transaction_id"] == "aaaa"  # the first one encountered is kept as-is


def test_no_id_gets_a_stable_content_derived_one():
    kept = assign_natural_ids([_row("2026-08-12", "-10.00", "coffee")], _con())
    assert kept[0]["transaction_id"]


def test_different_dates_never_collide():
    rows = [_row("2026-06-11", "-100.00", "standing order"),
            _row("2026-07-11", "-100.00", "standing order")]
    kept = assign_natural_ids(rows, _con())
    assert len(kept) == 2
    assert kept[0]["transaction_id"] != kept[1]["transaction_id"]


def test_preassigned_id_still_checked_against_existing_content():
    """A regression test for a real bug: an earlier version of this function only
    checked the database for rows WITHOUT a pre-assigned id, so a row carrying a
    "trusted" reference-based id (deterministic per reference, but two different
    references can describe the same real movement — e.g. a pending + settled pair)
    sailed straight through and re-duplicated a transaction on the very next sync,
    even though its content already matched a row already in the database."""
    con = _con()
    con.execute(
        "INSERT INTO raw.transactions "
        "(transaction_id, account_id, account_type, posted_date, amount, "
        " raw_description, source) "
        "VALUES ('existing-id', 'visaCal-4825', 'credit_card', '2026-08-13', -210.00, "
        "'עמותת להושיט יד', 'visaCal')"
    )
    # a later sync recomputes a DIFFERENT trusted id for the same real transaction
    row = _row("2026-08-13", "-210.00", "עמותת להושיט יד",
               account_id="visaCal-4825", transaction_id="a-new-different-id")
    kept = assign_natural_ids([row], con)
    assert kept == []
