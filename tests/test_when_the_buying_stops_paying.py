"""Price kept making highs; the buying had already stopped.

    "at some point the momentum fades out, we can book the profits &
     re -enter as our watchlist becomes very small"
                                    -- operator, 24 August 2026
    "harder verdict"                -- operator, 30 August 2026

He arrived at this himself before I looked it up, and it is the read
NinjaTrader, Bookmap and GoCharting all describe. Cumulative delta
starts each day at zero. While it climbs WITH price, the rise is
being paid for -- somebody is lifting offers. When price keeps making
new highs and cumulative delta does not follow, the last buyers have
stopped paying up and the price is coasting on nothing.

WHAT THIS IS NOT. It is not "delta went negative". Delta dips all day
in a stock that closes at its high; selling into strength is normal
and gating on it would exit every winner before lunch. The signal is
the DIVERGENCE: new price highs that the buying did not confirm.

THE HONESTY GATE IS THE POINT. core/order_flow.py classifies a print
by whether it hit the bid or lifted the offer, from the real 5-level
book. When depth is missing it falls back to the tick rule, which is
roughly 75-80% right and worst in exactly the fast markets this would
be used in. A divergence computed from inferred sides is a guess in
the clothes of a measurement, and it would tell him to sell a winner
on the strength of it. So below FLOW_MIN_BOOK_PCT the reading is
still shown and is plainly marked estimated.
"""

import pytest

from core import order_flow


def _series(points):
    """points = [(minute, delta, ltp, ticks, book_ticks)]"""
    out, running = [], 0.0
    for minute, delta, ltp, ticks, book in points:
        running += delta
        out.append({"minute": minute, "delta": delta, "cum": running,
                    "ltp": ltp, "ticks": ticks, "book_ticks": book})
    return out


def _minutes(n, start=15):
    for i in range(n):
        yield "%02d:%02d" % (9 + (start + i) // 60, (start + i) % 60)


def _rising(n=40, book=True):
    """Price and buying climbing together -- a healthy move."""
    pts = []
    for i, m in enumerate(_minutes(n)):
        pts.append((m, 1000.0, 600.0 + i * 0.5, 50, 50 if book else 2))
    return _series(pts)


def _diverging(n=40, book=True, tail=8):
    """Buying peaks, then price makes new highs without it."""
    pts = []
    for i, m in enumerate(list(_minutes(n))):
        if i < n - tail:
            delta = 1000.0
        else:
            delta = -400.0          # sellers taking the other side
        pts.append((m, delta, 600.0 + i * 0.5, 50, 50 if book else 2))
    return _series(pts)


# ------------------------------------------------------- saying nothing

def test_five_minutes_of_a_session_says_nothing():
    """Cumulative delta at 09:20 is noise, not a reading."""
    assert order_flow.divergence("X", series=_rising(6)) is None


def test_a_move_being_paid_for_is_not_a_warning():
    """The failure that would cost him money is a false exit. Price
    and buying climbing together must never produce one."""
    assert order_flow.divergence("X", series=_rising(40)) is None


def test_delta_dipping_in_a_strong_stock_is_not_divergence():
    """Selling into strength is normal. Only NEW HIGHS that the
    buying did not confirm count."""
    pts = []
    for i, m in enumerate(list(_minutes(40))):
        delta = -800.0 if i % 5 == 0 else 1200.0
        pts.append((m, delta, 600.0 + i * 0.5, 50, 50))
    assert order_flow.divergence("X", series=_series(pts)) is None


def test_a_morning_divergence_is_not_an_afternoon_exit():
    """Diverged at 10:00 and sideways since is not a reason to sell
    at 15:00. The last new high must be recent."""
    pts = []
    for i, m in enumerate(list(_minutes(300))):
        if i < 30:
            delta, price = 1000.0, 600.0 + i * 0.5
        elif i < 40:
            delta, price = -500.0, 615.0 + (i - 30) * 0.2   # new highs
        else:
            delta, price = 0.0, 610.0                       # flat, hours
        pts.append((m, delta, price, 50, 50))
    assert order_flow.divergence("X", series=_series(pts)) is None


# ------------------------------------------------------- saying it plainly

def test_new_highs_the_buying_did_not_follow():
    got = order_flow.divergence("X", series=_diverging())
    assert got is not None
    assert got["diverged"] is True
    assert got["new_highs"] >= 2
    assert got["since"], "the card has to name the time the buying peaked"
    assert "did not follow" in got["why"]


def test_it_names_when_the_buying_peaked_not_when_price_did():
    """"since 14:05" on the card is the moment BUYING topped out --
    the price went on rising after it, which is the whole point."""
    got = order_flow.divergence("X", series=_diverging(n=40, tail=8))
    assert got["since"] < "09:55", got["since"]


# ------------------------------------------------- the gate that matters

def test_an_inferred_divergence_is_marked_estimated():
    """The tick rule is 75-80% right. A verdict built on it must not
    look like a measurement -- this is what stops the board telling
    him to sell a winner on a guess."""
    got = order_flow.divergence("X", series=_diverging(book=False))
    assert got is not None, "the reading is still shown"
    assert got["measured"] is False
    assert got["book_pct"] < 60.0


def test_a_measured_divergence_says_so():
    got = order_flow.divergence("X", series=_diverging(book=True))
    assert got["measured"] is True
    assert got["book_pct"] >= 60.0


def test_the_threshold_is_the_one_in_config():
    from config import FLOW_MIN_BOOK_PCT, FLOW_DIVERGENCE_HIGHS

    assert 50.0 <= FLOW_MIN_BOOK_PCT <= 100.0
    assert FLOW_DIVERGENCE_HIGHS >= 2, (
        "one new high is noise on any tick; the card claims two")


# ------------------------------------------------------------- reading back

def test_an_empty_store_is_not_an_error(tmp_path):
    """A machine that has never recorded a session has nothing to
    say, and that is a fact rather than a failure."""
    assert order_flow.session_series("X", db_path=str(tmp_path / "no.db")) == []
    assert order_flow.divergence("X", db_path=str(tmp_path / "no.db")) is None


def test_the_running_total_is_built_on_read_not_stored():
    """A gap in the middle must not corrupt the earlier part of the
    day -- so the total is summed here, from the minutes on file."""
    got = _series([("09:15", 100.0, 10.0, 1, 1),
                   ("09:16", -30.0, 10.0, 1, 1),
                   ("09:17", 50.0, 10.0, 1, 1)])
    assert [r["cum"] for r in got] == [100.0, 70.0, 120.0]
