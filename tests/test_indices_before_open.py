"""
==========================================================
The indices do not wait for 09:15
==========================================================

    "what about indices data. why we need to wait till 09:15"
                                    -- operator, 4 August 2026

There was no good answer. IndexMonitor fills from the WebSocket tick
feed, and the first tick of the day arrives at the open -- so NIFTY,
BANKNIFTY, VIX and all fourteen sector tiles read "no feed" for the
entire hour he spends deciding what to trade. The pre-open book, the
gap list, the world numbers and the awareness tile were all live in
that hour; the indices were the one blank.

Dhan's REST quote endpoint answers outside market hours. It is how
tools/check_index_levels.py verified every security id after the close
on 3 August. main.py already hands quote_data to the circuit monitor,
so the callable was one argument away the whole time.

THE TICK ALWAYS WINS
--------------------
Once the feed is running its number is the truth, and a REST close must
never overwrite it. The fallback only fills entries the monitor has
marked unavailable, and what it fills is flagged from_rest so a close
can never be read as a live price.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from config import INDEX_INSTRUMENTS
from dashboard.state import DashboardState


def quote(req):
    """Dhan's REAL reply shape -- TWO "data" keys deep.

    ---- WHY THIS FIXTURE IS THE POINT OF THE FILE. 4 August 2026. ----

        "why NIFTY & other shows no feed ? whats the issue."

    The first version of this fixture was single-nested, because that
    is what I assumed. The parser matched the fixture, every test
    passed, and the tiles said "no feed" all day -- the fallback
    returned {} on every single call.

    tools/check_index_levels.py had the answer in a comment the whole
    time: "Two 'data' keys deep -- Dhan's HTTP wrapper nests the API
    body." core/circuit_monitor.py documents the same shape.

    A fixture invented rather than copied from working code tests
    nothing but the invention.
    """
    assert list(req) == ["IDX_I"], req
    return {"status": "success", "data": {"data": {"IDX_I": {
        "13": {"last_price": 24774.30, "ohlc": {"close": 24670.0}},
        "25": {"last_price": 58247.95, "ohlc": {"close": 58067.0}},
        "21": {"last_price": 11.93, "ohlc": {"close": 12.15}},
    }}}}


class Monitor:
    def __init__(self, live=None):
        self.live = live or {}

    def snapshot(self):
        out = {name: {"ltp": None, "prev_close": None, "pct": None,
                      "available": False}
               for name in INDEX_INSTRUMENTS.values()}
        out.update(self.live)
        return out


def state(monitor=None, quoter=quote):
    st = DashboardState.__new__(DashboardState)
    st.index_monitor = monitor if monitor is not None else Monitor()
    st._index_quote = quoter
    st._idx_rest = {}
    st._idx_rest_at = 0.0
    return st


# ---------------------------------------------------------------
# 1. FILLED BEFORE THE OPEN
# ---------------------------------------------------------------
def test_the_tiles_carry_the_last_close_before_any_tick():
    got = state().indices()
    assert got["nifty"]["ltp"] == 24774.30
    assert got["nifty"]["pct"] == 0.42
    assert got["banknifty"]["available"] is True
    assert got["vix"]["pct"] == -1.81


def test_what_came_from_rest_says_so():
    """A close must never be read as a live price."""
    assert state().indices()["nifty"]["from_rest"] is True


def test_a_sector_index_is_filled_too():
    """All fourteen were blank, not just the three headline tiles."""
    def sectors(req):
        return {"status": "success", "data": {"data": {"IDX_I": {
            "29": {"last_price": 41230.0, "ohlc": {"close": 40980.0}}}}}}
    got = state(quoter=sectors).indices()
    assert got["sector:IT"]["ltp"] == 41230.0


# ---------------------------------------------------------------
# 2. THE TICK ALWAYS WINS
# ---------------------------------------------------------------
def test_a_live_tick_is_never_overwritten_by_a_close():
    live = {"nifty": {"ltp": 24810.0, "prev_close": 24670.0, "pct": 0.57,
                      "available": True}}
    got = state(Monitor(live)).indices()
    assert got["nifty"]["ltp"] == 24810.0
    assert "from_rest" not in got["nifty"]


def test_nothing_is_asked_when_every_index_is_live():
    asked = {"n": 0}

    def counting(req):
        asked["n"] += 1
        return {}

    live = {name: {"ltp": 1.0, "prev_close": 1.0, "pct": 0.0,
                   "available": True} for name in INDEX_INSTRUMENTS.values()}
    state(Monitor(live), counting).indices()
    assert asked["n"] == 0


def test_the_quote_is_throttled():
    """The tiles redraw every second. Dhan must not be asked every
    second."""
    asked = {"n": 0}

    def counting(req):
        asked["n"] += 1
        return quote(req)

    st = state(quoter=counting)
    for _ in range(5):
        st.indices()
    assert asked["n"] == 1
    assert st.INDEX_REST_SECONDS >= 10


# ---------------------------------------------------------------
# 3. IT NEVER TAKES THE SCREEN DOWN
# ---------------------------------------------------------------
def test_a_failed_quote_leaves_the_monitor_alone():
    def boom(req):
        raise RuntimeError("no route")

    got = state(quoter=boom).indices()
    assert got["nifty"]["available"] is False


def test_no_quote_callable_is_the_old_behaviour():
    got = state(quoter=None).indices()
    assert got["nifty"]["available"] is False


def test_a_broken_monitor_does_not_raise():
    class Boom:
        def snapshot(self):
            raise RuntimeError("locked")

    assert state(Boom()).indices() == {}


def test_junk_in_the_reply_is_skipped_not_guessed():
    def junk(req):
        return {"status": "success", "data": {"data": {"IDX_I": {
            "13": {"last_price": "n/a"}, "9999": {"last_price": 1.0}}}}}
    got = state(quoter=junk).indices()
    assert got["nifty"]["available"] is False       # unparseable price
    assert "9999" not in got                        # unknown id


def test_the_real_double_nested_shape_is_the_one_that_must_work():
    """THE REGRESSION GUARD.

    Dhan sends raw["data"]["data"][segment][id]. The parser read one
    level, returned {} on every call, and the tiles said "no feed" all
    day while every test passed -- because the fixture was invented in
    the shape I assumed.

    This pins the shape explicitly, copied from
    tools/check_index_levels.py, which had it right all along.
    """
    real = {"status": "success",
            "data": {"data": {"IDX_I": {"13": {"last_price": 24774.30}}}}}
    got = state(quoter=lambda req: real).indices()
    assert got["nifty"]["available"] is True
    assert got["nifty"]["ltp"] == 24774.30


def test_a_single_nested_reply_is_tolerated_too():
    """Deliberate: if Dhan ever flattens the wrapper, the tiles keep
    working rather than silently emptying. Tolerance is the point --
    but the DOUBLE-nested shape above is the one that must never break
    again."""
    flat = {"data": {"IDX_I": {"13": {"last_price": 24774.30}}}}
    assert state(quoter=lambda req: flat).indices()["nifty"]["ltp"] == 24774.30


def test_a_refusal_is_not_read_as_prices():
    def refused(req):
        return {"status": "failure", "remarks": "bad token", "data": ""}
    assert state(quoter=refused).indices()["nifty"]["available"] is False


def test_a_missing_previous_close_still_gives_the_level():
    def no_prev(req):
        return {"status": "success", "data": {"data": {"IDX_I": {
            "13": {"last_price": 24774.30}}}}}
    got = state(quoter=no_prev).indices()
    assert got["nifty"]["ltp"] == 24774.30
    assert got["nifty"]["pct"] is None              # not faked as 0.00


# ---------------------------------------------------------------
# 4. IT IS ACTUALLY WIRED
# ---------------------------------------------------------------
def test_main_hands_the_dashboard_the_same_quote_the_circuit_monitor_uses():
    src = open("main.py", encoding="utf-8").read()
    assert "index_quote=dhan_rest_client.quote_data," in src
    assert "CircuitMonitor(dhan_rest_client.quote_data" in src


def test_every_index_reader_goes_through_the_fallback():
    """Four call sites read index_monitor.snapshot() directly. Any one
    of them left behind would keep showing 'no feed'."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    code = "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))
    # Only the fallback itself may call the monitor directly.
    assert code.count("self.index_monitor.snapshot()") == 1
    assert "self.indices()" in code
