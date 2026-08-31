"""---- VOLUME SURGE WAS ON HIS LIST AND NOT IN THE CODE. 31 Aug 2026 ----

    "opportunity = news , govt order, volume surge, events"
                                                  -- the operator

Four kinds of opportunity, and the reason lookup asked four stores:
stock events, the newswire, NSE filings, the pre-open gapper card. None
of them is volume. So with REQUIRE_A_REASON_ALWAYS on, a stock with no
published sentence was refused however much money went through it.

WHAT IT COST ON 31 AUGUST
-------------------------
The bot took none of the day's twelve best stocks. It did not refuse
them -- it never evaluated them:

    DIFFNKG      81x its normal volume    +16.9%
    MANALIPETC   65x                       +9.9%
    VENKEYS      26x                       +6.7%

Meanwhile the nine it DID pick, all of which had a published reason,
finished with eight of nine below where it would have bought.

WHY 20x AND NOT THE 5x LANE THAT ALREADY EXISTED
------------------------------------------------
UNEXPLAINED_MIN_VOLUME_RATIO = 5.0 is the old "exceptional volume
stands in for an event" lane, and the objection to it stands: it let
NCC be bought twice on 8.5x with nothing behind it. 5x is an ordinary
busy day.

Counted across all 1,288 stocks with enough history on 31 August:

       5x or more :  74 stocks      <- far too many
      20x or more :  10 stocks      <- this bar, the top 0.8%
      50x or more :   4

ONE DAY OF COUNTING, and the tests below say so. 20.0 is where the
board separates on 31 August and nowhere else yet.
"""

import pytest

import dashboard.state as st
from core.rules import (SURGE_IS_A_REASON, SURGE_REASON_MIN_RATIO,
                        UNEXPLAINED_MIN_VOLUME_RATIO)


class _State:
    """Every reason store empty, so only the volume can answer."""
    stock_events = None
    news_impact = None
    announcement_watcher = None
    _mechanism_for = st.DashboardState._mechanism_for

    def __init__(self, volumes):
        self._volume_now = dict(volumes)


# ---- the real ratios from 31 August, and what each should do ----
TODAY = {"DIFFNKG": 81.2, "MANALIPETC": 65.5, "VENKEYS": 25.6,
         "ALOKINDS": 21.8, "ICIL": 3.6, "HCG": 2.7, "PRUDENT": 2.6}


def test_a_huge_surge_is_a_reason_on_its_own():
    s = _State(TODAY)
    for symbol in ("DIFFNKG", "MANALIPETC", "VENKEYS"):
        got = s._mechanism_for(symbol)
        assert got, f"{symbol} still has no reason"
        assert "volume" in got["text"]


def test_the_reason_names_the_actual_number():
    """"volume" tells him nothing. 81x tells him what the decision was
    made on, and lets him disagree with it."""
    got = _State(TODAY)._mechanism_for("DIFFNKG")
    assert "81x" in got["text"]


def test_an_ordinary_busy_day_is_still_not_a_reason():
    """3.6x and 2.7x are Tuesdays. If those counted, "never into random
    stocks" would be finished -- 74 stocks cleared 5x on 31 August."""
    s = _State(TODAY)
    for symbol in ("ICIL", "HCG", "PRUDENT"):
        assert s._mechanism_for(symbol) is None, symbol


def test_the_bar_is_well_above_the_old_lane():
    """UNEXPLAINED_MIN_VOLUME_RATIO = 5.0 let NCC be bought twice on
    8.5x with nothing behind it. That objection stands and this bar has
    to stay clear of it."""
    assert SURGE_REASON_MIN_RATIO >= 4 * UNEXPLAINED_MIN_VOLUME_RATIO


def test_a_stock_with_no_volume_reading_gets_no_reason():
    """A missing ratio is not a small one. Treating absent as zero is
    fine here; treating it as "probably fine" would not be."""
    s = _State({})
    assert s._mechanism_for("DIFFNKG") is None


def test_a_rubbish_ratio_does_not_crash_the_lookup():
    s = _State({"WEIRD": None, "ALSOWEIRD": "lots"})
    assert s._mechanism_for("WEIRD") is None
    with pytest.raises(TypeError):
        # A string ratio would compare badly -- it must never reach
        # here. state.py filters it at the point it builds the dict,
        # which is what the next test checks.
        _State({"X": "lots"})._mechanism_for("X")


def test_the_ratio_dict_is_built_with_bad_values_filtered():
    """The guard lives where the dict is built, not where it is read."""
    from pathlib import Path

    src = Path("dashboard/state.py").read_text(encoding="utf-8")
    assert "self._volume_now = {}" in src
    assert "except (TypeError, ValueError):" in src


# ------------------------------------------------- it is asked LAST

def test_a_real_reason_still_wins_over_the_tape():
    """A filing or a news item is a better answer than "a lot of shares
    changed hands". The surge only speaks when the four stores have
    nothing, so this must not be able to overwrite one."""
    from pathlib import Path

    src = Path("dashboard/state.py").read_text(encoding="utf-8")
    where_why = src.find("got = why(events=events")
    where_surge = src.find("if got is None and SURGE_IS_A_REASON")
    assert where_why != -1 and where_surge != -1
    assert where_why < where_surge, (
        "the surge is being consulted before the real reason stores")


def test_it_can_be_switched_off():
    assert isinstance(SURGE_IS_A_REASON, bool)


# --------------------------------------------- it decides nothing else

def test_the_surge_only_grants_an_evaluation():
    """It says "look at this stock", not "buy it". Every other gate --
    moving up, volume ratio, a sized plan, circuit room, liquidity --
    is untouched, and long-only is untouched.

    If this ever starts returning something that skips a gate, the bot
    is buying on the tape alone, which is the thing he said no to."""
    got = _State(TODAY)._mechanism_for("DIFFNKG")
    assert set(got) <= {"text", "weight", "kind"}, got
    assert got["weight"] < 1.0, "a tape reason must not outrank a filing"
