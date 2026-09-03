"""---- YESTERDAY'S TICK CAME BACK AS TODAY'S PRICE. 3 Sep 2026 ----

    "Duplicates of data is not acceptable at all"    -- the operator

On 3 September the board carried ANTELOPUS twice at the same minute:

    live rows    951.15 .. 1063.10, moving all day, sector OIL & GAS
    stale rows   951.15 every row, +20.00%, frozen, no sector

951.15 is ANTELOPUS's PREVIOUS close and +20.00% was YESTERDAY's move.
2,247 symbol-minutes across 23 symbols carried more than one row, and
the ranker ranked the frozen copy at rank 6 while the live one sat at
rank 13.

THE CAUSE. core/tick_ohlc._latest is keyed by symbol and never
expires. reset() has existed since the file was written and a grep
finds no caller anywhere in the repo. dashboard/state._compute_gl_rows
backfills from it whenever the REST snapshot drops a stock -- which
that snapshot's own docstring says happens in 99% of sessions -- so a
dropped symbol was filled with its last tick from a previous session.

Nothing new is stored to fix it. remember() has always written
row["at"] as a full datetime; it was never read.

WHY IT IS NOT COSMETIC. The board he reads and the list the bot buys
from are the same rows, so a duplicate is a second and possibly stale
price the bot could size an order against.
"""

from datetime import datetime, timedelta

import core.tick_ohlc as tick_ohlc


def _put(symbol, when, close=100.0):
    tick_ohlc._latest[symbol] = {
        "open": 99.0, "high": 101.0, "low": 98.0, "close": close,
        "LTP": 100.5, "at": when,
    }


def test_a_tick_from_a_previous_session_is_not_served(monkeypatch):
    """THE BUG. ANTELOPUS's last tick from 2 September was handed out
    on 3 September as a live price."""
    tick_ohlc._latest.clear()
    _put("ANTELOPUS", datetime.now() - timedelta(days=1), close=792.625)
    assert tick_ohlc.of("ANTELOPUS") is None
    assert "ANTELOPUS" not in tick_ohlc.symbols()


def test_todays_tick_is_served_normally():
    """The guard must not empty the backfill. It exists for the moment
    REST is degraded, which is the one moment it has to work."""
    tick_ohlc._latest.clear()
    _put("HIKAL", datetime.now())
    assert tick_ohlc.of("HIKAL") is not None
    assert "HIKAL" in tick_ohlc.symbols()


def test_prev_close_inherits_the_guard():
    """prev_close() reads through of(), so a stale session cannot
    supply a previous close either."""
    tick_ohlc._latest.clear()
    _put("ANTELOPUS", datetime.now() - timedelta(days=1), close=792.625)
    assert tick_ohlc.prev_close("ANTELOPUS") is None


def test_a_row_with_no_timestamp_is_not_vouched_for():
    """A row that cannot say when it was recorded is not evidence that
    it is current. Missing means no, never yes."""
    tick_ohlc._latest.clear()
    tick_ohlc._latest["BROKEN"] = {"close": 100.0, "LTP": 100.0}
    assert tick_ohlc.of("BROKEN") is None


def test_the_ranked_list_carries_each_stock_once():
    """The guarantee, independent of the source. Asserted on the code
    because the failure is an ABSENT check, which no fixture can
    produce once the source is fixed."""
    with open("dashboard/state.py", encoding="utf-8") as fh:
        body = fh.read()
    start = body.index("ONE STOCK, ONE ROW")
    block = body[start:start + 1600]
    assert "seen_syms" in block
    assert 'got["rows"] = kept' in block
    assert "duplicate row(s) dropped" in block
