"""
==========================================================
One day was never a measurement
==========================================================

    "fix both"                      -- operator, 2 August 2026

CENTURYPLY was blocked as illiquid on Rs 1.76 crore. That is its
30 July figure. On 31 July it traded Rs 62.29 crore:

    22 Jul  23 Jul  24 Jul  27 Jul  28 Jul  29 Jul  30 Jul  31 Jul
     1.25    2.64    2.68    2.94    1.66    6.29    1.76   62.29

A single previous session decides in BOTH directions and gets it
wrong both ways. Measured across the last ten bhavcopies on disk,
against all 1,245 master symbols:

    clearing Rs 5cr on the last session only   974
    clearing Rs 5cr on a 10-session median     949
      newly allowed by the median               46
      newly blocked by the median               71

THE 71 ARE THE IMPORTANT HALF
-----------------------------
    SIGMA        last day Rs 31.74cr   median Rs  0.15cr
    PUNJABCHEM   last day Rs 31.55cr   median Rs  0.82cr
    BESTAGRO     last day Rs 71.20cr   median Rs  0.45cr
    CENTURYPLY   last day Rs 62.29cr   median Rs  2.66cr

Every one of those spikes is a results day. On the old rule the stock
was tradeable the next morning, on MTF at up to 4X, held overnight --
into a book that normally turns over fifteen lakh a day. That is not
an opportunity, it is a position you cannot exit.

I had this backwards when I first reported it: I said CENTURYPLY was
"not illiquid" because of the 62-crore day. Its normal day is
Rs 2.66 crore. The 62 was the spike, not the baseline.

AND THE 46 ARE REAL TOO
-----------------------
    FEDDERSHOL  median Rs 18.98cr   last day Rs 1.94cr
    KROSS       median Rs 18.62cr   last day Rs 4.40cr
    INDOBORAX   median Rs 14.77cr   last day Rs 2.79cr

Genuinely liquid names that one quiet day was hiding.

MEDIAN, NOT MEAN. CENTURYPLY's mean over those sessions is Rs 10.2cr
and is carried entirely by the one results day. The median answers
"on a normal day, can I get out", which is the question the bar was
written to ask.

WHAT IS NOT POOLED
------------------
Series, close and the T2T check still come from the LATEST session
only. Those are facts about today; a median of them would mean
nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.subscribe_list import (MIN_TURNOVER_RS, TURNOVER_MIN_SESSIONS,
                                 TURNOVER_SESSIONS, build_bhav_index,
                                 build_bhav_index_over, decide)


def day(**turnovers):
    """One bhavcopy, as raw rows. Rupees in, like the real file."""
    return [{"TckrSymb": s, "SctySrs": "EQ", "ClsPric": "100",
             "TtlTradgVol": "1", "TtlTrfVal": str(v)}
            for s, v in turnovers.items()]


# ---- THESE ARE DERIVED, NOT TYPED. 3 September 2026. ----
#
# They were Rs 1cr / Rs 60cr / Rs 9cr, chosen to sit either side of a
# MIN_TURNOVER_RS that was Rs 1.5cr at the time. That constant is not
# a setting -- core/subscribe_list.py computes it as
#
#     MIN_TURNOVER_RS = _POSITION_RS / MAX_POSITION_SHARE_OF_DAY
#
# so when the slot was halved to Rs 15,000 on 3 September the floor
# halved with it, to Rs 0.75cr, and the "quiet" fixture at Rs 1cr was
# suddenly LIQUID. Four tests in this file failed saying nothing about
# medians at all.
#
# That the floor moved is correct and is the point: a smaller position
# needs less of the day's turnover to fill, so more stocks become
# tradeable. What was wrong was a test that pinned it.
#
# Tied to the constant now, so the next time the slot changes these
# still bracket it.
QUIET = MIN_TURNOVER_RS / 2          # too thin to trade
FINE = MIN_TURNOVER_RS * 12          # comfortably liquid
BUSY = MIN_TURNOVER_RS * 80          # the one results day


# ---------------------------------------------------------------
# 1. A SPIKE NO LONGER LETS A THIN STOCK THROUGH
# ---------------------------------------------------------------
def test_one_busy_day_does_not_make_a_thin_stock_tradeable():
    """SIGMA: Rs 31.74cr on its results day, Rs 0.15cr median. The old
    rule made it tradeable on MTF overnight into a book that turns over
    fifteen lakh."""
    days = [day(SIGMA=QUIET) for _ in range(9)] + [day(SIGMA=BUSY)]
    idx = build_bhav_index_over(days)
    assert idx["SIGMA"]["turnover"] == QUIET
    ok, why = decide("SIGMA", bhav=idx["SIGMA"], sector="IT")
    assert not ok and "too illiquid" in why


def test_the_old_rule_would_have_allowed_it():
    """The comparison, so the change is visible rather than asserted."""
    idx = build_bhav_index(day(SIGMA=BUSY))
    ok, _ = decide("SIGMA", bhav=idx["SIGMA"], sector="IT")
    assert ok, "fixture is wrong -- the single-day rule should pass this"


def test_one_quiet_day_no_longer_blocks_a_liquid_stock():
    """KROSS: median Rs 18.62cr, last day Rs 4.40cr."""
    days = [day(KROSS=FINE) for _ in range(9)] + [day(KROSS=QUIET)]
    idx = build_bhav_index_over(days)
    assert idx["KROSS"]["turnover"] == FINE
    ok, why = decide("KROSS", bhav=idx["KROSS"], sector="AUTOMOBILE")
    assert ok, why


def test_the_median_is_not_the_mean():
    """CENTURYPLY's mean is Rs 10.2cr and its median Rs 2.66cr. The mean
    is the one results day. Using it would put the stock back."""
    days = [day(X=QUIET) for _ in range(9)] + [day(X=BUSY)]
    idx = build_bhav_index_over(days)
    mean = (QUIET * 9 + BUSY) / 10
    assert idx["X"]["turnover"] == QUIET
    assert mean > MIN_TURNOVER_RS > idx["X"]["turnover"]


# ---------------------------------------------------------------
# 2. ONLY TURNOVER IS POOLED
# ---------------------------------------------------------------
def test_series_and_close_come_from_the_latest_session_only():
    """A median close is not a price and a median series is not a
    series. Today's T2T flag has to be today's."""
    old = [{"TckrSymb": "Z", "SctySrs": "EQ", "ClsPric": "100",
            "TtlTradgVol": "1", "TtlTrfVal": str(FINE)}]
    new = [{"TckrSymb": "Z", "SctySrs": "BE", "ClsPric": "250",
            "TtlTradgVol": "1", "TtlTrfVal": str(FINE)}]
    idx = build_bhav_index_over([old, old, old, new])
    assert idx["Z"]["series"] == "BE"
    assert idx["Z"]["close"] == 250
    ok, why = decide("Z", bhav=idx["Z"], sector="IT")
    assert not ok and "T2T" in why


def test_a_stock_absent_from_the_latest_session_is_not_carried_forward():
    """Bhavcopy lists what traded. A name that did not trade today has
    no close and no series, and inventing yesterday's would be reading
    a stale price as a live one."""
    idx = build_bhav_index_over([day(A=FINE, B=FINE), day(A=FINE)])
    assert "B" not in idx


# ---------------------------------------------------------------
# 3. A SHORT HISTORY IS NOT A MEDIAN
# ---------------------------------------------------------------
def test_too_few_sessions_uses_the_worst_reading_not_the_best():
    """A stock listed on Thursday that traded heavily once has not
    shown it can be exited on a NORMAL day, and this bar exists to ask
    exactly that."""
    idx = build_bhav_index_over([day(NEW=BUSY), day(NEW=QUIET)])
    assert idx["NEW"]["turnover"] == QUIET
    assert idx["NEW"]["turnover_days"] == 2


def test_one_session_is_exactly_the_old_behaviour():
    """Degrading, not failing. A dead network gives one bhavcopy and
    the tool must still produce a universe."""
    one = build_bhav_index_over([day(A=FINE)])
    old = build_bhav_index(day(A=FINE))
    assert one["A"]["turnover"] == old["A"]["turnover"]
    assert one["A"]["turnover_days"] == 1


def test_nothing_in_gives_nothing_out():
    assert build_bhav_index_over([]) == {}
    assert build_bhav_index_over(None) == {}
    assert build_bhav_index_over([[], []]) == {}


# ---------------------------------------------------------------
# 4. THE BLOCK CAN BE ARGUED WITH
# ---------------------------------------------------------------
def test_the_reason_says_how_many_sessions_it_speaks_from():
    """A block the operator cannot check is a block he has to take on
    trust, and he has been given wrong numbers by this file before."""
    days = [day(A=QUIET) for _ in range(TURNOVER_SESSIONS)]
    idx = build_bhav_index_over(days)
    _, why = decide("A", bhav=idx["A"], sector="IT")
    assert f"median of {TURNOVER_SESSIONS} sessions" in why
    # The rupee figure is QUIET expressed in crore -- derived, so it
    # cannot drift away from the fixture the way the hard-coded
    # "1.00cr" did when the slot halved.
    assert "%.2fcr" % (QUIET / 1_00_00_000) in why

    _, why_one = decide("A", bhav=build_bhav_index(day(A=QUIET))["A"],
                        sector="IT")
    assert "last session" in why_one


def test_the_window_is_long_enough_to_survive_a_results_day():
    """A results-day spike must be one reading among many. Anything
    below about a week and a single day starts moving the median."""
    assert TURNOVER_SESSIONS >= 5
    assert 1 < TURNOVER_MIN_SESSIONS < TURNOVER_SESSIONS


def test_the_bar_is_a_share_of_the_day_not_a_loose_constant():
    """2 August 2026. Rs 5 crore means nothing on its own -- it only
    means something next to the size of a position. His rule is Rs 1
    lakh per MTF position, so the bar says "my order is 0.2% of what
    the stock trades on a normal day".

    A flat constant does not keep that. Double the position and the
    same Rs 5cr silently becomes 0.4%, with nothing saying so."""
    from core.subscribe_list import (MAX_POSITION_SHARE_OF_DAY,
                                     MIN_TURNOVER_RS, _POSITION_RS)
    assert MIN_TURNOVER_RS == _POSITION_RS / MAX_POSITION_SHARE_OF_DAY


def test_the_derived_bar_moves_with_position_size():
    from core.subscribe_list import MAX_POSITION_SHARE_OF_DAY as share
    assert 200_000 / share == 100_000_000, (
        "a Rs 2 lakh position should demand Rs 10cr of normal turnover")


def test_it_still_works_if_config_cannot_be_read():
    """A test fixture or a stripped checkout has no config. The
    universe must still build."""
    src = open("core/subscribe_list.py", encoding="utf-8").read()
    block = src[src.find("try:\n    from config import MTF_MARGIN"):]
    block = block[:block.find("MIN_TURNOVER_RS =")]
    assert "except Exception" in block
    from core.subscribe_list import _POSITION_RS
    assert str(int(_POSITION_RS)) in block.replace("_", "")


def test_the_morning_tool_asks_for_the_window():
    src = open("tools/morning_universe.py", encoding="utf-8").read()
    assert "build_bhav_index_over" in src
    assert "recent_bhavcopies()" in src
    block = src[src.find("history = recent_bhavcopies()"):]
    block = block[:block.find("excluded = fetch_excluded_symbols()")]
    assert "build_bhav_index(bhav_rows)" in block, (
        "it must still fall back to one session rather than aborting")
    assert "1 session only" in block, (
        "and it must SAY so -- a silent fallback to the old rule is how "
        "this went unnoticed for a week")
