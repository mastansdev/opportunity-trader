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


def test_a_quarter_bigger_than_its_own_year_is_kept_and_labelled():
    """Fetched live from BSE on 30 August. Every column is internally
    consistent -- 376.96/7743.55 = 4.87% and 1.54/56.61 = 2.72%, both
    matching the NPM row BSE printed beside them -- and one quarter is
    twenty-five times the whole financial year next to it.

    Those cannot be the same company on the same basis. Storing them as
    one series produced the +13,579% that left COROMANDEL ungraded.

    The first fix DROPPED the payload. Labelling replaced it: nothing
    is thrown away, the bad comparison is still prevented, and the day
    a second quarter arrives on the same basis the pair grades by
    itself. See test_a_snapshot_with_two_bases_is_labelled_not_dropped.
    """
    rows = parse_results_snapshot(_COROMANDEL)
    assert len(rows) == 2
    assert {r["basis"] for r in rows} == {"main", "alt"}


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


# ------------------------------------------------ which set of books

def test_a_snapshot_with_two_bases_is_labelled_not_dropped():
    """---- WHICH SET OF BOOKS. 30 August 2026. ----

        "fix that basis column so those 8 grade properly"

    A company files STANDALONE and CONSOLIDATED accounts, and for a
    holding company they are wildly different numbers. No source says
    which it is serving.

    The payload's own full-year column decides it: a quarter sitting at
    a sane share of that year belongs to the year's books; one that
    does not belongs to a different set. Arithmetic on figures BSE
    printed together, not an opinion about the company.

    The first version DROPPED such a payload. Labelling is strictly
    better -- nothing is thrown away, the bad comparison is still
    prevented, and the day a second quarter arrives on the same basis
    the pair grades on its own.
    """
    rows = {r["period_label"]: r for r in parse_results_snapshot(_COROMANDEL)}
    assert rows["Mar-26"]["basis"] == "main"     # 56.61 of a 305.31 year
    assert rows["Jun-26"]["basis"] == "alt"      # 7,743.55 of the same year


def test_one_basis_throughout_is_all_main():
    clean = {"results_in_crores": {
        "fields": ["title", "Jun-26", "Mar-26", "FY25-26"],
        "data": [["Revenue", "130.00", "120.00", "480.00"]]}}
    assert {r["basis"] for r in parse_results_snapshot(clean)} == {"main"}


def test_no_year_column_means_the_basis_is_unknown():
    """Unknown is not "alt". With nothing to anchor on, the comparison
    falls back to matching on source, exactly as before."""
    two_only = {"results_in_crores": {
        "fields": ["title", "Jun-26", "Mar-26"],
        "data": [["Revenue", "130.00", "120.00"]]}}
    assert all(r["basis"] is None for r in parse_results_snapshot(two_only))


def test_two_bases_are_never_compared(tmp_path):
    """The whole point. COROMANDEL held Jun-26 on one basis and Mar-26
    on another, and the store compared them: +13,579% QoQ, no grade,
    and a number on screen that meant nothing."""
    import datetime

    from core.quarterly_results import QuarterlyResults

    store = QuarterlyResults(url="sqlite:///" + str(tmp_path / "q.db"))
    store.remember("TESTCO", datetime.date(2026, 3, 31), sales=56.61,
                   pat=1.54, period_label="Mar-26", basis="main",
                   source="bse", trusted=True)
    store.remember("TESTCO", datetime.date(2026, 6, 30), sales=7743.55,
                   pat=376.96, period_label="Jun-26", basis="alt",
                   source="bse", trusted=True)
    assert store.compare("TESTCO") is None, (
        "two sets of books were compared with each other")


def test_the_same_basis_still_compares(tmp_path):
    import datetime

    from core.quarterly_results import QuarterlyResults

    store = QuarterlyResults(url="sqlite:///" + str(tmp_path / "q.db"))
    store.remember("TESTCO", datetime.date(2026, 3, 31), sales=120.0,
                   pat=12.0, period_label="Mar-26", basis="main",
                   source="bse", trusted=True)
    store.remember("TESTCO", datetime.date(2026, 6, 30), sales=130.0,
                   pat=14.0, period_label="Jun-26", basis="main",
                   source="bse", trusted=True)
    got = store.compare("TESTCO")
    assert got is not None and got["qoq"]["sales"] is not None


def test_an_older_store_without_the_column_still_reads(tmp_path):
    """Rows written before today carry NULL, which reads as unknown and
    compares on source exactly as it always did."""
    import datetime

    from core.quarterly_results import QuarterlyResults

    store = QuarterlyResults(url="sqlite:///" + str(tmp_path / "q.db"))
    for end, label, sales in ((datetime.date(2026, 3, 31), "Mar-26", 120.0),
                              (datetime.date(2026, 6, 30), "Jun-26", 130.0)):
        store.remember("OLDCO", end, sales=sales, pat=sales / 10,
                       period_label=label, source="bse", trusted=True)
    got = store.compare("OLDCO")
    assert got is not None and got["qoq"]["sales"] is not None
