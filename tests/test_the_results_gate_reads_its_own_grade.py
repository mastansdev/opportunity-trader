"""It computed a grade and then threw an exception reading it.

    "fix those 8 stocks parsed sales figures"
                                    -- operator, 30 August 2026

Chasing those eight turned up something costlier than the eight.

    core/results_gate.ResultsGate.grade_for():
        qoq, yoy = self.quarterly.compare(symbol)

compare() returns a dict of EIGHT keys -- symbol, period, latest, qoq,
yoy, grade, summary, unreliable. Unpacking a dict yields its KEYS, so
this raised ValueError on every call, the bare except below swallowed
it, and the function returned None every single time it was asked.

Proved on the live store: compare("TCS") carries grade="WEAK" and
grade_for("TCS") answered None.

WHAT IT COST. block_reason() asks the PUBLISHED chip first, so a stock
carrying an EXCELLENT / GREAT / GOOD card from Earnings Pulse was
never affected. Everything else fell through to REASON_NO_GRADE --
"numbers not read yet" -- and was blocked on its results day, with the
numbers sitting in the store and a grade already computed off them.

Which is the fault of 5 August wearing different clothes: "the weaker
source silently vetoed the stronger one, and the refusal read like a
data problem rather than a decision". Last time the weaker source was
a second lookup. This time it was an exception.
"""

import pytest

from core.quarterly_results import parse_results_snapshot
from core.results_gate import ResultsGate


class _Store:
    """A quarterly store that answers the way the real one does."""

    def __init__(self, answer):
        self.answer = answer

    def compare(self, symbol):
        return self.answer


# ------------------------------------------------------ the grade is read

def test_the_grade_the_store_computed_is_the_one_returned():
    gate = ResultsGate(quarterly=_Store({
        "symbol": "TCS", "period": "Jun-26", "latest": {}, "qoq": {},
        "yoy": {}, "grade": "WEAK", "summary": "", "unreliable": None}))
    assert gate.grade_for("TCS") == "WEAK"


def test_an_unbelievable_set_of_figures_still_grades_nothing():
    """compare() already sets grade=None when its own guard fires, so
    reading its answer keeps that protection rather than bypassing it."""
    gate = ResultsGate(quarterly=_Store({
        "symbol": "COROMANDEL", "grade": None,
        "unreliable": "sales +13,579% QoQ -- beyond anything a real "
                      "quarter does"}))
    assert gate.grade_for("COROMANDEL") is None


def test_no_store_is_not_an_error():
    assert ResultsGate(quarterly=None).grade_for("TCS") is None


def test_a_store_that_raises_is_not_an_error():
    class Broken:
        def compare(self, symbol):
            raise RuntimeError("db gone")

    assert ResultsGate(quarterly=Broken()).grade_for("TCS") is None


def test_it_does_not_unpack_the_dict():
    """The regression itself. A two-name unpack of an eight-key dict
    reads as ordinary code and fails on every call."""
    import inspect

    src = inspect.getsource(ResultsGate.grade_for)
    # Code only. The comment above the fix quotes the broken line on
    # purpose, so scanning the raw source would fail on its own
    # explanation.
    code = "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))
    assert "qoq, yoy = " not in code


# ------------------------------- three columns that are not one series

_COROMANDEL = {
    "currency_unit": "in Cr.",
    "periods": ["Jun-26", "Mar-26", "FY25-26"],
    "results_in_crores": {
        "fields": ["title", "Jun-26", "Mar-26", "FY25-26"],
        "data": [["Revenue", "7,743.55", "56.61", "305.31"],
                 ["Net Profit", "376.96", "1.54", "20.09"],
                 ["EPS", "12.80", "5.24", "68.19"],
                 ["NPM %", "4.87", "2.73", "6.58"]]}}


def test_a_quarter_bigger_than_its_own_year_is_not_stored():
    """Fetched live from BSE on 30 August. Every column is internally
    consistent -- 376.96/7743.55 = 4.87% and 1.54/56.61 = 2.72%, both
    matching the NPM row BSE printed beside them -- and one quarter is
    twenty-five times the whole financial year next to it.

    Those cannot be the same company on the same basis. Storing them
    as one series produced the +13,579% that left COROMANDEL ungraded.
    """
    assert parse_results_snapshot(_COROMANDEL) == []


def test_nothing_is_kept_from_a_payload_that_fails():
    """Keeping the columns that happen to agree would leave the store
    holding a mixture, with no way to tell afterwards which basis any
    row came from."""
    got = parse_results_snapshot(_COROMANDEL)
    assert not any(r.get("period_label") == "Mar-26" for r in got)


def test_growth_is_not_mistaken_for_a_broken_payload():
    """The newest quarter belongs to the NEXT financial year, so
    exceeding the previous year's total is a business event. The test
    is loose on purpose -- COROMANDEL's was 25x."""
    growing = {
        "results_in_crores": {
            "fields": ["title", "Jun-26", "Mar-26", "FY25-26"],
            "data": [["Revenue", "130.00", "120.00", "400.00"],
                     ["Net Profit", "13.00", "12.00", "40.00"]]}}
    rows = parse_results_snapshot(growing)
    assert [r["period_label"] for r in rows] == ["Jun-26", "Mar-26"]


def test_a_payload_with_no_year_column_is_left_alone():
    """The check needs the full-year column to anchor on. Without one
    it must not start rejecting good data."""
    two_only = {
        "results_in_crores": {
            "fields": ["title", "Jun-26", "Mar-26"],
            "data": [["Revenue", "7,743.55", "56.61"]]}}
    assert len(parse_results_snapshot(two_only)) == 2


def test_the_threshold_is_stated_and_loose():
    from core.quarterly_results import QUARTER_OVER_YEAR

    assert 1.0 < QUARTER_OVER_YEAR <= 4.0
