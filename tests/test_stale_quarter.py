"""
==========================================================
A grade of LAST quarter must not answer for THIS one
==========================================================

31 July 2026, on the operator's own screen:

    APTUS  [GOOD]   score 13   0 backing
      FILED RESULTS 591m ago
      REPORTING TODAY
      GOOD: PAT +10% QoQ
      CROWDED 7x -- likely already priced
      PULSE: Weak results
      AI +: Q1 net profit grew 18% YoY (2.6B vs 2.2B)

    ... and APTUS closed at -5.77%.

    "to be frank i could have bought this by seeing Good & AI - 18%
     yoy. but weak results from PULSE"

WHAT WAS ACTUALLY WRONG
-----------------------
The GOOD was real arithmetic. On the MARCH quarter.

    stored period : Mar-26, read 27 July, compared against Dec-25
    today's Q1    : Jun-26, PAT 261 vs 261 flat, provisions +103% YoY

Today's filing had never been ingested. A three-month-old grade sat
beside "REPORTING TODAY" with nothing on it saying which quarter it
described.

And it did worse than mislead. The old rule was:

    already = bool(fin and grade)      # we graded it, ignore the channel

so the stale GOOD scored +3.0 AND silenced the fresh WEAK's -2.5. A
5.5 point swing the wrong way, on the one row where the channel was
right and we were out of date.

THE TWO RULES
-------------
1. Every grade chip names its quarter, always -- not only when stale.
   A label that appears only when something is wrong is a label nobody
   learns to read.
2. Arithmetic that has never seen today's result cannot claim to have
   counted it.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date

import pytest

from core.shortlist import ShortlistBuilder


class Events:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=None, hours=None, scope=None):
        return self.rows


class Fin:
    """Our own filed-numbers store, pinned to one quarter."""

    def __init__(self, period_label, period_end, grade="GOOD",
                 summary="PAT +10% QoQ"):
        self.period_label = period_label
        self.period_end = period_end
        self.grade = grade
        self.summary = summary

    def compare(self, symbol):
        return {"symbol": symbol, "period": self.period_label,
                "grade": self.grade, "summary": self.summary,
                "latest": {"period_end": self.period_end},
                "qoq": {"pat": 10.4}, "yoy": None}


PULSE_WEAK_TODAY = [{"symbol": "APTUS", "kind": "RESULT", "grade": "WEAK",
                     "at": "2026-07-31T07:52:13"}]

# What our store actually held: the March quarter, read on 27 July.
STALE = Fin("Mar-26", date(2026, 3, 31))
# What it would hold once today's filing is ingested.
FRESH = Fin("Jun-26", date(2026, 6, 30))


def _rank(fin, events, today="2026-07-31"):
    builder = ShortlistBuilder(stock_events=Events(events),
                               quarterly_results=fin)
    out = builder.rank([{"symbol": "APTUS", "ltp": 261.2,
                         "change_pct": 3.0, "sector": "Financial Services"}],
                       top=5, today=today)
    rows = out.get("rows") or []
    return rows[0] if rows else None


# ---------------------------------------------------------------
# 1. THE CHIP NAMES ITS QUARTER
# ---------------------------------------------------------------
def test_the_grade_chip_says_which_quarter_it_is_about():
    got = _rank(STALE, [])
    # "OUR NUMBERS: GOOD (Mar-26)" -- the prefix went on 2 August, when
    # the operator read our arithmetic as a channel verdict. The quarter
    # label this test guards is unchanged.
    chip = next(w for w in got["why"] if w.startswith("OUR NUMBERS: GOOD"))
    assert "Mar-26" in chip, (
        f"a grade beside 'REPORTING TODAY' must say which quarter it "
        f"describes, got {chip!r}")


def test_a_current_quarter_is_labelled_too():
    """Always, not only when stale. A label that only appears when
    something is wrong is a label nobody learns to read."""
    got = _rank(FRESH, [])
    # "OUR NUMBERS: GOOD (Mar-26)" -- the prefix went on 2 August, when
    # the operator read our arithmetic as a channel verdict. The quarter
    # label this test guards is unchanged.
    chip = next(w for w in got["why"] if w.startswith("OUR NUMBERS: GOOD"))
    assert "Jun-26" in chip


# ---------------------------------------------------------------
# 2. STALE ARITHMETIC MUST NOT SILENCE A FRESH VERDICT
# ---------------------------------------------------------------
def test_a_stale_grade_does_not_suppress_todays_pulse_verdict():
    """The APTUS incident, exactly. Our Mar-26 GOOD must not swallow
    Earnings Pulse's WEAK on the Jun-26 filing."""
    got = _rank(STALE, PULSE_WEAK_TODAY)
    assert any("PULSE: Weak" in w for w in got["why"]), got["why"]


def test_a_stale_grade_costs_the_score_the_fresh_warning():
    """The 5.5 point swing. With the old rule the WEAK scored nothing;
    it must now push the score DOWN."""
    silenced = _rank(STALE, [])                    # no channel verdict
    with_warning = _rank(STALE, PULSE_WEAK_TODAY)
    assert with_warning["score"] < silenced["score"], (
        "a fresh WEAK verdict must reduce the score even when we hold "
        "an older GOOD")


def test_the_fresh_warning_is_counted_as_pushing_back():
    got = _rank(STALE, PULSE_WEAK_TODAY)
    assert got["against"] >= 1


# ---------------------------------------------------------------
# 3. AND THE DOUBLE-COUNT GUARD MUST STILL WORK
# ---------------------------------------------------------------
def test_a_grade_of_the_same_quarter_still_counts_only_once():
    """The original rule was right for the case it was written for.
    Our Jun-26 arithmetic and a Jun-26 Pulse verdict are the same
    result read twice; scoring both would double it."""
    pulse_same_quarter = [{"symbol": "APTUS", "kind": "RESULT",
                           "grade": "GOOD", "at": "2026-06-29T10:00:00"}]
    both = _rank(FRESH, pulse_same_quarter)
    arithmetic_only = _rank(FRESH, [])
    assert both["score"] == arithmetic_only["score"]


def test_the_pulse_chip_is_shown_either_way():
    """Shown always, scored conditionally -- that distinction is what
    the 31 July fix was about in the first place."""
    pulse_same_quarter = [{"symbol": "APTUS", "kind": "RESULT",
                           "grade": "GOOD", "at": "2026-06-29T10:00:00"}]
    got = _rank(FRESH, pulse_same_quarter)
    assert any("PULSE" in w for w in got["why"])


# ---------------------------------------------------------------
# 4. UNREADABLE DATES FAIL TOWARDS THE WARNING
# ---------------------------------------------------------------
@pytest.mark.parametrize("bad_end", [None, "", "not-a-date", 0])
def test_an_unreadable_period_is_treated_as_stale(bad_end):
    """Wrong in this direction means one extra signal is counted.
    Wrong in the other direction silences a fresh warning, which is
    the failure being fixed."""
    fin = Fin("???", bad_end)
    got = _rank(fin, PULSE_WEAK_TODAY)
    assert any("PULSE: Weak" in w for w in got["why"])
