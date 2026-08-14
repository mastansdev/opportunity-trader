"""
==========================================================
Bajaj Finance did not do twelve crore of sales
==========================================================

1 August 2026. 200 results PDFs were fetched using the filing links
Earnings Pulse had been publishing all along. 92 parsed, 108 failed --
and the 108 were the SAFE half.

An audit of the whole store found 21 rows in 1,699 where the stored
sales figure disagrees with the company's OWN history by twenty times
or more:

    WESTLIFE    Jun-25   sales  9,650.00   own median      1.00
    TORNTPHARM  Mar-26   sales      1.00   own median  2,599.00
    BAJFINANCE  Jun-26   sales     12.00   own median  8,308.97
    REDINGTON   Jun-26   sales     19.59   own median  6,400.64
    VEDL        Jun-25   sales     24.61   own median 15,754.00

Nineteen came from the PDF parser reading the wrong column of a
results table. Two came from BSE's own snapshot. Three are the CURRENT
quarter.

WHY THIS IS WORSE THAN THE 108 THAT FAILED
------------------------------------------
A missing quarter leaves the panel labelled with the older quarter's
name -- "GOOD (Mar-26)" -- and the operator can see that it is stale.

A wrong one produces a confident grade off arithmetic that is
nonsense, and nothing on screen says so. This is the same failure as
reading a filing's columns out of alignment, and the same failure as
grading APTUS STRONG on a day it fell 5.77%.

THE TEST IS THE COMPANY AGAINST ITSELF
--------------------------------------
There is no absolute rupee figure that is right for both Reliance and
a small-cap, and inventing one would refuse real quarters. So the
guard compares a new figure against the median of what that same
company has already reported.

TWENTY TIMES IS DELIBERATELY LOOSE. A genuine doubling passes. A
merger passes. A fourfold jump on a new plant passes. The real cases
were 37x to 9,650x -- this class of error is never subtle.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.quarterly_results import QuarterlyResults


@pytest.fixture
def store(tmp_path):
    """A company with four honest quarters around Rs 8,000 crore."""
    store = QuarterlyResults(url=f"sqlite:///{tmp_path}/q.db")
    from datetime import date
    for month, day, sales in ((6, 30, 8200.0), (3, 31, 8400.0),
                              (12, 31, 8100.0), (9, 30, 8500.0)):
        year = 2025 if month in (12, 9) else 2026
        store.remember("BAJFINANCE", date(year, month, day), sales=sales,
                       pat=400.0, source="test")
    return store


# ---------------------------------------------------------------
# 1. THE MISREADS ARE REFUSED
# ---------------------------------------------------------------
@pytest.mark.parametrize("sales,name", [
    (12.00, "the real BAJFINANCE Jun-26 misread"),
    (1.00, "a TORNTPHARM-shaped decimal error"),
    (19.59, "a REDINGTON-shaped column error"),
    (900000.0, "the same error in the other direction"),
])
def test_a_figure_that_cannot_be_this_company_is_refused(store, sales, name):
    from datetime import date
    got = store.remember("BAJFINANCE", date(2026, 6, 30), sales=sales,
                         source="filing_pdf")
    assert got == "unchanged", name
    # and the honest quarter is still there
    assert store.latest("BAJFINANCE")["sales"] == 8200.0


def test_the_refusal_explains_itself(store):
    why = store._implausible("BAJFINANCE", 12.0)
    assert why and "own median" in why
    assert "misread" in why


# ---------------------------------------------------------------
# 2. REAL BUSINESS CHANGE MUST SURVIVE
# ---------------------------------------------------------------
@pytest.mark.parametrize("sales,name", [
    (8300.0, "an ordinary quarter"),
    (16600.0, "a genuine doubling"),
    (4100.0, "a genuine halving"),
    (33000.0, "a fourfold jump on a new plant"),
    (2100.0, "a collapse to a quarter of normal"),
])
def test_a_real_change_however_large_is_stored(store, sales, name):
    from datetime import date
    assert store._implausible("BAJFINANCE", sales) is None, name
    got = store.remember("BAJFINANCE", date(2026, 9, 30), sales=sales,
                         source="filing_pdf")
    assert got == "new", name


def test_the_threshold_is_loose_on_purpose():
    """Tight enough to catch a decimal place, loose enough that no
    real quarter is ever refused."""
    assert QuarterlyResults.SALES_SANITY_RATIO >= 10.0


# ---------------------------------------------------------------
# 3. IT NEVER BLOCKS A COMPANY IT CANNOT JUDGE
# ---------------------------------------------------------------
def test_a_company_with_no_history_is_never_refused(tmp_path):
    """Refusing on two data points would block every newly covered
    stock, which is a bigger hole than the one being closed."""
    from datetime import date
    store = QuarterlyResults(url=f"sqlite:///{tmp_path}/n.db")
    assert store.remember("BRANDNEW", date(2026, 6, 30), sales=1234.5,
                          source="filing_pdf") == "new"


def test_two_quarters_is_still_not_enough_history(tmp_path):
    from datetime import date
    store = QuarterlyResults(url=f"sqlite:///{tmp_path}/t.db")
    store.remember("PAIR", date(2026, 3, 31), sales=5000.0, source="test")
    store.remember("PAIR", date(2025, 12, 31), sales=5000.0, source="test")
    assert store._implausible("PAIR", 1.0) is None
    assert QuarterlyResults.SALES_SANITY_MIN_HISTORY >= 3


@pytest.mark.parametrize("value", [None, 0, "not a number"])
def test_a_missing_or_odd_sales_figure_does_not_raise(store, value):
    got = store._implausible("BAJFINANCE", value)
    assert got is None or isinstance(got, str)


def test_a_negative_sales_figure_is_refused(store):
    assert "negative" in (store._implausible("BAJFINANCE", -500.0) or "")


# ---------------------------------------------------------------
# 4. A ROW IS REMOVED, NEVER EDITED
# ---------------------------------------------------------------
def test_the_purge_tool_deletes_rather_than_corrects():
    """Editing a figure we could not read would be inventing one. The
    row goes, and the store falls back to the previous quarter -- the
    state the panel labels honestly."""
    src = open("tools/purge_bad_quarters.py", encoding="utf-8").read()
    assert "DELETE FROM quarterly_results" in src
    assert "UPDATE quarterly_results" not in src


def test_the_purge_tool_needs_apply_to_touch_anything():
    src = open("tools/purge_bad_quarters.py", encoding="utf-8").read()
    assert 'main(apply="--apply" in sys.argv)' in src
    assert "DRY RUN" in src


def test_the_purge_tool_uses_the_same_threshold_as_the_guard():
    """Two numbers that must agree, imported rather than repeated --
    otherwise the tool cleans to one standard and the store admits to
    another."""
    src = open("tools/purge_bad_quarters.py", encoding="utf-8").read()
    assert "QuarterlyResults.SALES_SANITY_RATIO" in src
    assert "QuarterlyResults.SALES_SANITY_MIN_HISTORY" in src
