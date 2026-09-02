"""---- 30% OF THE UNIVERSE WAS INVISIBLE. 2 September 2026. ----

    "last time we both agreed to make all stock universe tradeable &
     you said task done and gave some 1300 or something number of
     stocks , but today you r telling 900 stocks."
                                                -- the operator

He is right and my earlier report was wrong in the way that matters. I
verified the layer I had worked on -- 1,282 symbols subscribed to the
tick feed -- and reported the universe done. I never checked whether
the layer that RANKS stocks receives all 1,282. It does not.

The quote snapshot goes out in two batches, 900 + 382. The loop used to
BREAK on a failed batch and then report status "success", because
status had already been set by the first batch:

    [CIRCUIT_MONITOR] 1282 symbols checked, 1282 rows cached
    [GL] 900 rows from 900 symbols. Skipped: all zero

Every counter said whole. Measured across the two sessions on record:

    2 Sep    843 of 854 cycles ran on 900 stocks
    1 Sep    596 of 618 cycles ran on 899

Thirty percent of the universe, absent all day, both days -- and the
bot cannot refuse a stock it has never been shown. Of the eleven
stocks he watched close above +10% that day, FIVE were subscribed and
simply not on the board: ANTELOPUS, INDOCO, XPROINDIA, BODALCHEM,
MOREPENLAB.

THREE THINGS CHANGED.

    the batches are independent -- one failing no longer abandons the
    rest, which is what threw away the last 382 every cycle

    each batch gets ONE retry, because the failures on record are
    transient (aborted connections, resets, DNS blips on api.dhan.co),
    not refusals

    a short board SAYS SO. A partial snapshot is invisible otherwise:
    the missing stocks do not exist, every skip counter reads zero, and
    the market looks like it had nothing in it.
"""

import pytest

import core.circuit_monitor as cm
from core.circuit_monitor import CircuitMonitor

UNIVERSE = {str(i): f"SYM{i}" for i in range(1282)}


@pytest.fixture
def said(monkeypatch):
    lines = []
    monkeypatch.setattr(cm, "warn", lines.append)
    monkeypatch.setattr(cm, "decision", lines.append)
    monkeypatch.setattr(cm, "when_it_changes",
                        lambda key, msg, how=None: lines.append(msg))
    return lines


def _monitor(fails):
    """fails = set of CALL numbers that come back a failure."""
    calls = {"n": 0}

    def quote(req):
        calls["n"] += 1
        ids = list(req.values())[0]
        if calls["n"] in fails:
            return {"status": "failure", "remarks": "connection reset"}
        return {"status": "success", "data": {"data": {"NSE_EQ": {
            str(i): {"last_price": 100.0, "upper_circuit_limit": 120.0,
                     "lower_circuit_limit": 80.0, "open": 99.0,
                     "high": 101.0, "low": 98.0, "close": 99.5,
                     "volume": 1000} for i in ids}}}}

    m = CircuitMonitor(quote_fn=quote, exchange_segment="NSE_EQ")
    m.set_universe(UNIVERSE)
    return m, calls


def _short(lines):
    return [x for x in lines if "SHORT" in str(x)]


def test_a_transient_failure_no_longer_costs_382_stocks(said):
    """The whole point. One dropped packet used to cost 30% of the
    market for that cycle."""
    m, calls = _monitor({2})
    m.poll_once()
    assert calls["n"] == 3, "the failed batch was not retried"
    assert not _short(said), said


def test_a_failed_first_batch_no_longer_abandons_the_second(said):
    """`break` meant one early failure threw away everything after it."""
    m, calls = _monitor({1})
    m.poll_once()
    assert not _short(said), said


def test_a_batch_that_fails_twice_is_reported_loudly(said):
    """It must never look like a market with nothing in it."""
    m, _ = _monitor({2, 3})
    m.poll_once()
    hit = _short(said)
    assert hit, "a 900-of-1282 board passed silently"
    assert "900" in hit[0] and "1,282" in hit[0] and "382" in hit[0], hit[0]


def test_it_says_the_stocks_are_ABSENT_not_refused(said):
    """The distinction that cost a day of debugging: a stock the bot
    never saw leaves no refusal, so every counter reads zero and the
    absence is invisible."""
    m, _ = _monitor({2, 3})
    m.poll_once()
    assert "absent" in _short(said)[0], _short(said)[0]


def test_recovery_is_announced_too(said):
    """A shortfall that is said once must also be un-said, or a fixed
    board still reads as broken."""
    m, _ = _monitor(set())
    m.poll_once()
    assert any("complete again" in str(x) for x in said), said


def test_it_does_not_retry_for_ever(said):
    """One retry, not a loop. This runs every few seconds against a
    rate-limited endpoint."""
    m, calls = _monitor({1, 2, 3, 4, 5, 6})
    m.poll_once()
    assert calls["n"] == 4, f"two batches should cost at most 4 calls, got {calls['n']}"


def test_a_healthy_poll_costs_exactly_two_calls(said):
    """The retry must not fire when nothing is wrong."""
    m, calls = _monitor(set())
    m.poll_once()
    assert calls["n"] == 2, calls["n"]
