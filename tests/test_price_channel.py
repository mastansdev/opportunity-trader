"""
==========================================================
Prices at tick speed, not at snapshot speed
==========================================================

    "ABSOLUTELY - LATENCY FIRST even today i got confused no of times
     & felt that lag on price observations"
                                    -- operator, 4 August 2026

WHAT WAS ACTUALLY WRONG
-----------------------
Not the feed. Ticks land in MarketData the moment Dhan sends them.
Everything AFTER the feed was slow:

    tick  ->  snapshot rebuilt on a 1s timer      (main.py)
          ->  page polls that snapshot every 2s   (screen.html)
          ->  the whole board's HTML rebuilt

So a price on his screen could be three seconds behind the Dhan app
open next to it. Correct, and stale -- the worst combination, because
a stale number looks exactly like a current one. He said he got
confused "no of times", on live money.

WHY A SECOND CHANNEL AND NOT A FASTER /ws
-----------------------------------------
Rebuilding the full snapshot four times a second means breadth, sector
maths and gainers/losers four times a second, in the same process that
has to place his orders. The rule has always been that the dashboard
must never slow the engine.

So the expensive channel stays at 1s and a cheap one runs at 250ms
reading nothing but market_data's price dict.

Author : H&M Opportunity Trader
==========================================================
"""

import warnings

import pytest
from fastapi.testclient import TestClient

from core.market_data import MarketData
from dashboard.server import build_app

warnings.filterwarnings("ignore")


def _executable(path):
    """The file with every comment removed.

    I have asserted against prose in a comment five times on this
    project and been wrong five times -- most recently here, where the
    string "/api/snapshot" survived in a design note explaining why the
    page NO LONGER uses it. Line comments are not enough: this file
    carries block comments and HTML comments too.
    """
    import re
    src = open(path, encoding="utf-8").read()
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("//"))


class _Loader:
    def known_symbols(self):
        return {"TCS", "INFY"}

    def sector_of(self, symbol):
        return None

    def blocked_symbols(self):
        return {}


def _client(market_data):
    class Engine:
        pass

    engine = Engine()
    engine.market_data = market_data

    class State:
        def __init__(self):
            self.engine = engine

        def snapshot(self):
            return {}

        def get_snapshot(self):
            return {"ready": True}

        def force_gainers_losers_refresh(self):
            pass

    return TestClient(build_app(State(), None, _Loader(), operator_token="T"))


# ---------------------------------------------------------------
# 1. THE DICT COMES OUT WHOLE, AND IT COMES OUT A COPY
# ---------------------------------------------------------------
def test_latest_prices_returns_every_live_price():
    md = MarketData()
    md._latest_price.update({"TCS": 3345.8, "INFY": 1500.0})
    assert md.latest_prices() == {"TCS": 3345.8, "INFY": 1500.0}


def test_it_hands_out_a_copy_not_the_live_dict():
    """A caller iterating the real dict while a tick thread writes to
    it is a RuntimeError mid-session, on the one path that must never
    break."""
    md = MarketData()
    md._latest_price["TCS"] = 100.0
    out = md.latest_prices()
    out["TCS"] = 999.0
    out["JUNK"] = 1.0
    assert md.get_latest_price("TCS") == 100.0
    assert "JUNK" not in md.latest_prices()


def test_an_empty_feed_is_an_empty_dict_not_a_crash():
    assert MarketData().latest_prices() == {}


# ---------------------------------------------------------------
# 2. IT PUSHES ONLY WHAT MOVED
# ---------------------------------------------------------------
def test_only_changed_prices_are_sent():
    """Re-sending 900 unchanged numbers four times a second is how a
    'fast' channel becomes the slow one."""
    md = MarketData()
    with _client(md).websocket_connect("/ws/prices") as ws:
        md._latest_price["TCS"] = 3345.8
        ws.receive_json()                      # opening frame
        first = None
        for _ in range(4):                     # the tick lands on a frame
            got = ws.receive_json()
            if got:
                first = got
                break
        assert first == {"TCS": 3345.8}

        md._latest_price["INFY"] = 1500.0
        second = None
        for _ in range(4):
            got = ws.receive_json()
            if got:
                second = got
                break
        # TCS did not move, so TCS is not in the frame.
        assert second == {"INFY": 1500.0}


def test_a_quiet_market_still_sends_a_heartbeat():
    """"Nothing moved" and "the socket is dead" must never look the
    same on screen. That is the frozen-board bug he reported: prices
    that stopped updating while still looking current."""
    md = MarketData()
    md._latest_price["TCS"] = 100.0
    with _client(md).websocket_connect("/ws/prices") as ws:
        seen = [ws.receive_json() for _ in range(5)]
    assert {} in seen, seen


def test_a_price_that_moves_back_is_still_a_change():
    md = MarketData()
    with _client(md).websocket_connect("/ws/prices") as ws:
        ws.receive_json()
        md._latest_price["TCS"] = 100.0
        for _ in range(4):
            if ws.receive_json():
                break
        md._latest_price["TCS"] = 101.0
        for _ in range(4):
            if ws.receive_json():
                break
        md._latest_price["TCS"] = 100.0
        back = None
        for _ in range(4):
            got = ws.receive_json()
            if got:
                back = got
                break
        assert back == {"TCS": 100.0}


# ---------------------------------------------------------------
# 3. IT NEVER TOUCHES THE SNAPSHOT BUILDER
# ---------------------------------------------------------------
def test_the_price_channel_does_not_rebuild_the_snapshot():
    """The whole reason for a second channel. If this ever calls
    get_snapshot() it has quietly become the expensive one, running
    four times a second, in the process that places his orders."""
    md = MarketData()
    calls = []

    class Engine:
        pass

    engine = Engine()
    engine.market_data = md

    class State:
        def __init__(self):
            self.engine = engine

        def get_snapshot(self):
            calls.append(1)
            return {"ready": True}

        def snapshot(self):
            return {}

        def force_gainers_losers_refresh(self):
            pass

    client = TestClient(build_app(State(), None, _Loader(),
                                  operator_token="T"))
    with client.websocket_connect("/ws/prices") as ws:
        md._latest_price["TCS"] = 100.0
        for _ in range(4):
            ws.receive_json()
    assert calls == [], "the price channel rebuilt the snapshot"


def test_a_missing_market_data_does_not_kill_the_socket():
    """Before the feed thread is up, engine.market_data can be None.
    That must be an empty frame, never a dropped connection -- a page
    that has to reconnect at 09:15 is a page that is red at 09:15."""
    class State:
        engine = None

        def get_snapshot(self):
            return {}

        def snapshot(self):
            return {}

        def force_gainers_losers_refresh(self):
            pass

    client = TestClient(build_app(State(), None, _Loader(),
                                  operator_token="T"))
    with client.websocket_connect("/ws/prices") as ws:
        assert ws.receive_json() == {}


# ---------------------------------------------------------------
# 4. THE CADENCE IS DELIBERATE
# ---------------------------------------------------------------
def test_the_price_cadence_is_faster_than_the_snapshot():
    from config import (DASHBOARD_REFRESH_INTERVAL_SECONDS,
                        PRICE_PUSH_SECONDS)
    assert PRICE_PUSH_SECONDS < DASHBOARD_REFRESH_INTERVAL_SECONDS


def test_it_is_not_pushed_faster_than_a_browser_can_paint():
    """Below ~200ms there is nothing left to gain but CPU burnt in the
    trading process."""
    from config import PRICE_PUSH_SECONDS
    assert PRICE_PUSH_SECONDS >= 0.2


# ---------------------------------------------------------------
# 5. THE PAGE ACTUALLY USES IT
# ---------------------------------------------------------------
def test_the_price_channel_is_still_served():
    """---- THE PAGE THAT CONSUMED IT IS GONE. 13 Aug 2026. ----

    These two tests checked dashboard/static/screen.html for a
    websocket price push and addressable `data-px` cells. screen.html
    was deleted when four dashboards became two.

    THE SERVER SIDE IS UNCHANGED and is what this now guards: /ws and
    /ws/prices still exist, so the channel is there for whichever page
    wants it.

    THE CONSUMER IS THE GAP. board.html -- the screen he trades from --
    polls /api/snapshot every 3 seconds and rebuilds. That was true
    before this deletion; screen.html was the only page that pushed,
    and he was not using it. See
    test_the_trading_screen_still_polls_rather_than_listens below,
    which records it rather than pretending otherwise.

    His own words on why it matters: "a stale number looks exactly
    like a current one", and he got confused "no of times", on live
    money.
    """
    server = open("dashboard/server.py", encoding="utf-8").read()
    assert '"/ws/prices"' in server, "the price channel itself is gone"
    assert '"/ws"' in server


def test_the_trading_screen_still_polls_rather_than_listens():
    """A KNOWN GAP, recorded so it is not rediscovered by surprise.

    Delete this test the day /board opens the websocket -- it will
    fail then, which is the point.
    """
    board = open("dashboard/static/board.html", encoding="utf-8").read()
    assert "/ws/prices" not in board, (
        "/board now listens on the price channel -- good. Remove this "
        "test and assert the push directly.")
    assert "setInterval(tick" in board, (
        "the board no longer polls either, so nothing updates its "
        "prices at all")
