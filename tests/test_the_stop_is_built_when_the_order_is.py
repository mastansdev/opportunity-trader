"""---- IT SOLD SBCL ONE SECOND AFTER BUYING IT. 4 Sep 2026. ----

    09:16:39  PAPER BUY  SBCL  qty=106 @ 1135.67
    09:16:40  TRAILING STOP HIT: SBCL stop=1144.80 price=1133.40
    09:16:40  PAPER SELL SBCL  qty=106 @ 1131.13        -Rs 481

The stop was 1144.80 on an entry of 1135.67 -- ABOVE it. A long whose
stop sits above its entry has already been stopped out before the
order fills.

1144.80 / 0.97 = 1180.20, which is where SBCL was before it fell into
the open. The stop came from row["plan"], and the plan is built by
dashboard/state._build() during the rebuild -- 50 to 344 seconds that
day, up to five minutes at worst.

WHY HALF A FIX MADE IT WORSE. price_now() began refreshing the ENTRY
price from the live tick on 3 September, and that worked. The plan was
left behind. So one number was current and the other was minutes old,
and they contradicted each other. When BOTH were stale they at least
agreed with each other; fixing only one created this.

So the plan is now rebuilt from the same price, at the same instant.
They cannot disagree because they come from one number.

AND A GUARD BENEATH IT. If a stop ever arrives on the wrong side again
by some other route, trailing_stop.start() clamps it to the standard
distance and says so loudly. Clamped rather than refused: by the time
that code runs the position is already open, and leaving it
unprotected would be worse than protecting it at the normal distance.
"""

from core.auto_entry import price_now


def _tick(ltp, prev, high, low):
    return lambda sym: {"LTP": ltp, "close": prev, "high": high, "low": low}


def _row(stale_plan_stop, stale_value):
    return {"symbol": "SBCL", "action": "BUY", "ltp": 1180.20,
            "day_high": 1215.70, "day_low": 1126.20,
            "plan": {"ok": True, "stop": stale_plan_stop, "qty": 106,
                     "value_rs": stale_value}}


def test_the_stop_is_rebuilt_from_the_price_being_paid():
    """THE BUG, with the day's real numbers. The plan says 1144.80 from
    when SBCL was 1180; the tick says 1135.67."""
    row = _row(1144.80, 106 * 1180.20)
    price_now(row, _tick(1135.67, 1103.0, 1215.70, 1126.20))
    assert row["ltp"] == 1135.67
    stop = row["plan"]["stop"]
    assert stop < row["ltp"], (
        "the stop is still above the entry -- 1135.67 bought against a "
        "stop of %.2f is already past its own exit" % stop)


def test_the_two_numbers_come_from_one_moment():
    """Not "the stop is lower" -- the stop must be derived from THIS
    price. A stop that happens to be below by luck is not the fix."""
    row = _row(1144.80, 106 * 1180.20)
    price_now(row, _tick(1135.67, 1103.0, 1215.70, 1126.20))
    assert row.get("plan_priced_from") == "tick"


def test_a_rebuild_that_fails_leaves_the_old_plan_standing():
    """A stale stop is bad. No plan at all refuses the trade outright,
    which is worse -- refuse_reason() drops a row with no plan."""
    row = _row(1144.80, 0)          # value_rs 0 -> margin cannot be recovered
    price_now(row, _tick(1135.67, 1103.0, 1215.70, 1126.20))
    assert row["plan"].get("ok") is True
    assert row["plan"].get("qty")


def test_no_tick_leaves_both_numbers_alone_together():
    """When the feed says nothing, price and plan stay old TOGETHER --
    which is not this bug. They agree with each other, and that is the
    property that matters."""
    row = _row(1144.80, 106 * 1180.20)
    before = dict(row["plan"])
    price_now(row, lambda sym: None)
    assert row["ltp"] == 1180.20
    assert row["plan"] == before


def test_the_guard_clamps_a_stop_on_the_wrong_side():
    """The second layer. If anything ever hands over a stop above the
    entry again, the position is protected at the standard distance
    rather than instantly closed."""
    from config import FIXED_STOP_PCT
    from core.trailing_stop import TrailingStopEngine
    t = TrailingStopEngine()
    t.start("SBCL", 1144.80, direction="LONG", entry_price=1135.67)
    got = t.get_stop("SBCL")
    assert got < 1135.67, "a long is still seeded with a stop above its entry"
    assert abs(got - 1135.67 * (1 - FIXED_STOP_PCT / 100.0)) < 0.01


def test_a_correct_stop_is_left_exactly_as_given():
    """The guard must not touch a good seed. Sizing already decided
    that distance and this is not the place to second-guess it."""
    from core.trailing_stop import TrailingStopEngine
    t = TrailingStopEngine()
    t.start("HIKAL", 216.30, direction="LONG", entry_price=223.02)
    assert t.get_stop("HIKAL") == 216.30
