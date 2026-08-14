"""
==========================================================
One pass over the universe, not seven
==========================================================

    "the full dashboard has data some of that were struck at last time
     i used & still its showing the same data"
                                -- operator, 13 August 2026

It was not the page. Measured on the live 12:40 session:

    served_at   12:40:12 -> 12:40:31   moving
    updated_at  12:39:29 -> 12:39:29   FROZEN

`updated_at` is stamped when _build() RETURNS, so the snapshot was
being rebuilt roughly every two to three minutes while main.py asked
for one every second. Both screens were minutes behind a live market,
and /full showed it worst because it renders only what the websocket
pushes -- and swallows any render error, so stale and broken look
identical.

THE CAUSE
---------
The log showed [GL] eleven times in two seconds.
_compute_gl_rows() walks all 1,314 symbols, and its own docstring said
it was deliberately uncached because "each caller's own throttle
already controls how often this actually runs". True when it had TWO
callers, both throttled. It had grown to SEVEN, five with no throttle:
the shortlist, the movers, the extras.

THE FIX
-------
Compute once per build, share it. Cleared at the top of _build() so a
build never reuses the previous one's rows, and a build that takes
twenty seconds does not recompute halfway through.

It is also more honest: every caller in one snapshot now sees the SAME
rows instead of seven passes taken milliseconds apart disagreeing
about the same market.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest


class _Engine:
    """Counts how many times the expensive source is read."""

    def __init__(self):
        self.reads = 0

    def get_circuit_snapshot(self):
        self.reads += 1
        return {
            "TCS": {"prev_close": 100.0, "open": 101.0, "high": 104.0,
                    "low": 99.0, "last_price": 103.0, "volume": 1000,
                    "upper_circuit_limit": None, "lower_circuit_limit": None},
        }


class _Loader:
    def get_by_symbol(self, symbol):
        return {"SECTOR": "IT"}


class _MarketData:
    def get_latest_price(self, symbol):
        return 103.0


def _state():
    from dashboard.state import DashboardState

    st = DashboardState.__new__(DashboardState)
    st.engine = _Engine()
    st.master_loader = _Loader()
    st.market_data = _MarketData()
    st._gl_rows_this_build = None
    return st


def test_seven_callers_cost_one_pass():
    """THE REGRESSION. Eleven walks of 1,314 symbols in two seconds."""
    st = _state()
    for _ in range(7):
        st._compute_gl_rows()
    assert st.engine.reads == 1, (
        f"the universe was walked {st.engine.reads} times for one "
        f"build -- that is what put the dashboard minutes behind")


def test_every_caller_sees_the_same_rows():
    """Seven passes milliseconds apart disagreed about one market.
    Within a build they must agree."""
    st = _state()
    first = st._compute_gl_rows()
    second = st._compute_gl_rows()
    assert first is second


def test_a_new_build_does_not_reuse_the_last_one():
    """The cache is a per-build memo, not a timer. Stale rows served
    into the NEXT snapshot would be the very bug this fixes."""
    st = _state()
    st._compute_gl_rows()
    assert st.engine.reads == 1
    st._gl_rows_this_build = None        # what _build() does at its top
    st._compute_gl_rows()
    assert st.engine.reads == 2


def test_build_clears_the_memo_at_the_top():
    """If _build() ever stops clearing it, the dashboard freezes
    permanently instead of merely lagging -- a worse failure than the
    one being fixed."""
    import inspect

    from dashboard.state import DashboardState

    src = inspect.getsource(DashboardState._build)
    body = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "self._gl_rows_this_build = None" in body, (
        "_build() no longer clears the per-build row cache")
    # It must be cleared BEFORE anything can populate it.
    before = body.index("self._gl_rows_this_build = None")
    assert before < len(body) // 2, (
        "the cache is cleared late in _build(), so panels built before "
        "that point would still see the previous snapshot's rows")


def test_the_memo_survives_a_missing_attribute():
    """DashboardState is constructed with __new__ in several tests and
    tools. A missing attribute must read as 'no cache', never raise."""
    from dashboard.state import DashboardState

    st = DashboardState.__new__(DashboardState)
    st.engine = _Engine()
    st.master_loader = _Loader()
    st.market_data = _MarketData()
    # deliberately NOT setting _gl_rows_this_build
    assert st._compute_gl_rows() is not None
