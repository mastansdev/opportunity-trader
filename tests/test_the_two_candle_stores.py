"""---- WHICH CANDLE STORE ANSWERS WHICH QUESTION. 31 Aug 2026 ----

The bot keeps two minute stores and they do not hold the same thing.
On 31 August I quoted the wrong one at the operator and told him
ATHERENERG closed at 1,649.00. It closed at 1,717.70.

    data/backtest_candles.db   written from the live tick feed.
                               THE CONTINUOUS SESSION ONLY.
    data/history_candles.db    fetched from Dhan's historical API.
                               Includes the CLOSING AUCTION.

Neither is wrong. They answer different questions:

    "what could we have traded at"     -> backtest_candles
    "what did it close at"             -> history_candles

F&O stocks leave continuous trading at 15:15 and finish in the closing
auction, so 209 of 1,288 stocks on 31 August have no backtest bar after
15:14 and a history bar at 15:30. That is the market, not a gap in the
data, and any analysis of "what happened after we exited" wants the
continuous store -- an auction price is not one the bot could have got.

DO THEY AGREE WHERE THEY OVERLAP
--------------------------------
Measured across 300 symbols on 31 August: 4,005 minutes differ at all,
and of those

    3,493 by less than 0.10%
      504 by 0.10 - 0.50%
        8 by more than 0.50%

which is the last tick of a minute against an API's own close. It is
not a disagreement about what happened. The test below holds it to
that, so a real divergence -- a feed writing into the wrong symbol, a
timezone slipping, a store going stale mid-session -- shows up as a
failure rather than as a number quietly quoted at him.
"""

import os
import sqlite3

import pytest

BACKTEST = os.path.join("data", "backtest_candles.db")
HISTORY = os.path.join("data", "history_candles.db")


def _latest_shared_day():
    if not (os.path.exists(BACKTEST) and os.path.exists(HISTORY)):
        return None
    try:
        b = sqlite3.connect(f"file:{BACKTEST}?mode=ro", uri=True)
        h = sqlite3.connect(f"file:{HISTORY}?mode=ro", uri=True)
        bd = {r[0] for r in b.execute("select distinct date from candles "
                                      "order by date desc limit 20")}
        hd = {r[0] for r in h.execute("select distinct date from candles "
                                      "order by date desc limit 20")}
        b.close(); h.close()
    except sqlite3.Error:
        return None
    shared = sorted(bd & hd)
    return shared[-1] if shared else None


def test_the_two_stores_agree_on_price_where_they_overlap():
    """Not "are they identical" -- they never will be, one is the last
    tick we saw and the other is an API's own close. The question is
    whether they are describing the same stock on the same day."""
    day = _latest_shared_day()
    if day is None:
        pytest.skip("both stores are not present on this machine")

    b = sqlite3.connect(f"file:{BACKTEST}?mode=ro", uri=True)
    h = sqlite3.connect(f"file:{HISTORY}?mode=ro", uri=True)
    symbols = [r[0] for r in b.execute(
        "select distinct symbol from candles where date=? limit 120", (day,))]

    checked = big = 0
    worst = (0.0, None, None)
    for symbol in symbols:
        bb = {r[0][11:16]: r[1] for r in b.execute(
            "select minute, c from candles where symbol=? and date=?",
            (symbol, day))}
        hh = {r[0][11:16]: r[1] for r in h.execute(
            "select minute, c from candles where symbol=? and date=?",
            (symbol, day))}
        for minute in set(bb) & set(hh):
            one, two = bb[minute], hh[minute]
            if not one or not two:
                continue
            checked += 1
            pct = abs(one - two) / two * 100.0
            if pct > worst[0]:
                worst = (pct, symbol, minute)
            if pct >= 2.0:
                big += 1
    b.close(); h.close()

    if not checked:
        pytest.skip("no overlapping minutes to compare")
    # 2% is far outside anything measured (the worst on 31 August was
    # 1.68%) and far inside "the two stores are describing different
    # things", which is what this is here to catch.
    assert big == 0, (
        f"{big} of {checked} shared minutes differ by 2% or more on "
        f"{day}. Worst: {worst[1]} at {worst[2]}, {worst[0]:.2f}%. The "
        f"stores are no longer describing the same tape.")


def test_the_continuous_store_is_the_one_that_stops_at_the_auction():
    """The distinction that made me quote a wrong close. If this ever
    inverts -- backtest running past 15:15, or history stopping at it --
    then every "what happened after we exited" number in day_report and
    why_not is measured against prices the bot could not have traded."""
    day = _latest_shared_day()
    if day is None:
        pytest.skip("both stores are not present on this machine")

    b = sqlite3.connect(f"file:{BACKTEST}?mode=ro", uri=True)
    h = sqlite3.connect(f"file:{HISTORY}?mode=ro", uri=True)
    b_last = b.execute("select max(minute) from candles where date=?",
                       (day,)).fetchone()[0]
    h_last = h.execute("select max(minute) from candles where date=?",
                       (day,)).fetchone()[0]
    b.close(); h.close()
    if not (b_last and h_last):
        pytest.skip("one store has no rows for that day")
    assert b_last[11:16] <= h_last[11:16], (
        "the tick-fed store now runs LATER than the API store. The "
        "continuous session cannot outlast the auction")


def test_the_analysis_tools_read_the_continuous_store():
    """day_report answers "what did the stock do after we exited",
    which is a question about prices the bot could have traded at. An
    auction close is not one of those."""
    from pathlib import Path

    for name in ("tools/day_report.py", "tools/why_not.py"):
        src = Path(name).read_text(encoding="utf-8")
        assert "backtest_candles" in src, (
            f"{name} is not reading the continuous store")
