"""Price says the move died. The buying says it did not.

    "volume is also considered as event. as some stocks will rally
     sudden volume surges & later we/bot will know the reason.
     retailer typically last to know the reason behind stock movements
     & volume can't hide. right now with order flow . buying pressure
     making highs confirm even before news land into bot"
                                    -- operator, 31 August 2026

PRECWIRE, that morning. The entry gate refused it 518 times as
"fading -- the move has already stopped working", because _faded()
asks one question: where does the PRICE sit in the day's range.
PRECWIRE sat at 0.22 of its range, so: faded.

At the same moment, off the live store:

    buy 1,34,708   sell 79,125   -> 63% of every share traded was bought
    cumulative delta 18,774 at 09:15 -> 56,830 by 11:43, rising all day
    book_ticks 7,637 of 7,637 ticks  -> 100% MEASURED, not inferred

The price pulled back. The pressure never did. A pullback on rising
buying is not the same animal as a roll-over on selling, and the bot
could not tell them apart.

WHY "STILL GROWING" AND NOT "RECENTLY PEAKED". The first draft asked
how long ago the delta peaked. Measured on the live session, that
answered wrongly: PRECWIRE's peak was 17 minutes old and it was
sitting 1.1% BELOW it. A stock can hold its high for an hour without
having stopped buying. So the test is whether delta is HIGHER THAN IT
WAS, fifteen minutes back -- the same clock core/intraday_shape.py
already uses. On the live data that afternoon it separated them
cleanly:

    PRECWIRE     66,243  vs  65,930  ->  growing,  99% of peak
    ASHOKA      3,04,021 vs 3,28,122 ->  falling,  67% of peak
    ATHERENERG    34,988 vs   40,031 ->  falling,  83% of peak
    VIMTALABS    -33,897 vs  -14,861 ->  falling, negative

THE FLOW CAN ONLY RESCUE, NEVER CONDEMN. A gate that could be turned
ON by a guess would be worse than the gate we already have.
"""

import pytest

from core import order_flow
from core.auto_entry import _faded


def _series(cums, book=True, start="09:15"):
    """Minutes carrying a cumulative delta path."""
    out = []
    hh, mm = int(start[:2]), int(start[3:])
    for i, cum in enumerate(cums):
        total = hh * 60 + mm + i
        out.append({"minute": "%02d:%02d" % (total // 60, total % 60),
                    "cum": float(cum), "delta": 0.0, "ltp": 100.0,
                    "ticks": 50, "book_ticks": 50 if book else 2})
    return out


def _rising(n=40):
    return _series([1000 * (i + 1) for i in range(n)])


def _rolling_over(n=40):
    up = [1000 * (i + 1) for i in range(n // 2)]
    peak = up[-1]
    return _series(up + [peak - 800 * (i + 1) for i in range(n - len(up))])


# ------------------------------------------------------ still_buying

def test_delta_growing_and_positive_is_still_buying():
    got = order_flow.still_buying("X", series=_rising())
    assert got["still_buying"] is True
    assert got["growing"] and got["positive"]


def test_delta_falling_back_is_not():
    got = order_flow.still_buying("X", series=_rolling_over())
    assert got["still_buying"] is False


def test_holding_near_the_high_is_still_buying():
    """PRECWIRE's actual shape: 1.1% below a peak seventeen minutes
    old, and still adding. The first draft called that "stopped"."""
    path = [1000 * (i + 1) for i in range(30)]
    path += [path[-1] + 20 * (i + 1) for i in range(10)]   # crawling up
    got = order_flow.still_buying("X", series=_series(path))
    assert got["still_buying"] is True
    assert got["of_peak"] == 100.0


def test_negative_delta_is_never_still_buying():
    """Growing towards zero is not buying. VIMTALABS went -14,861 to
    -33,897 and even a rise from -40,000 to -30,000 is sellers
    winning, more slowly."""
    got = order_flow.still_buying("X", series=_series(
        [-40000 + 100 * i for i in range(40)]))
    assert got["growing"] is True
    assert got["positive"] is False
    assert got["still_buying"] is False


def test_too_little_session_says_nothing():
    assert order_flow.still_buying("X", series=_rising(5)) is None


def test_an_inferred_reading_says_nothing():
    """The tick rule is 75-80% right. It must not be allowed to
    overrule a gate -- see FLOW_MIN_BOOK_PCT."""
    inferred = _series([1000 * (i + 1) for i in range(40)], book=False)
    assert order_flow.still_buying("X", series=inferred) is None


# ------------------------------------------------------- the gate itself

def _row(ltp, symbol="X"):
    return {"symbol": symbol, "day_high": 130.0, "day_low": 100.0, "ltp": ltp}


def test_a_strong_stock_is_not_faded_and_never_asks_the_flow(monkeypatch):
    """Above half its range it was never faded. The flow lookup costs
    a database read and must not happen on every healthy row."""
    def boom(*a, **k):
        raise AssertionError("the flow was consulted on a healthy row")

    monkeypatch.setattr(order_flow, "still_buying", boom)
    assert _faded(_row(125.0)) is False


def test_a_pullback_on_rising_buying_is_rescued(monkeypatch):
    monkeypatch.setattr(order_flow, "still_buying",
                        lambda *a, **k: {"still_buying": True})
    assert _faded(_row(106.0)) is False, "PRECWIRE would be refused again"


def test_a_pullback_on_falling_buying_stays_faded(monkeypatch):
    monkeypatch.setattr(order_flow, "still_buying",
                        lambda *a, **k: {"still_buying": False})
    assert _faded(_row(106.0)) is True


def test_no_flow_reading_leaves_the_price_verdict_alone(monkeypatch):
    """A missing reading means "do not act", never "no buying"."""
    monkeypatch.setattr(order_flow, "still_buying", lambda *a, **k: None)
    assert _faded(_row(106.0)) is True


def test_a_broken_flow_lookup_cannot_open_the_gate(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store gone")

    monkeypatch.setattr(order_flow, "still_buying", boom)
    assert _faded(_row(106.0)) is True


def test_an_unknown_range_is_still_not_faded():
    """Unchanged: the test fails OPEN when the row carries no range."""
    assert _faded({"symbol": "X", "ltp": 100.0}) is False
