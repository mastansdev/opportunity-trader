"""
==========================================================
A stop-out costs Rs 2,000. Whatever the stop distance.
==========================================================

    "but with lower the stop loss 1.67% will kick us out instantly
     right?"                          -- operator, 7 August 2026
    "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS"

Position size came from the MARGIN budget alone and never asked where
the stop was. Measured on the eight fills of 6 August, entry to the
opening-range low:

    JAMNAAUTO 1.26%  BELRISE 1.45%  EXIDEIND 1.72%  RHIM    2.10%
    GMDCLTD   2.41%  VGUARD  3.82%  BASF     4.16%  JKLAKSHMI 6.42%

Rs 2,000 on a Rs 1.2 lakh position allows 1.67%. JKLAKSHMI would have
cost about Rs 6,623 on a stop-out. Nothing refused it.

His worry was that this means a tighter stop. It does not, and the
first test below is the one that proves it: the STOP NEVER MOVES. The
share count comes down instead.

Author : H&M Opportunity Trader
==========================================================
"""

import inspect

from config import RISK_PER_TRADE_RS
from core.engine import Engine

# Real numbers off data/fills.db and the 09:15-09:30 candles.
SIX_AUGUST = [
    ("JAMNAAUTO", 144.79, 143.25 * 0.998, 613),
    ("BELRISE", 243.90, 240.85 * 0.998, 396),
    ("EXIDEIND", 469.75, 462.60 * 0.998, 212),
    ("RHIM", 415.90, 408.00 * 0.998, 212),
    ("GMDCLTD", 594.55, 581.40 * 0.998, 133),
    ("VGUARD", 323.23, 311.50 * 0.998, 337),
    ("BASF", 4177.93, 4012.30 * 0.998, 23),
    ("JKLAKSHMI", 618.00, 579.50 * 0.998, 167),
]


def engine():
    """Arithmetic only -- no broker, no feed, no config LIVE guard."""
    got = Engine.__new__(Engine)
    got._manual_alert = lambda *a, **k: None
    return got


def test_no_trade_risks_more_than_the_budget():
    """The whole point. Every one of the eight, after sizing."""
    bot = engine()
    for symbol, entry, stop, was in SIX_AUGUST:
        distance = entry - stop
        qty = bot._cap_by_risk(was, entry, distance, symbol)
        risk = qty * distance
        assert risk <= RISK_PER_TRADE_RS + 1, (
            f"{symbol} still risks Rs {risk:,.0f} against a "
            f"Rs {RISK_PER_TRADE_RS:,.0f} budget")


def test_jklakshmi_is_the_one_that_changes():
    """Rs 6,623 of risk becomes Rs 2,000. Same stop."""
    bot = engine()
    entry, stop, was = 618.00, 579.50 * 0.998, 167
    distance = entry - stop
    assert was * distance > 6000, "the fixture no longer reproduces it"
    qty = bot._cap_by_risk(was, entry, distance, "JKLAKSHMI")
    assert qty < was, "it did not shrink the position"
    assert qty * distance <= RISK_PER_TRADE_RS + 1


def test_a_tight_stop_is_left_completely_alone():
    """His "win big" half. A tight range keeps its full size."""
    bot = engine()
    entry, stop, was = 144.79, 143.25 * 0.998, 613
    assert bot._cap_by_risk(was, entry, entry - stop, "JAMNAAUTO") == was


def test_the_stop_price_is_never_touched():
    """His first worry, and the important one.

    Read the function: it may compute a share count and nothing else.
    A stop tightened to fit a budget is a guaranteed loser and this bot
    learned that on 24 July.
    """
    src = inspect.getsource(Engine._cap_by_risk)
    body = "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#")
                     and '"""' not in line)
    for forbidden in ("stop_price", "stop =", "self.stop", "hard_stop"):
        assert forbidden not in body, (
            f"the sizer writes to the stop: found '{forbidden}'")


def test_a_stop_so_wide_that_one_share_busts_the_budget_is_refused():
    bot = engine()
    said = []
    bot._manual_alert = lambda *a, **k: said.append(a)
    # One share of a Rs 50,000 stock with a Rs 3,000 stop distance.
    assert bot._cap_by_risk(10, 50000.0, 3000.0, "SILLY") == 0
    assert said, "it refused silently"


def test_no_stop_distance_leaves_the_size_alone():
    """Rather than invent a stop to size against."""
    bot = engine()
    assert bot._cap_by_risk(100, 500.0, 0, "X") == 100
    assert bot._cap_by_risk(100, 500.0, None, "X") == 100


def test_rubbish_in_never_raises():
    """It runs inside the order path."""
    bot = engine()
    for args in ((None, 100.0, 1.0), (10, None, 1.0), ("x", "y", "z")):
        bot._cap_by_risk(*args, "X")


def test_the_sizer_is_actually_called_by_the_sizing_path():
    """The ranker sat unwired through 3,541 green tests. Not again."""
    src = inspect.getsource(Engine._risk_sized_qty)
    assert "_cap_by_risk" in src, (
        "_cap_by_risk exists and nothing calls it")
    assert src.count("_cap_by_risk") >= 2, (
        "only one of the two return paths is capped")
