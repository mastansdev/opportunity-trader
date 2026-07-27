"""
The recorder must not write bars from after the market has closed.

Operator-found live on 2026-07-27. I told the operator "MARKSANS fell
from Rs 263 to Rs 247" and used that to justify a ~Rs 12,000 swing in a
backtest result. It never fell. This is the actual tape:

    15:27   263.55  264.00  263.40  263.55    9,457
    15:28   263.55  264.40  263.40  263.40    7,767
    15:29   246.95  246.95  246.95  246.95    1,110   <- not a candle

One bar, open == high == low == close, minus 6.2%, no bar anywhere near
that price before or after it.

It was not an isolated print. Across the whole session file:

    minute   bars  o=h=l=c
    15:28     688        2      normal
    15:29     134      134      every one flat
    15:40..    32       32      post-market, every one flat

and all 67 one-minute moves bigger than 4% in that database occur at or
after 15:29. CARTRADE "fell" 11% at 15:50. TBZ "fell" 7.7% at 15:52 on
zero volume.

Cause: core/candle_engine.py closes a candle only when a tick lands in
the NEXT bucket. Real ticks stop at 15:30, so the tail of the session
gets closed -- much later -- by post-market snapshot prices that have
nothing to do with continuous trading.

Consequence, and the reason these tests exist: any backtest that reads
to end-of-day trades ghosts. This project has already been burned once
by a corrupt bar (INFY 1037 -> 111, a fake +Rs145,403 short) and once
by look-ahead. This is the same failure wearing a different hat.
"""

from datetime import datetime

import pytest

from config import RECORDER_LAST_MINUTE
from core.candle_recorder import CandleRecorder


class _Store:
    """Captures rows instead of writing them, so the test asserts on
    what WOULD have been persisted."""

    def __init__(self):
        self.rows = []

    class _Conn:
        def __init__(self, outer):
            self.outer = outer

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _stmt, batch):
            self.outer.rows.extend(batch)

    class _Engine:
        def __init__(self, outer):
            self.outer = outer

        def begin(self):
            return _Store._Conn(self.outer)

    @property
    def engine(self):
        return _Store._Engine(self)

    class _Table:
        def insert(self):
            return self

        def prefix_with(self, _):
            return self

    candles = _Table()


def _candle(hhmm, price=100.0, volume=1000.0):
    hh, mm = hhmm.split(":")
    return {
        "time": datetime(2026, 7, 27, int(hh), int(mm)),
        "open": price, "high": price, "low": price, "close": price,
        "volume": volume,
    }


def _recorded(*times):
    store = _Store()
    rec = CandleRecorder(store=store, flush_every=1)
    for t in times:
        rec.record("MARKSANS", _candle(t))
    rec.flush()
    return [r["minute"][11:] for r in store.rows]


def test_the_marksans_bar_is_never_written():
    """The exact bar that produced a wrong number for the operator."""
    assert _recorded("15:29") == [], \
        "the 15:29 ghost bar is still being recorded -- this is the bug"


def test_post_market_prints_are_never_written():
    """15:40-16:00 is the post-close session. 32 flat bars landed there
    on 2026-07-27, including CARTRADE at -11%."""
    assert _recorded("15:40", "15:50", "15:52", "15:59") == []


def test_real_session_bars_are_still_written():
    """The guard must cost exactly one minute and nothing else."""
    assert _recorded("09:15", "12:00", "15:14", "15:28") == \
        ["09:15", "12:00", "15:14", "15:28"]


def test_the_boundary_minute_itself_is_kept():
    assert _recorded(RECORDER_LAST_MINUTE) == [RECORDER_LAST_MINUTE]


def test_a_late_arriving_candle_is_judged_by_its_OWN_time():
    """A 15:20 candle that only closes at 15:45 is still a real 15:20
    candle. Judging by wall clock would throw away good data on a slow
    feed, and keep junk on a fast one."""
    assert _recorded("15:20") == ["15:20"]


def test_dropped_bars_are_counted_not_silently_swallowed():
    """A filter nobody can see is how the next silent data bug starts."""
    rec = CandleRecorder(store=_Store(), flush_every=1)
    rec.record("X", _candle("15:29"))
    rec.record("X", _candle("15:50"))
    rec.record("X", _candle("15:28"))
    assert rec._dropped_after_close == 2


def test_the_cutoff_is_inside_the_trading_session():
    """A cutoff after 15:30 would silently re-admit the post-market
    prints this exists to exclude."""
    assert "15:00" < RECORDER_LAST_MINUTE < "15:30", (
        f"RECORDER_LAST_MINUTE is {RECORDER_LAST_MINUTE}; outside the "
        f"continuous session this guard does nothing"
    )


@pytest.mark.parametrize("bad", ["15:29", "15:30", "15:35", "15:59"])
def test_every_minute_past_the_cutoff_is_refused(bad):
    assert _recorded(bad) == []
