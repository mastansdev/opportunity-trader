"""
==========================================================
Three rules he read off a chart in one glance
==========================================================

    "i'm not satisfied with bot entries . why it is taking trades in
     falling stock? DEEPAKNTR even i took this without looking charts.
     ; ICICIGI SAME STORY"
                                -- operator, 5 August 2026

He named two stocks from memory. Of the nineteen sized entries the bot
would have taken that day, exactly two were trading below their own
opening price -- DEEPAKNTR and ICICIGI. Both lost. He had picked out
the entire defect without seeing any of the data.

RULE 1 -- NOTHING BEFORE 09:30
------------------------------
The ranker published DEEPAKNTR at 09:15:28, twenty-eight seconds after
the open and fifteen minutes before the opening range closes.

    picked before 09:30    5 picks   avg  -2.71%
    picked 09:30 onwards  18 picks   avg  +1.51%

RULE 2 -- NEVER BUY BELOW TODAY'S OPEN
--------------------------------------
`change_pct` is measured against YESTERDAY'S CLOSE and that was the
only number the ranker ever saw. ICICIGI:

    prev close 1644.80   opened 1732.20 (+5.3% gap)
    09:15 1722.9 ... 09:23 1687.8        nine down minutes in a row
    the bot recorded: change_pct 2.68%, state=alive, action BUY

A gap is not momentum. Above its open or it is falling today.

RULE 3 -- FADING CANNOT BE SIZED
--------------------------------
SFL and PNBHOUSING were entered with `state=fading` recorded on the
same row. liveness() knew; position_plan never asked.

WHAT THESE NUMBERS ARE NOT
--------------------------
One day and nineteen trades, and the rules were written after looking
at that day's losers. The P&L improvement is arithmetic, not evidence.
Each rule is here because it stands on its own:

    below its own open  = falling today, by definition
    before 09:30        = there is no opening range yet to break
    fading              = the bot contradicting itself in one row

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

import pytest

from core.ranker import RANK_FROM_TIME, rank


def mover(symbol, change_pct, ltp, **extra):
    row = {"symbol": symbol, "change_pct": change_pct, "ltp": ltp,
           "sector": "CHEMICALS", "volume_x": 3.0}
    row.update(extra)
    return row


def good_reason(_symbol):
    return {"text": "Better-than-expected quarterly results signal "
                    "stronger margins",
            "weight": 0.8, "direction": "POSITIVE"}


def rich(_symbol):
    return 50.0


def mtf_ok(_symbol, _row=None):
    return {"eligible": True, "leverage": 3.0, "margin_pct": 33.0}


def call(movers, **kwargs):
    kwargs.setdefault("mechanism_of", good_reason)
    kwargs.setdefault("adv_of", rich)
    kwargs.setdefault("mtf_of", mtf_ok)
    return rank(movers, **kwargs)


# ---------------------------------------------------------------
# RULE 1 -- NOTHING BEFORE THE OPENING RANGE EXISTS
# ---------------------------------------------------------------
def test_nothing_is_named_at_twenty_eight_seconds_past_the_open():
    """DEEPAKNTR, 09:15:28."""
    got = call([mover("DEEPAKNTR", 6.79, 1834.40)],
               now=datetime(2026, 8, 5, 9, 15, 28))
    assert got["rows"] == []
    assert RANK_FROM_TIME in got["note"]


def test_the_boundary_belongs_to_the_ranker():
    """09:30 exactly is the first moment the range is complete."""
    got = call([mover("CASTROLIND", 3.06, 193.00)],
               now=datetime(2026, 8, 5, 9, 30, 0))
    assert [r["symbol"] for r in got["rows"]] == ["CASTROLIND"]


def test_one_minute_early_is_still_early():
    got = call([mover("CASTROLIND", 3.06, 193.00)],
               now=datetime(2026, 8, 5, 9, 29, 59))
    assert got["rows"] == []


def test_the_afternoon_is_fine():
    got = call([mover("RITES", 3.1, 222.93)],
               now=datetime(2026, 8, 5, 14, 12))
    assert [r["symbol"] for r in got["rows"]] == ["RITES"]


def test_no_clock_means_no_time_check():
    """Every existing caller and test passes no clock and must behave
    exactly as before."""
    got = call([mover("RITES", 3.1, 222.93)])
    assert [r["symbol"] for r in got["rows"]] == ["RITES"]


def test_an_empty_ranking_still_reports_refusals_not_a_crash():
    got = call([mover("X", 5.0, 100.0)], now=datetime(2026, 8, 5, 9, 20))
    assert got["refusals"] == {}
    assert got["market_pct"] == 0.0


# ---------------------------------------------------------------
# RULE 2 -- A GAP IS NOT MOMENTUM
# ---------------------------------------------------------------
ICICIGI = mover("ICICIGI", 2.68, 1687.80, sector="FINANCE")
DEEPAKNTR = mover("DEEPAKNTR", 4.94, 1802.50)


def test_the_two_stocks_he_named():
    """Both up against yesterday. Both below today's open. Both
    refused."""
    opens = {"ICICIGI": 1732.20, "DEEPAKNTR": 1840.00}
    got = call([ICICIGI, DEEPAKNTR], open_of=opens.get)
    assert got["rows"] == []
    assert got["refusals"]["below its own open -- falling today"] == 2


def test_without_the_gate_they_both_rank():
    """Proof the test above is testing the gate and not something
    else. This is exactly what shipped on 5 August."""
    got = call([ICICIGI, DEEPAKNTR])
    assert sorted(r["symbol"] for r in got["rows"]) == ["DEEPAKNTR", "ICICIGI"]


def test_a_stock_above_its_open_is_untouched():
    got = call([mover("ENGINERSIN", 3.0, 231.54)],
               open_of=lambda s: 226.90)
    assert [r["symbol"] for r in got["rows"]] == ["ENGINERSIN"]


def test_exactly_at_the_open_is_allowed():
    """Not below. A stock sitting on its open has not broken down."""
    got = call([mover("X", 3.0, 100.0)], open_of=lambda s: 100.0)
    assert [r["symbol"] for r in got["rows"]] == ["X"]


def test_the_mirror_holds_for_a_short():
    """A short wants a stock BELOW its open. One that has recovered
    above it is rising today."""
    got = call([mover("Y", -3.0, 105.0)], open_of=lambda s: 100.0,
               mechanism_of=lambda s: {
                   "text": "Weak quarterly numbers, margins compressed "
                           "sharply", "weight": 0.8,
                   "direction": "NEGATIVE"})
    assert got["rows"] == []
    assert "above its own open -- rising today" in got["refusals"]


def test_an_unknown_open_does_not_refuse_the_stock():
    """A missing reference is not evidence of falling. Refusing on it
    would silently empty the panel for anything that had not ticked
    when the open was recorded."""
    got = call([mover("X", 3.0, 100.0)], open_of=lambda s: None)
    assert [r["symbol"] for r in got["rows"]] == ["X"]


def test_a_broken_open_lookup_cannot_stop_the_ranking():
    def explodes(_symbol):
        raise RuntimeError("store is gone")
    got = call([mover("X", 3.0, 100.0)], open_of=explodes)
    assert [r["symbol"] for r in got["rows"]] == ["X"]


def test_no_open_lookup_means_no_check():
    got = call([ICICIGI])
    assert [r["symbol"] for r in got["rows"]] == ["ICICIGI"]


# ---------------------------------------------------------------
# RULE 3 -- FADING CANNOT BE SIZED
# ---------------------------------------------------------------
def test_a_fading_row_gets_no_tradeable_plan():
    """Read off the real source. SFL carried state=fading and a sized,
    tradeable plan on the same row."""
    import inspect

    from dashboard.state import DashboardState
    code = inspect.getsource(DashboardState.build_ranked)
    body = code[code.find("position_plan"):]
    assert 'row.get("state") == "fading"' in body, (
        "position_plan is still sized without asking liveness()")
    # The refusal must come BEFORE the sizing call, not after it.
    assert body.index('"fading"') < body.rindex("position_plan(")


# ---------------------------------------------------------------
# THE RULES ARE ACTUALLY WIRED TO THE LIVE PATH
# ---------------------------------------------------------------
def test_the_dashboard_passes_the_clock_and_the_open():
    """A gate nothing calls is a comment."""
    import inspect

    from dashboard.state import DashboardState
    code = inspect.getsource(DashboardState.build_ranked)
    # Everything from the rank( call onwards. Two earlier attempts at a
    # tighter slice failed on their own arithmetic rather than on the
    # code -- one stopped inside datetime.now(), the next matched an
    # `except` that sits above the call.
    block = code[code.find("got = rank("):]
    assert block, "build_ranked no longer calls rank()"
    assert "now=" in block, "the ranker is never told the time"
    assert "open_of=" in block, "the ranker is never told today's open"
    assert "get_day_open" in block


def test_the_open_lookup_is_a_real_method():
    """get_day_open, not a name I remembered."""
    import inspect

    from core.market_data import MarketData
    assert "get_day_open" in {n for n, _ in inspect.getmembers(MarketData)}
