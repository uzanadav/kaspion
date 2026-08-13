"""Unit tests for kaspion.insights — synthetic months only, no database, no network."""
from kaspion.insights import MIN_TXNS, build_insights

CUR = "2026-08"


def _txn(amount=100.0, merchant="shop", emoji="🤖", income=0):
    """A row shaped exactly like report.py builds it (index order matters)."""
    return ["2026-07-01", "01.07", merchant, "אחר", amount, emoji,
            "id", "other", "max", "max-1", income, merchant]


def _month(key, spent=0.0, income=0.0, cats=None, txns=None, n_txns=MIN_TXNS):
    return {"key": key, "label": f"חודש {key}", "spent": spent, "budget": 0.0,
            "toDate": 0.0, "income": income, "cats": cats or [],
            "txns": txns if txns is not None else [_txn() for _ in range(n_txns)],
            "isCurrent": key == CUR, "pace": 0.0, "saved": round(income - spent, 2)}


def _kinds(out):
    return {i["kind"] for i in out}


def test_no_history_says_nothing():
    assert build_insights([_month("2026-08", spent=100)], CUR) == []


def test_empty_months_is_safe():
    assert build_insights([], CUR) == []


def test_current_month_is_never_a_record():
    """August is mid-month and has the highest income — it must not win a record."""
    months = [_month("2026-05", spent=100, income=1000),
              _month("2026-06", spent=100, income=2000),
              _month("2026-07", spent=100, income=3000),
              _month(CUR, spent=50, income=99999)]
    rec = [i for i in build_insights(months, CUR, limit=9) if i["kind"] == "income_record"]
    assert rec and "99,999" not in rec[0]["text"]


def test_zero_income_month_cannot_hold_a_record():
    """income == 0 means data was never loaded, not that nothing was earned."""
    months = [_month("2026-05", income=0), _month("2026-06", income=2000),
              _month("2026-07", income=3000), _month(CUR)]
    assert "income_record" not in _kinds(build_insights(months, CUR, limit=9))


def test_future_month_is_not_a_low_spend_month():
    """Statements carry future-dated installments; one such row is not a real month."""
    months = [_month("2026-06", spent=20000, income=2000),
              _month("2026-07", spent=21000, income=2000),
              _month(CUR, spent=100),
              _month("2026-09", spent=291, txns=[_txn()])]
    for i in build_insights(months, CUR, limit=9):
        assert "291" not in i["text"]


def test_stub_month_is_excluded():
    thin = _month("2026-06", spent=9999, income=5000, n_txns=MIN_TXNS - 1)
    months = [thin, _month("2026-07", spent=100, income=100), _month(CUR)]
    for i in build_insights(months, CUR, limit=9):
        assert "9,999" not in i["text"]


def test_partial_month_only_reports_an_overshoot():
    """Spend only grows: 'already more' is safe, 'less than' is not yet knowable."""
    base = [_month("2026-06", spent=1000, income=5000),
            _month("2026-07", spent=1000, income=5000)]
    under = build_insights(base + [_month(CUR, spent=200)], CUR, limit=9)
    assert not [i for i in under if i["kind"] == "mom_totals" and "כבר" in i["text"]]
    over = build_insights(base + [_month(CUR, spent=5000)], CUR, limit=9)
    assert [i for i in over if i["kind"] == "mom_totals" and "כבר" in i["text"]]


def test_noise_floor_suppresses_trivial_moves():
    """A ₪5 -> ₪20 category must not shout '+300%'."""
    cats = lambda v: [{"id": "c", "name": "זוטות", "actual": v,
                       "budget": 0, "status": "no_budget", "suggested": False}]
    months = [_month("2026-05", cats=cats(5)), _month("2026-06", cats=cats(5)),
              _month("2026-07", cats=cats(20)), _month(CUR)]
    assert "category_move" not in _kinds(build_insights(months, CUR, limit=9))


def test_recurring_needs_a_stable_amount():
    """Same merchant twice at wildly different amounts is a visit, not a subscription."""
    def m(key, amounts):
        return _month(key, txns=[_txn(amount=a, merchant=f"sub{i}")
                                 for i, a in enumerate(amounts)])
    stable = [m("2026-06", [100, 100, 100]), m("2026-07", [100, 100, 100]), _month(CUR)]
    assert "recurring" in _kinds(build_insights(stable, CUR, limit=9))
    erratic = [m("2026-06", [100, 100, 100]), m("2026-07", [900, 900, 900]), _month(CUR)]
    assert "recurring" not in _kinds(build_insights(erratic, CUR, limit=9))


def test_check_payments_are_not_merchants():
    """Real data caught this: 'חיוב צק/17672/0050027/18' is a check reference number, not
    a merchant name, and a new one is issued for every payment. Without a filter every
    check looked like a brand-new business, and a run of them (kindergarten paid this way
    every month) never grouped together as the same recurring payee."""
    def checks(key, n):
        return _month(key, txns=[_txn(amount=3100, merchant=f"חיוב צק/17672/00500{i}/18 [צ׳קים]")
                                 for i in range(n)])
    months = [checks("2026-06", 1), checks("2026-07", 1),
              _month(CUR, txns=[_txn(amount=3100, merchant="חיוב צק/17672/0050099/18 [צ׳קים]")])]
    out = build_insights(months, CUR, limit=9)
    assert "new_merchant" not in _kinds(out)
    assert "recurring" not in _kinds(out)   # each check has a unique key, so it can't group either
    for i in out:
        assert "צק" not in i["text"]


def test_figures_in_text_are_the_computed_ones():
    """The whole point: the number in the sentence must be the number that was computed."""
    months = [_month("2026-05", spent=100, income=1000),
              _month("2026-06", spent=100, income=2000),
              _month("2026-07", spent=100, income=7654),
              _month(CUR)]
    rec = [i for i in build_insights(months, CUR, limit=9) if i["kind"] == "income_record"]
    assert rec and "7,654" in rec[0]["text"]


def test_limit_and_one_per_kind():
    months = [_month("2026-05", spent=5000, income=9000),
              _month("2026-06", spent=6000, income=9000),
              _month("2026-07", spent=9000, income=9000),
              _month(CUR, spent=20000, income=9000)]
    out = build_insights(months, CUR, limit=3)
    assert len(out) <= 3
    assert len(_kinds(out)) == len(out)
    assert out == sorted(out, key=lambda i: -i["score"])


def test_every_insight_links_somewhere_real():
    """A click must land on a known view and a month that actually exists."""
    months = [_month("2026-05", spent=5000, income=9000),
              _month("2026-06", spent=6000, income=9000),
              _month("2026-07", spent=9000, income=9000),
              _month(CUR, spent=20000, income=9000)]
    out = build_insights(months, CUR, limit=9)
    assert out
    keys = {m["key"] for m in months}
    for i in out:
        assert i["link"]["view"] in {"txns", "cats", "trends"}
        assert i["link"].get("month", CUR) in keys


def test_recurring_link_lists_exactly_the_merchants_it_counted():
    """The headline count and the drill-down must agree, or the click disproves the claim."""
    def m(key, n):
        return _month(key, txns=[_txn(amount=100, merchant=f"sub{i}") for i in range(n)])
    months = [m("2026-06", 4), m("2026-07", 4), _month(CUR)]
    rec = [i for i in build_insights(months, CUR, limit=9) if i["kind"] == "recurring"][0]
    assert rec["text"].startswith("4 ")
    assert set(rec["link"]["merchants"]) == {f"sub{i}" for i in range(4)}


def test_category_move_link_points_at_what_it_describes():
    cats = lambda v: [{"id": "c", "name": "דיור", "actual": v,
                       "budget": 0, "status": "no_budget", "suggested": False}]
    months = [_month("2026-05", cats=cats(200)), _month("2026-06", cats=cats(200)),
              _month("2026-07", cats=cats(2000)), _month(CUR)]
    mv = [i for i in build_insights(months, CUR, limit=9) if i["kind"] == "category_move"][0]
    assert mv["link"] == {"view": "txns", "month": "2026-07", "cat": "דיור"}


def test_uncategorized_link_filters_to_unclassified_rows():
    cur = _month(CUR, txns=[_txn(emoji="❔") for _ in range(6)])
    unc = [i for i in build_insights([_month("2026-07"), cur], CUR, limit=9)
           if i["kind"] == "uncategorized"][0]
    assert unc["link"]["uncat"] is True and unc["link"]["month"] == CUR
