"""---- THE DOOR WAS READING A PHOTOGRAPH. 3 September 2026. ----

    "fix the entry lag, make it read ticks not the snapshot. to be
     frank i want lag free & seamless dashboard with out missing any
     opportunity. bot is doing too much complex of operations"

core/auto_entry.take() ends in

    enter(symbol, security_id, row.get("ltp"), plan["stop"], ...)

and row["ltp"] came off the dashboard snapshot. That snapshot is
rebuilt by dashboard/state._build(), which recomputes about
twenty-five panels from scratch: 42s at the median, 82s at p90.
main.py asks for one every second (DASHBOARD_REFRESH_INTERVAL_SECONDS
= 1) and gets one every forty. So the price the order was placed at,
and the stop derived from it, were up to a minute and a half old.

Measured on his own book: entries averaged 0.95% worse than the price
at first sighting.

THE SPLIT. The snapshot answers the SLOW question well -- which stocks
qualify: reason, sector, liquidity, ADV, news. None of that moves in a
minute. It answers the FAST one badly. So the snapshot still chooses
the candidates and the tick prices them. That is the division
core/engine.py already uses at the other end of the trade:
process_tick() runs the trailing stop intrabar, on every tick.

price_of is INJECTED, exactly like engine.buying_check, and for the
reason that file gives: nothing here imports the tick store, so a unit
test cannot reach the live one.
"""

from core.auto_entry import price_now


def _tick(ltp, prev=100.0, high=None, low=None):
    return lambda sym: {"LTP": ltp, "close": prev,
                        "high": high if high is not None else ltp,
                        "low": low if low is not None else ltp}


def test_the_order_price_is_the_tick_not_the_snapshot():
    """THE BUG. The snapshot said 100.00 a minute ago; the stock is
    102.50 now. The order was going in at 100.00."""
    row = {"symbol": "ANTELOPUS", "ltp": 100.0, "change_pct": 0.0}
    price_now(row, _tick(102.5))
    assert row["ltp"] == 102.5
    assert row["priced_from"] == "tick"


def test_the_change_is_recomputed_from_the_real_previous_close():
    """change_pct decides whether the move still clears
    MIN_MOVE_FROM_PREV_CLOSE_PCT. Stale price, stale verdict."""
    row = {"symbol": "ANTELOPUS", "ltp": 100.0, "change_pct": 0.0}
    price_now(row, _tick(107.0, prev=100.0))
    assert round(row["change_pct"], 2) == 7.0


def test_the_days_high_only_widens():
    """The extremes can only widen. REST drops symbols and the feed
    reconnects, so take the wider of the two rather than trusting
    either source alone."""
    row = {"symbol": "X", "ltp": 100.0, "day_high": 110.0, "day_low": 95.0}
    price_now(row, _tick(101.0, high=105.0, low=99.0))
    assert row["day_high"] == 110.0        # snapshot's was higher
    assert row["day_low"] == 95.0          # snapshot's was lower


def test_liveness_is_re_asked_on_the_live_price():
    """The whole point. The fading gate ran on a 42-second-old
    picture. A stock that has rolled over since must read fading
    BEFORE the order goes in, not after."""
    row = {"symbol": "X", "ltp": 100.0, "day_high": 100.0, "day_low": 90.0,
           "change_pct": 8.0, "recent_pct": 2.0, "state": "alive"}
    price_now(row, _tick(96.0, prev=92.6, high=100.0, low=90.0))
    assert row["state"] == "fading", (
        "4% off its high and still reading alive -- the gate judged "
        "the snapshot, not the stock")


def test_no_tick_leaves_the_row_exactly_as_it_was():
    """A missing reading means nothing. It must never be read as a
    better price, and it must not blank a row the ranker built."""
    row = {"symbol": "X", "ltp": 100.0, "change_pct": 5.0, "state": "alive"}
    before = dict(row)
    price_now(row, lambda sym: None)
    assert row == before
    price_now(row, None)
    assert row == before


def test_a_broken_tick_is_ignored_rather_than_believed():
    """Zero, negative and unparseable are not prices."""
    for bad in (0, -5, "n/a", None):
        row = {"symbol": "X", "ltp": 100.0}
        price_now(row, lambda sym: {"LTP": bad, "close": 95.0})
        assert row["ltp"] == 100.0


def test_main_hands_the_tick_store_in():
    """Asserted on the source: an un-wired price_of is silently the
    old behaviour, which is the failure this whole file is about."""
    with open("main.py", encoding="utf-8") as fh:
        body = fh.read()
    call = body[body.index("auto_entry.take("):][:900]
    assert "price_of=tick_ohlc.of" in call
