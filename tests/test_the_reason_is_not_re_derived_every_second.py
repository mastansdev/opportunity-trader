"""The reason a stock is moving does not change every second.

Measured 29 August 2026 against the real stores: why() costs a median
15.1 ms a symbol, 105 symbols carry news on an ordinary day, and
dashboard_state.refresh() asked for all of them once per second. That
is 1,590 ms of a 1-second loop -- roughly 13,000 cycles between 09:15
and 15:30 instead of 22,500.

Nothing was missed by it. The reason set is rebuilt every cycle either
way, so news at 11:00 still made a stock a candidate. It meant every
entry landed a second or two later than it could have.

Two things are guarded here, and the second is the one that bites:

  1. a repeat inside the TTL does not re-derive
  2. the whole cache does not fall due on the same cycle

A flat TTL fills on one cycle and therefore expires on one cycle. That
turned a steady 1,590 ms into 0.3 ms for twenty-nine cycles and
5,372 ms for the thirtieth, which is worse than the average it fixed.
"""

from datetime import datetime

import pytest

import config
from core.stock_events import StockEvents
from dashboard.state import DashboardState


class _Stub(DashboardState):
    """Only the attributes _mechanism_for touches.

    Building a real DashboardState opens the broker, the feed and
    every store. This method reads three of them and nothing else.
    """

    def __init__(self):
        self.stock_events = None
        self.news_impact = None
        self.announcement_watcher = None


@pytest.fixture
def counted(monkeypatch):
    """A why() that answers instantly and counts how often it ran."""
    calls = []

    def _why(events=None, news_hits=None, symbol=None, filing=None,
             on_date=None):
        calls.append(str(symbol).upper())
        return {"text": f"reason for {symbol}", "weight": 0.6}

    monkeypatch.setattr("core.why_moving.why", _why)
    return calls


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock this test drives by hand."""
    now = {"t": 1000.0}
    monkeypatch.setattr("dashboard.state.time.monotonic", lambda: now["t"])
    return now


# ------------------------------------------------------- it caches

def test_the_same_symbol_is_not_re_derived_within_the_window(counted, clock):
    state = _Stub()
    first = state._mechanism_for("TESTCO")
    for _ in range(50):
        assert state._mechanism_for("TESTCO") == first
    assert counted == ["TESTCO"], "why() ran more than once inside the TTL"


def test_no_reason_is_cached_too(counted, clock, monkeypatch):
    """Most of the list has no reason, and None costs the same 15 ms."""
    monkeypatch.setattr("core.why_moving.why",
                        lambda **kw: counted.append(kw["symbol"]) or None)
    state = _Stub()
    assert state._mechanism_for("TESTCO") is None
    assert state._mechanism_for("TESTCO") is None
    assert len(counted) == 1


def test_it_re_derives_once_the_window_has_passed(counted, clock):
    state = _Stub()
    state._mechanism_for("TESTCO")
    clock["t"] += config.REASON_CACHE_SECONDS + 1
    state._mechanism_for("TESTCO")
    assert len(counted) == 2


def test_fresh_news_is_never_more_than_the_ttl_away(counted, clock):
    """His rule sets this number, so it is asserted, not assumed.

        "if 100 stocks were there at morning & by 11 5 stocks got
         news . then bot must include those stocks too"

    A stock is a candidate because this lookup says it has a reason.
    So the TTL IS the bot's reaction time to news, and no symbol may
    hold a stale answer for longer than it.
    """
    state = _Stub()
    names = [f"SYM{i}" for i in range(300)]
    for name in names:
        state._mechanism_for(name)
    lifetimes = [v[0] - clock["t"] for v in state._reason_cache.values()]
    assert max(lifetimes) <= config.REASON_CACHE_SECONDS
    assert min(lifetimes) > 0


# --------------------------------------------- and it does not stampede

def test_the_whole_cache_does_not_fall_due_on_one_cycle(counted, clock):
    """The fault a flat TTL introduces.

    Filled in one cycle, expiring in one cycle: 29 free cycles and one
    that pays for all of them. The lifetimes must spread.
    """
    state = _Stub()
    names = [f"SYM{i}" for i in range(300)]
    for name in names:
        state._mechanism_for(name)
    due = sorted(v[0] for v in state._reason_cache.values())
    spread = due[-1] - due[0]
    assert spread > config.REASON_CACHE_SECONDS * 0.2, (
        "every symbol expires at the same moment -- the stall is back")

    # No single second may carry more than a modest share of them.
    busiest = {}
    for when in due:
        second = int(when)
        busiest[second] = busiest.get(second, 0) + 1
    assert max(busiest.values()) < len(names) * 0.5


def test_a_symbol_keeps_the_same_lifetime_across_restarts(counted, clock):
    """Fixed by the name, not by chance.

    Randomising it would make two runs of the same session behave
    differently, and a timing bug that only appears sometimes is the
    kind this repo has spent whole days on.
    """
    first = _Stub()
    first._mechanism_for("TESTCO")
    life_a = first._reason_cache["TESTCO"][0] - clock["t"]

    second = _Stub()
    second._mechanism_for("TESTCO")
    life_b = second._reason_cache["TESTCO"][0] - clock["t"]
    assert life_a == life_b


# ------------------------------------------------------------ safety

def test_yesterdays_reason_is_not_served_today(counted, clock, monkeypatch):
    """A process that runs past midnight must not carry the day over."""
    state = _Stub()
    state._mechanism_for("TESTCO")
    assert len(counted) == 1
    monkeypatch.setattr(state, "_reason_cache_day", "1999-01-01")
    state._mechanism_for("TESTCO")
    assert len(counted) == 2


def test_the_cache_can_be_turned_off(counted, clock, monkeypatch):
    monkeypatch.setattr("dashboard.state.REASON_CACHE_SECONDS", 0)
    state = _Stub()
    for _ in range(5):
        state._mechanism_for("TESTCO")
    assert len(counted) == 5


def test_an_empty_symbol_is_not_cached_as_a_reason(counted, clock):
    state = _Stub()
    assert state._mechanism_for("") is None
    assert state._mechanism_for(None) is None
    assert counted == []


def test_the_cached_answer_is_the_one_it_would_have_computed():
    """Against the REAL stores, not a stub.

    A cache that returns something different from the function it
    stands in for is worse than no cache.
    """
    state = _Stub()
    state.stock_events = StockEvents()
    symbols = list(state.stock_events.symbols_with_events(hours=36))[:5]
    if not symbols:
        pytest.skip("no events stored to check against")
    for name in symbols:
        fresh = _Stub()
        fresh.stock_events = state.stock_events
        assert state._mechanism_for(name) == fresh._mechanism_for(name)
