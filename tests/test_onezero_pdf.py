"""The ONE ZERO PDF statement parser, and the guard that keeps it from re-importing
movements the .xls export already put in the database."""
from __future__ import annotations

import pytest

from kaspion.ingest.onezero_pdf import _description, parse_text
from kaspion.ingest.statements import detect_format

HEADING = "פירוט של תנועות שקליות בחשבון"


def statement(*lines: str) -> str:
    return "\n".join([HEADING, *lines])


def test_description_reads_bottom_up():
    # the extractor emits an RTL row's wrapped lines in reverse reading order
    assert _description(['ממופ"ת מילואים', "העברה"]) == 'העברה ממופ"ת מילואים'
    assert _description(["", "117-", "FounderPlusS", "דמי מנוי"]) == "דמי מנוי FounderPlusS 117-"


def test_detects_a_pdf_by_its_magic_bytes_not_its_name(tmp_path):
    path = tmp_path / "named-wrong.xlsx"
    path.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    assert detect_format(path) == "onezero_pdf"


def test_rejects_a_pdf_that_is_not_a_statement():
    with pytest.raises(ValueError, match="not a ONE ZERO statement"):
        parse_text("some other PDF entirely")


def test_parses_credits_debits_and_the_transaction_date():
    # balance, credits, debits, description…, value date, transaction date
    rows = parse_text(statement(
        "35,752.89 3,100 0 movement-a 01/06/2026 01/06/2026",
        "29,002.89 0 6,750 movement-b 01/06/2026 02/06/2026",
    ))
    assert [(r["posted_date"], r["amount"], r["raw_description"]) for r in rows] == [
        ("2026-06-01", 3100.0, "movement-a"),
        ("2026-06-02", -6750.0, "movement-b"),   # the LATER date posts, as in the .xls
    ]
    assert all(r["account_id"] == "onezero" and r["source"] == "onezero" for r in rows)


def test_joins_a_wrapped_description_back_into_reading_order():
    rows = parse_text(statement(
        '45,614.89 0 6.06 -מקס איט פיננסים',
        "חיוב מ 09/06/2026 09/06/2026",
    ))
    assert rows[0]["raw_description"] == 'חיוב מ -מקס איט פיננסים'


def test_skips_summary_lines_and_zero_amount_rows():
    rows = parse_text(statement(
        "32,652.89 יתרה קודמת",
        "35,752.89 0 0 nothing-moved 01/06/2026 01/06/2026",
        "35,752.89 100 0 real 01/06/2026 01/06/2026",
    ))
    assert [r["amount"] for r in rows] == [100.0]


def test_a_page_letterhead_does_not_swallow_the_first_movement():
    rows = parse_text(statement(
        "ONE ZERO Digital Bank LTD",
        "2/1 תאריך הערך",
        "35,752.89 3,100 0 first 01/06/2026 01/06/2026",
    ))
    assert [r["amount"] for r in rows] == [3100.0]


def test_a_statement_with_no_movements_is_an_error():
    with pytest.raises(ValueError, match="no movements"):
        parse_text(statement("32,652.89 יתרה קודמת"))


def test_known_rows_are_dropped_by_multiplicity_not_by_existence(monkeypatch, tmp_path):
    import duckdb

    from kaspion import db
    from kaspion.ingest import statements

    path = str(tmp_path / "t.duckdb")
    monkeypatch.setattr(statements, "connect", lambda: duckdb.connect(path))
    duckdb.connect(path).execute(db.DDL).execute(
        "INSERT INTO raw.transactions VALUES "
        "('x', 'onezero', 'bank', DATE '2026-06-11', -100, 'ILS', 'הוראת קבע', 'onezero', now())"
    ).close()

    # the export holds BOTH standing orders; the database holds one, so one is new
    rows = [{"account_id": "onezero", "posted_date": "2026-06-11", "amount": -100.0,
             "raw_description": f"PDF wording {i}"} for i in range(2)]
    assert len(statements.drop_known_by_date_and_amount(rows)) == 1

    # once both are held, re-importing the same export adds nothing
    duckdb.connect(path).execute(
        "INSERT INTO raw.transactions VALUES "
        "('y', 'onezero', 'bank', DATE '2026-06-11', -100, 'ILS', 'PDF wording 0', "
        "'onezero', now())"
    ).close()
    assert statements.drop_known_by_date_and_amount(rows) == []
