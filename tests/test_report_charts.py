"""Unit tests for report.py's chart inputs — synthetic months only, no database."""
from kaspion.insights import merchant_label
from kaspion.report import _destinations, _flag_months

CUR = "2026-08"


def _txn(day="2026-07-01", amount=100.0, cat="other", income=0, mkey="shop"):
    """A row shaped exactly like _collect() builds it (index order matters)."""
    return [day, day[8:] + "." + day[5:7], mkey, "אחר", amount, "🤖",
            "id", cat, "max", "max-1", income, mkey]


def _month(key, txns=None, spent=0.0, income=0.0):
    return {"key": key, "label": f"חודש {key}", "spent": spent, "budget": 0.0,
            "income": income, "cats": [], "txns": txns or []}


# --- merchant_label ---------------------------------------------------------------

def test_check_series_collapses_to_one_payee():
    keys = ["חיוב צק/17672/0050020/18 [צ׳קים]", "חיוב צק/17672/0050026/18 [צ׳קים]",
            "חיוב צק/17672/0050027/18 [צ׳קים]"]
    assert len({merchant_label(k) for k in keys}) == 1


def test_numbered_subscription_collapses_too():
    """The check regex is not the only reference family — this one has no צ׳קים in it."""
    a = merchant_label("דמי מנוי - 117-4413012/14932422/founderpluss [אחר]")
    b = merchant_label("דמי מנוי - 117-4092980/13025927/founderpluss [אחר]")
    assert a == b and "founderpluss" in a and "4413012" not in a


def test_real_merchant_is_never_rewritten():
    for k in ["שופרסל און ליין", 'ד"ר דוד שי מרגלית', "PAYBOX"]:
        assert merchant_label(k) == k


def test_label_never_ends_up_empty():
    assert merchant_label("") == "ללא שם"
    assert merchant_label("12/34/56") == "12/34/56"   # nothing left after stripping


# --- _flag_months -----------------------------------------------------------------

def test_flags_partial_first_month_and_future_month():
    ms = [_month("2026-05", [_txn("2026-05-07")]), _month("2026-06", [_txn("2026-06-01")]),
          _month(CUR, [_txn("2026-08-01")]), _month("2026-09", [_txn("2026-09-10")])]
    _flag_months(ms, CUR)
    assert [m["complete"] for m in ms] == [False, True, False, False]
    assert [m["isFuture"] for m in ms] == [False, False, False, True]
    assert [m["isCurrent"] for m in ms] == [False, False, True, False]
    assert [m["firstDay"] for m in ms] == [7, 1, 1, 10]


def test_quiet_mid_history_month_is_still_complete():
    """Only the FIRST month can be cut short by when data collection started."""
    ms = [_month("2026-05", [_txn("2026-05-01")]), _month("2026-06", [_txn("2026-06-28")])]
    _flag_months(ms, CUR)
    assert [m["complete"] for m in ms] == [True, True]


def test_empty_month_list_and_empty_txns_are_safe():
    _flag_months([], CUR)
    ms = [_month("2026-06")]
    _flag_months(ms, CUR)
    assert ms[0]["firstDay"] == 0 and ms[0]["complete"] is False


def test_saved_and_pace_still_computed():
    ms = [_month("2026-06", spent=100.0, income=250.0)]
    _flag_months(ms, CUR)
    assert ms[0]["saved"] == 150.0 and ms[0]["pace"] == -100.0


# --- _destinations ----------------------------------------------------------------

def test_destinations_collapse_check_series_into_one_bar():
    txns = [_txn(mkey=f"חיוב צק/17672/005002{i}/18 [צ׳קים]", amount=5600.0) for i in range(3)]
    out = _destinations([_month("2026-06", txns)], CUR)
    assert len(out) == 1
    assert out[0]["total"] == 16800.0
    assert len(out[0]["keys"]) == 3          # the drill-down needs every raw key


def test_destinations_exclude_income_and_negative_income_rows():
    """t[10] alone is not enough: a PAYBOX reversal is an outflow filed under 'income',
    which fct_budget_pacing leaves out of `spent`."""
    txns = [_txn(mkey="shop", amount=100.0),
            _txn(mkey="salary", amount=9000.0, cat="income", income=1),
            _txn(mkey="PAYBOX", amount=743.0, cat="income", income=0)]
    out = _destinations([_month("2026-06", txns)], CUR)
    assert [d["label"] for d in out] == ["shop"]


def test_destinations_skip_future_months():
    out = _destinations([_month("2026-06", [_txn(mkey="a", amount=10.0)]),
                         _month("2026-09", [_txn("2026-09-10", mkey="b", amount=999.0)])], CUR)
    assert [d["label"] for d in out] == ["a"]


def test_destinations_sorted_and_capped():
    txns = [_txn(mkey=f"m{i}", amount=float(i)) for i in range(1, 16)]
    out = _destinations([_month("2026-06", txns)], CUR, top=10)
    assert len(out) == 10
    assert out[0]["label"] == "m15"
    assert [d["total"] for d in out] == sorted((d["total"] for d in out), reverse=True)


def test_destinations_empty_history():
    assert _destinations([], CUR) == []
