"""A slow rebuild outlived its own cache and made itself slower.

    "fix the movers panel next"     -- the operator, 4 September 2026

Measured from his own logs, 4 September:

    rebuilds  slowest  median    worst panels (median)
         324   487.5s   58.9s    ranked 26.6s, movers 24.9s, shortlist 14.4s

_build_shortlist() is guarded by a 30-SECOND TIMER. _build() calls it
near the top for the shortlist panel, and build_movers() asks for it
again further down the SAME build. With a median build of 58.9
seconds, the timer has expired by the time movers asks -- so movers
rebuilt the entire shortlist from scratch, inside the snapshot that
had just built it.

That is a vicious circle, not merely waste: a slow build outlives its
cache, which makes the build slower, which makes it outlive the cache
by more. movers reached 72.5 seconds.

It was also quietly WRONG. Two panels in one snapshot could show two
different shortlists, taken half a minute apart, with nothing saying
so -- the same class of bug _compute_gl_rows() was fixed for on
2 September, whose comment reads: "a build that takes twenty seconds
must not recompute halfway through". That reasoning was never carried
one function across.

So the shortlist is now computed ONCE per build and shared, and the
30-second timer keeps doing its other job: not rebuilding on every
one-second refresh.
"""

import dashboard.state as state_mod
from dashboard.state import DashboardState


class _Counter:
    """Stands in for the real screener and counts how often it runs."""

    def __init__(self):
        self.runs = 0

    def rank(self, _rows, top=None):
        self.runs += 1
        return {"rows": [{"symbol": f"RUN{self.runs}"}], "thin": [],
                "scanned": 1, "built_at": "09:20:00"}


def _state(counter):
    """A DashboardState with only the parts _build_shortlist touches."""
    state = object.__new__(DashboardState)
    state._shortlist = counter
    state._shortlist_cache = None
    state._shortlist_built_at = 0.0
    state._shortlist_this_build = None
    state._gl_rows_this_build = []          # _compute_gl_rows short-circuits
    return state


def test_the_second_ask_inside_one_build_does_not_rebuild():
    """THE fix. Both asks are in the same build, so both get the same
    shortlist however long the build has taken."""
    counter = _Counter()
    state = _state(counter)
    first = state._build_shortlist()
    second = state._build_shortlist()
    assert counter.runs == 1, "the shortlist was built twice in one build"
    assert first is second


def test_an_expired_timer_cannot_rebuild_mid_BUILD(monkeypatch):
    """The exact 4 September case: the build outlives the 30-second
    timer. Before the fix this rebuilt; now the per-build cache wins."""
    counter = _Counter()
    state = _state(counter)
    state._build_shortlist()

    # pretend a very slow build: the timer is long gone
    monkeypatch.setattr(state_mod.time, "monotonic",
                        lambda: state._shortlist_built_at + 10_000)
    again = state._build_shortlist()
    assert counter.runs == 1, (
        "an expired timer rebuilt the shortlist in the middle of a "
        "build -- the vicious circle is back")
    assert again["rows"][0]["symbol"] == "RUN1"


def test_a_new_build_gets_a_fresh_shortlist_when_the_timer_has_passed(monkeypatch):
    """The cache must not span builds -- that would be a stale board,
    which is the opposite problem and just as bad."""
    counter = _Counter()
    state = _state(counter)
    state._build_shortlist()

    state._shortlist_this_build = None            # what _build() does
    monkeypatch.setattr(state_mod.time, "monotonic",
                        lambda: state._shortlist_built_at + 10_000)
    fresh = state._build_shortlist()
    assert counter.runs == 2
    assert fresh["rows"][0]["symbol"] == "RUN2"


def test_a_new_build_inside_the_timer_still_reuses_the_answer():
    """The 30-second throttle keeps its other job: main.py asks for a
    snapshot every second and must not rescreen the market each time."""
    counter = _Counter()
    state = _state(counter)
    state._build_shortlist()
    state._shortlist_this_build = None            # next build
    state._build_shortlist()
    assert counter.runs == 1


def test_the_build_clears_it_so_two_builds_never_share(monkeypatch):
    """Asserted on _build() itself: if the reset line is ever dropped,
    the board freezes on the first shortlist of the session."""
    import inspect
    src = inspect.getsource(DashboardState._build)
    assert "self._shortlist_this_build = None" in src, (
        "_build() no longer clears the per-build shortlist -- every "
        "later build would reuse the first one forever")
