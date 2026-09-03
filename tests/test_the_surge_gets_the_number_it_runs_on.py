"""---- THE SURGE RULE WAS NEVER HANDED ITS NUMBER. 3 Sep 2026 ----

    "today bot missed too many volume surge & order opportunities.
     the mechanism is in this way order will be recevied & volume
     starts surging, bot needs to track, enter & exit once the
     momentum gone."
    "last day i said loud enough that exact point. but you didn't
     hear me at all."
                                            -- the operator

He said it on 2 September. I checked that SURGE_IS_A_REASON was True
and that the constant was wired, found both, and reported it fixed.
I never checked whether the VALUE the rule reads ever arrives.

IT DOES NOT, FOR HALF THE MARKET.

Dhan sends quote numbers as strings -- the feed banner prints
{'avg_price': '41.03', 'close': '40.19'} at every startup. When
volume arrives as "12345.0" instead of "12345", int() raises
ValueError, and core/circuit_monitor._snapshot_row's except turned
that into volume=None for the symbol, for the whole session.

MEASURED LIVE, 14:20 on 3 September: 49 of 100 gainer/loser rows had
no volume at all.

dashboard/state._surging_now() opens with

    if not (symbol and volume and price and a): continue

so no volume means no ratio, no pool seed, and the stock is refused
"no event behind it -- the tape is not a reason" while it trades at
191x its own normal:

    BFUTILITIE   191x   +15.7%   refused 1,562 times
    SBCL                          refused 1,557 times, never once
                                  reached the board
    ANTELOPUS    374x   +20.0%   refused   622 times
    INDOCO       456x   +12.3%   never bought
    PAR          253x   +19.7%   never bought

This is the fourth time the same shape has cost him a day: prev_close
against close, shortlist against ranked, a boolean that became an
object, and now an int that was really a float in a string. Each
time I verified the layer I touched and not the value it reads.
"""

import pytest

from core.circuit_monitor import CircuitMonitor


def _row(volume):
    """One quote through the real parser, nothing mocked but the wire."""
    monitor = CircuitMonitor(quote_fn=lambda req: None,
                             exchange_segment="NSE_EQ")
    return monitor._snapshot_row({
        "last_price": 100.0,
        "upper_circuit_limit": 120.0,
        "lower_circuit_limit": 80.0,
        "volume": volume,
        "ohlc": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 99.5},
    })


@pytest.mark.parametrize("sent,expected", [
    (12345,        12345),      # int
    ("12345",      12345),      # string int
    ("12345.0",    12345),      # THE BUG -- int() raised on this
    (12345.0,      12345),      # float
    ("12345.67",   12345),      # float string with real decimals
    (0,                0),
    (None,             0),
    ("",               0),
])
def test_every_shape_dhan_sends_parses_to_a_number(sent, expected):
    row = _row(sent)
    assert row is not None, "the row was dropped entirely"
    assert row["volume"] == expected, (
        f"volume {sent!r} parsed to {row['volume']!r}; a stock with no "
        f"volume cannot trigger the surge rule and is refused for "
        f"'no event behind it' while it trades at 191x normal")


def test_genuinely_unreadable_volume_is_still_none():
    """None must stay possible. A stock we cannot measure must read as
    unmeasured, never as zero -- zero is a claim that nothing traded."""
    assert _row("not a number")["volume"] is None


def test_the_surge_seeder_needs_volume():
    """Asserted on the source. This is the line that silently dropped
    half the market, and it must keep needing volume -- the fix is to
    supply the number, never to loosen the check."""
    import os
    with open(os.path.join("dashboard", "state.py"), encoding="utf-8") as fh:
        body = fh.read()
    assert "if not (symbol and volume and price and a):" in body, (
        "_surging_now no longer guards on volume -- if that guard was "
        "removed rather than fed, the surge ratio is being computed "
        "from a missing number")


def test_the_surge_rule_is_still_switched_on():
    from core.rules import SURGE_IS_A_REASON, SURGE_REASON_MIN_RATIO
    assert SURGE_IS_A_REASON is True
    assert SURGE_REASON_MIN_RATIO == 10.0, (
        "his bar is ten times the stock's own normal volume")
