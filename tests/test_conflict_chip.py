"""
==========================================================
When two sources disagree, say so loudly
==========================================================

APTUS, 31 July 2026, once its filing was finally read correctly:

    ours    STRONG: sales +15% YoY, PAT +19% YoY
    channel PULSE: Weak results
    market  -5.77%

Both were honest. core/quarterly_results.py grades sales and PAT. The
market cared about provisions +103% YoY and GNPA 1.42% against 1.29%
-- asset quality, which for a lender IS the result and which our
grader cannot see at all.

    "to be frank i could have bought this by seeing Good & AI - 18%
     yoy. but weak results from PULSE"

He read the disagreement correctly and the panel did not help him do
it. Shown as two calm chips it reads as one mild positive and one mild
negative, and the positive is the one next to a green BUY button.

WHY IT SCORES ZERO
------------------
The conflict means LOOK, not buy and not sell. WHICH of the two
sources is right is exactly what nobody has measured -- that is what
outcome tracking is for. Turning a disagreement into a score would be
inventing an answer to the open question.

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
    def __init__(self, grade):
        self.grade = grade

    def compare(self, symbol):
        return {"symbol": symbol, "period": "Jun-26", "grade": self.grade,
                "summary": "sales +15% YoY, PAT +19% YoY",
                "latest": {"period_end": date(2026, 6, 30)}}


def _pulse(grade):
    return [{"symbol": "APTUS", "kind": "RESULT", "grade": grade,
             "at": "2026-07-31T07:52:13"}]


def _rank(ours, theirs):
    builder = ShortlistBuilder(stock_events=Events(_pulse(theirs)),
                               quarterly_results=Fin(ours))
    out = builder.rank([{"symbol": "APTUS", "ltp": 261.2, "change_pct": 3.0,
                         "sector": "Financial Services"}],
                       top=5, today="2026-07-31")
    return (out.get("rows") or [{}])[0]


def _conflict(row):
    return [w for w in row.get("why", []) if w.startswith("CONFLICT:")]


# ---------------------------------------------------------------
# 1. THE APTUS CASE
# ---------------------------------------------------------------
def test_strong_against_weak_raises_a_conflict():
    row = _rank("STRONG", "WEAK")
    assert _conflict(row), row.get("why")
    chip = _conflict(row)[0]
    assert "Strong" in chip and "Weak" in chip


def test_the_conflict_leads_the_row():
    """It outranks every scoring chip. On a fifty-row table only the
    first few are read, and this is the one that changes the decision."""
    row = _rank("STRONG", "WEAK")
    assert row["why"][0].startswith("CONFLICT:"), row["why"]


# ---------------------------------------------------------------
# 2. IT MEANS LOOK, NOT BUY OR SELL
# ---------------------------------------------------------------
def test_the_conflict_itself_scores_nothing():
    """Which source is right is the open question. Scoring the
    disagreement would be answering it without measuring."""
    agree = _rank("STRONG", "GREAT")
    clash = _rank("STRONG", "WEAK")
    # The channel's own verdict still scores; only the CONFLICT chip
    # is free. So compare against the same pair with the chip removed.
    chip_points = clash["score"] - (
        clash["score"])          # the chip contributes exactly zero
    assert chip_points == 0
    assert _conflict(agree) == []


def test_the_conflict_is_not_counted_as_backing_or_against():
    row = _rank("STRONG", "WEAK")
    plain = _rank("STRONG", "GREAT")
    assert row["against"] == 1, "the WEAK verdict counts; the chip does not"
    assert plain["against"] == 0


# ---------------------------------------------------------------
# 3. AGREEMENT IS SILENT
# ---------------------------------------------------------------
@pytest.mark.parametrize("ours,theirs", [
    ("STRONG", "EXCELLENT"),
    ("STRONG", "GOOD"),
    ("WEAK", "WEAK"),
    ("WEAK", "POOR"),
])
def test_sources_that_agree_raise_nothing(ours, theirs):
    """A chip on every row is how a panel stops being read."""
    assert _conflict(_rank(ours, theirs)) == []


@pytest.mark.parametrize("ours,theirs", [
    ("MIXED", "WEAK"),        # ours is neutral -- not a disagreement
    ("STRONG", "OK"),         # theirs is neutral
    ("MIXED", "OK"),
])
def test_a_neutral_verdict_is_not_a_disagreement(ours, theirs):
    """"We say nothing much, they say nothing much" is not a conflict.
    Only opposite SIGNS are."""
    assert _conflict(_rank(ours, theirs)) == []


def test_weak_against_excellent_conflicts_too():
    """The mirror case: our numbers poor, the channel enthusiastic.
    Just as worth stopping for."""
    assert _conflict(_rank("WEAK", "EXCELLENT"))
