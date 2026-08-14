"""
==========================================================
How much backs this move, and does the weekend exist?
==========================================================

Two complaints from 31 July 2026, both about the Why column.

ONE -- the panel showed one of two things and would not say which
-------------------------------------------------------------------
    "for some stocks chip is showing these & for some PULSE: Excellent
     results . ; instead keep both chips"

The Pulse verdict was hidden whenever our own arithmetic had already
graded the same quarter. The reasoning was sound -- one result must
not score twice -- but it was applied to the CHIP as well as the
score, so the operator saw a different kind of evidence depending on
which source happened to have arrived, with no way to tell whether the
other was absent or merely suppressed.

Two independent sources agreeing is the strongest thing this panel can
say. Now both show; only one scores.

    "more supports = more chips = clumsy in table ,. to resolve this
     u find a solution"

Also true, and it pulls the other way. So every chip now carries the
points it contributed, which makes two things possible that were not
before: a countable number of reasons backing the move, and an order
that puts the strongest first instead of whatever order the code
happened to build them in.

TWO -- the weekend did not exist
--------------------------------
    "real gap as far i concerned about after my terminal(laptop) close
     to next opening. & weekends data?"

Friday close to Monday open is 65.5 hours. The event memory was read
back 36. Events are never pruned, so Friday's excellent result was
sitting in the database on Monday morning and nothing looked at it --
the stock would open near the top of the gainers with no reason beside
it, which is the exact failure this column exists to prevent.

Measured on the real channels: 34% of all messages arrive OUTSIDE
market hours.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.shortlist import ShortlistBuilder, _age_suffix


class Events:
    """Stands in for core/stock_events.py."""

    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=None, hours=None, scope=None):
        self.asked_hours = hours
        return self.rows


class Fin:
    """Our own arithmetic off the filing, for the double-count case."""

    def compare(self, symbol):
        return {"grade": "STRONG", "summary": "sales +7% QoQ, PAT +51% QoQ",
                "period": "Q1", "qoq": 7, "yoy": 51}


# ---- A TEST MUST NOT READ TONIGHT'S NSE DATA. 2 August 2026. ----
#
# This fixture used the real symbol YASHO, and ShortlistBuilder loads
# data/results_calendar.db from disk -- it is not stubbed anywhere.
# Tonight's calendar refresh added YASHO's 31 July result, three days
# before this file's fixed today="2026-08-03", so a "results out 3d
# ago" chip appeared and the backing count went from 1 to 2.
#
# Nothing was broken. The test was reading production data that
# changes every night, which is not a test -- it is a tripwire that
# fires on the wrong thing.
#
# ZZFIXTURE cannot appear in an NSE announcement.
def _row(symbol="ZZFIXTURE", move=6.1):
    return {"symbol": symbol, "ltp": 420.0, "change_pct": move,
            "sector": "Chemicals"}


def _rank(builder, today="2026-08-03", move=6.1):
    out = builder.rank([_row(move=move)], top=5, today=today)
    rows = out.get("rows") or []
    return rows[0] if rows else None


PULSE = [{"symbol": "ZZFIXTURE", "kind": "RESULT", "grade": "EXCELLENT",
          "at": "2026-07-31T14:20:00"}]
ORDER = [{"symbol": "ZZFIXTURE", "kind": "ORDER", "value_cr": 640.0,
          "counterparty": "BigBasket", "at": "2026-07-31T14:25:00"}]


# ---------------------------------------------------------------
# 1. BOTH CHIPS, ONE SCORE
# ---------------------------------------------------------------
def test_both_the_arithmetic_and_the_pulse_verdict_are_shown():
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE),
                                 quarterly_results=Fin()))
    text = " | ".join(got["why"])
    # "OUR NUMBERS: STRONG (Q1) -- ..." The quarter came from the APTUS
    # incident (tests/test_stale_quarter.py); the OUR NUMBERS prefix came
    # from 2 August, when the operator asked what the STRONG/MIXED/WEAK
    # chip beside the symbol was and the answer was "us, not a channel".
    # Both halves of this assertion still matter: our arithmetic and the
    # publisher's verdict are two sources and both must be visible.
    assert "OUR NUMBERS: STRONG (Q1) -- sales +7% QoQ" in text, \
        "our own numbers must show, and must say they are ours"
    assert "PULSE: Excellent results" in text, (
        "the channel's verdict must show TOO -- it is a second, "
        "independent source and hiding it left the operator unable to "
        "tell absence from suppression")


def test_the_same_quarter_is_not_scored_twice():
    """The reason the chip was hidden in the first place. Suppressing
    the CHIP was the wrong fix for a SCORE problem."""
    both = _rank(ShortlistBuilder(stock_events=Events(PULSE),
                                  quarterly_results=Fin()))
    arithmetic_only = _rank(ShortlistBuilder(quarterly_results=Fin()))
    assert both["score"] == arithmetic_only["score"], (
        "showing the Pulse chip must not add points on top of the "
        "filed numbers")


def test_the_pulse_verdict_scores_when_it_is_the_only_source():
    """It is the EARLY signal -- it arrives while the filing is still
    being parsed. It must still be worth something on its own."""
    alone = _rank(ShortlistBuilder(stock_events=Events(PULSE)))
    assert alone["support"] >= 1
    assert any("PULSE" in w for w in alone["why"])


# ---------------------------------------------------------------
# 2. THE BACKING COUNT
# ---------------------------------------------------------------
def test_more_evidence_means_a_higher_backing_count():
    one = _rank(ShortlistBuilder(stock_events=Events(PULSE)))
    two = _rank(ShortlistBuilder(stock_events=Events(PULSE + ORDER)))
    assert two["support"] > one["support"]


def test_the_price_move_is_not_counted_as_evidence():
    """It is WHAT is being explained. Counting it would mean every row
    had at least one reason and the number said nothing."""
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE)), move=12.0)
    assert got["support"] == 1, "only the Pulse verdict backs this"
    assert any(w.startswith("up ") for w in got["why"])


def test_a_reason_pushing_the_other_way_is_counted_separately():
    head = {"kind": "BROKER",
            "headline": "UBS issues 'sell' tag on the stock"}

    class News:
        def for_symbol(self, s):
            return head

    got = _rank(ShortlistBuilder(stock_events=Events(PULSE),
                                 news_watcher=News()))
    assert got["against"] >= 1, (
        "a downgrade must be counted as pushing back, not quietly "
        "dropped from the tally")


# ---------------------------------------------------------------
# 3. STRONGEST FIRST
# ---------------------------------------------------------------
BIG_ORDER = [{"symbol": "ZZFIXTURE", "kind": "ORDER", "value_cr": 2205.0,
              "counterparty": "HAL", "at": "2026-07-31T14:25:00"}]


def test_the_biggest_reason_leads():
    """A Rs 2,205cr order is the top band (5.0); an EXCELLENT Pulse
    verdict is 4.0. The order leads.

    Note a Rs 640cr order does NOT lead -- it is worth 4.0, the same as
    the Pulse verdict, and on a tie the sort is stable so they keep the
    order the code built them in. That is deliberate: chips that
    reshuffle between refreshes on a table the operator is clicking BUY
    in are a hazard of their own.
    """
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE + BIG_ORDER)))
    assert got["why"][0].startswith("ORDER WIN"), (
        f"a Rs 2,205cr order must outrank a one-word verdict, got "
        f"{got['why'][0]!r}")


def test_equal_weight_reasons_do_not_reshuffle():
    builder = ShortlistBuilder(stock_events=Events(PULSE + ORDER))
    first = _rank(builder)["why"]
    for _ in range(5):
        builder._events_cache = None
        assert _rank(builder)["why"] == first


def test_the_price_move_sorts_last():
    """It is already printed in its own column two cells to the left.
    On the first attempt it took an inline slot and pushed the Pulse
    verdict behind the '+2'."""
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE + ORDER)))
    assert got["why"][-1].startswith("up "), (
        f"the move must come last, got {got['why']!r}")


def test_a_warning_outranks_background_noise():
    """"CROWDED 30x -- likely already priced" scores nothing and is the
    one chip arguing against acting."""
    got = ShortlistBuilder(stock_events=Events(PULSE)).rank(
        [dict(_row(), volume=9_000_000)], top=5, today="2026-08-03")
    why = (got["rows"] or [{}])[0].get("why", [])
    crowded = [i for i, w in enumerate(why) if w.startswith("CROWDED")]
    move = [i for i, w in enumerate(why) if w.startswith("up ")]
    if crowded and move:
        assert crowded[0] < move[0]


# ---------------------------------------------------------------
# 4. THE WEEKEND
# ---------------------------------------------------------------
def test_the_event_window_reaches_back_past_a_weekend():
    """Friday 15:30 to Monday 09:00 is 65.5 hours. A 36-hour window
    could not see it."""
    events = Events(PULSE)
    _rank(ShortlistBuilder(stock_events=events))
    assert events.asked_hours >= 66, (
        f"the window is {events.asked_hours}h -- a Friday result is "
        f"invisible on Monday below 66")


def test_a_friday_result_still_shows_on_monday():
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE)),
                today="2026-08-03")
    assert any("PULSE: Excellent results" in w for w in got["why"])


def test_and_it_says_it_is_from_friday():
    """A reason from Friday is still a reason. It is not the same as
    one from eleven minutes ago, and presenting them identically is
    lying by omission."""
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE)),
                today="2026-08-03")
    chip = next(w for w in got["why"] if w.startswith("PULSE"))
    assert "(Fri)" in chip, chip


def test_todays_events_carry_no_age_label():
    got = _rank(ShortlistBuilder(stock_events=Events(PULSE)),
                today="2026-07-31")
    chip = next(w for w in got["why"] if w.startswith("PULSE"))
    assert chip == "PULSE: Excellent results", chip


@pytest.mark.parametrize("at,today,expected", [
    ("2026-07-31T14:20:00", "2026-07-31", ""),
    ("2026-07-31T14:20:00", "2026-08-01", " (yesterday)"),
    ("2026-07-31T14:20:00", "2026-08-03", " (Fri)"),
    ("2026-07-20T14:20:00", "2026-08-03", " (14d ago)"),
    (None, "2026-08-03", ""),
    ("not a date", "2026-08-03", ""),
])
def test_the_age_label(at, today, expected):
    assert _age_suffix(at, today) == expected
