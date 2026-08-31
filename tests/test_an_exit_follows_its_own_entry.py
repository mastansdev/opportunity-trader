"""---- THE STOP THAT WOULD HAVE OPENED A SHORT. 31 August 2026. ----

Execution._route sent every exit to the live executor, on the reasoning
that "a real position needs a real stop". That reasoning is sound and
still wins where nothing else is known. It is not the whole story.

The case it misses is an ordinary one: he flips the switch with a
position already open. The bot buys on paper in the morning, he likes
what he sees at noon and clicks ON. That morning's stock must still be
SOLD on paper.

Selling it for real would place a real SELL for stock he never bought.
In NSE cash intraday that is not a harmless no-op; it opens a real
short. The bot would then believe it was flat while carrying a live
short it had no plan for, no stop on, and no record of.

An exit goes wherever its entry went. That is not a third mode -- it is
the same two modes, remembered.
"""

import sqlite3

import pytest

from trading.execution import Execution


class _Executor:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def buy(self, security_id, symbol, price, qty, reason="", at_time=None):
        self.calls.append(("BUY", symbol))
        return {"ok": True}

    def sell(self, security_id, symbol, price, qty, reason="", at_time=None):
        self.calls.append(("SELL", symbol))
        return {"ok": True}


def _execution(live_switch):
    x = Execution.__new__(Execution)
    x.executor = _Executor("paper")
    x._live = _Executor("live")
    x._live_refused = None
    x.live = live_switch
    return x


def test_a_paper_entry_gets_a_paper_exit():
    """He flips the switch with a position already open.

    This is the only way a paper position and a live switch can coexist
    now, and it is a normal Tuesday: the bot buys on paper in the
    morning, he likes what he sees at noon and clicks ON. That
    morning's stock must still be SOLD on paper. Selling it for real
    would place a real SELL for stock he never bought -- an actual
    short position, in cash intraday, that the bot does not know it is
    carrying."""
    x = _execution(live_switch=False)
    x.buy("1", "ASHOKA", 100.0, 10, "RANKED_SETUP")
    assert x._opened_by["ASHOKA"] == "paper"

    x.live = True                      # he clicks ON at noon
    assert x._route("STOP_HIT", selling=True, symbol="ASHOKA") is x.executor


def test_a_live_entry_still_gets_a_live_exit():
    """The original concern, undamaged. His click is real, so its stop
    is real."""
    x = _execution(live_switch=True)
    x.buy("1", "TATASTEEL", 100.0, 10, "MANUAL_BUY")
    assert x._opened_by["TATASTEEL"] == "live"
    assert x._route("STOP_HIT", selling=True, symbol="TATASTEEL") is x._live


def test_an_unknown_symbol_still_exits_live():
    """Nothing on record means this is not a position this process
    opened. Failing to exit a real position is the worse of the two
    errors, so the old behaviour stands here unchanged."""
    x = _execution(live_switch=True)
    assert x._route("STOP_HIT", selling=True, symbol="NEVERSEEN") is x._live


def test_the_switch_off_sends_everything_to_paper():
    """OFF is a full paper day. No lookup should be able to change
    that -- not even a symbol whose last live fill is in the log."""
    x = _execution(live_switch=False)
    x.buy("1", "ASHOKA", 100.0, 10, "MANUAL_BUY")
    assert x._route("STOP_HIT", selling=True, symbol="ASHOKA") is x.executor


def test_a_restart_reads_the_fills_log(tmp_path, monkeypatch):
    """The case that matters most: the process dies mid-session and
    comes back with open positions and an empty dictionary. The stamp
    in data/fills.db is the only surviving record of which money each
    position was opened with."""
    db = tmp_path / "fills.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE fills (id INTEGER PRIMARY KEY, mode TEXT, "
                 "side TEXT, symbol TEXT)")
    conn.executemany("INSERT INTO fills (mode, side, symbol) VALUES (?,?,?)",
                     [("PAPER", "BUY", "ASHOKA"), ("LIVE", "BUY", "TATASTEEL")])
    conn.commit()
    conn.close()
    monkeypatch.setattr("core.fill_log.DB_PATH", str(db))

    x = _execution(live_switch=True)          # no _opened_by at all
    assert x._who_opened("ASHOKA") == "paper"
    assert x._who_opened("TATASTEEL") == "live"
    assert x._who_opened("NEVERSEEN") is None


def test_a_sell_reaches_the_right_executor_end_to_end():
    """_route is internal. This is the path the stop actually takes."""
    x = _execution(live_switch=False)
    x.buy("1", "ASHOKA", 100.0, 10, "RANKED_SETUP")
    x.live = True                      # he clicks ON while it is open
    x.sell("1", "ASHOKA", 95.0, 10, "STOP_HIT")
    assert ("SELL", "ASHOKA") in x.executor.calls
    assert ("SELL", "ASHOKA") not in x._live.calls
