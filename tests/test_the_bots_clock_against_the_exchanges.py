"""
==========================================================
Is the bot's clock the exchange's clock?
==========================================================

    "did u resolve the time delay, mis timing with nse/system time
     with bot time?"            -- the operator, 14 September 2026

Two causes of the lag he SAW were fixed that day: the board rebuild
freezing the main loop (heartbeats 85-100s apart), and the Telegram
column printing a tagged-UTC stamp raw (the 5h30m). Neither answered
this question, and nothing in the bot ever had.

Every tick carries LTT -- the exchange's own last-traded time -- and
received_at, this machine's clock, is captured beside it at enqueue.
They have sat together in the queue since the worker was written and
nothing had ever subtracted one from the other.

WHY IT MATTERS MORE THAN A DISPLAY. Every time rule the bot has reads
the machine clock: the ORB window, LAST_ENTRY_TIME 15:15, the
square-off, move age, "held 45 minutes" in the drift exit. If this
laptop drifts from NSE they are all wrong together, quietly, and the
bot goes on trading as though they were right.

WHAT THE NUMBER IS, stated rather than hidden: LTT is stamped by the
exchange when the trade printed, received_at is when this process took
the packet off the socket, so the gap is feed latency PLUS any clock
offset and the two cannot be separated from here. Steady and under a
couple of seconds is a healthy feed on a correct clock; minutes means
one of the two is wrong.

TWO FAULTS THIS FILE ALREADY CAUGHT, before it ever ran live:

  1. The first version lived inside main() and read two config names
     that were never imported -- a NameError only a live tick would
     have found. It is at module level now, which is why it is
     testable at all.
  2. "said" used 0.0 for BOTH "never reported" and a real timestamp,
     so a caller whose clock read 0.0 re-primed every tick and the
     line never came out. A sentinel that can collide with a real
     value is not a sentinel.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

import pytest

import main

TICK = datetime(2026, 9, 15, 10, 0, 0)


def _fresh():
    return {"worst": 0.0, "n": 0, "sum": 0.0, "said": None}


def _report(gap_seconds, ticks=30):
    """Drive it until it reports, and hand back the line."""
    state = _fresh()
    received = TICK + timedelta(seconds=gap_seconds)
    main._clock_watch(TICK, received, now=0.0, state=state)   # prime
    for _ in range(ticks):
        line = main._clock_watch(TICK, received, now=61.0, state=state)
        if line:
            return line
    return None


# ---------------------------------------------------------------
# IT MEASURES, AND IT SAYS WHICH WAY
# ---------------------------------------------------------------

def test_a_healthy_feed_reports_a_small_gap():
    line = _report(1.2)
    assert line and "+1.2s" in line


def test_a_drifting_clock_is_reported_in_full():
    """Five minutes out. This is the case the operator asked about."""
    line = _report(300)
    assert line and "+300.0s" in line


def test_it_says_which_way_the_offset_runs():
    """A number with no direction is not readable. Positive means this
    machine is behind the exchange."""
    assert "BEHIND the exchange" in _report(1.2)


def test_a_tick_stamped_in_the_future_reads_negative():
    """The offset can run the other way, and must not be hidden behind
    an absolute value."""
    line = _report(-2.0)
    assert line and "-2.0s" in line


def test_it_admits_what_the_number_contains():
    """Feed latency and clock offset cannot be separated from here, and
    the line says so rather than implying a clean clock reading."""
    line = _report(1.2)
    assert "Feed latency and clock offset" in line


# ---------------------------------------------------------------
# A DRIFT IS LOUD; A HEALTHY FEED IS NOT
# ---------------------------------------------------------------

def test_a_big_drift_warns_and_a_small_one_does_not(monkeypatch):
    said = []
    monkeypatch.setattr(main, "warn", lambda m: said.append(("warn", m)))
    monkeypatch.setattr(main, "diagnostic", lambda m: said.append(("diag", m)))
    _report(1.2)
    assert said and said[-1][0] == "diag", "a healthy feed must not cry wolf"
    said.clear()
    _report(300)
    assert said and said[-1][0] == "warn", "a 5-minute drift must be loud"


def test_the_threshold_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr("config.CLOCK_DRIFT_WARN_SECONDS", 0.1)
    said = []
    monkeypatch.setattr(main, "warn", lambda m: said.append("warn"))
    monkeypatch.setattr(main, "diagnostic", lambda m: said.append("diag"))
    _report(1.2)
    assert said[-1] == "warn"


# ---------------------------------------------------------------
# IT RUNS ON THE TICK WORKER AND MUST NEVER RAISE OR FLOOD
# ---------------------------------------------------------------

def test_missing_or_unusable_stamps_are_silent():
    for a, b in ((None, None), (TICK, None), (None, TICK),
                 ("not a time", "nor this"), (TICK, "x")):
        assert main._clock_watch(a, b, now=61.0, state=_fresh()) is None


def test_it_does_not_report_on_every_tick():
    """One line a minute, not one per tick -- 1,193 instruments are
    feeding this."""
    state = _fresh()
    received = TICK + timedelta(seconds=1.2)
    main._clock_watch(TICK, received, now=0.0, state=state)
    lines = [main._clock_watch(TICK, received, now=1.0, state=state)
             for _ in range(500)]
    assert not any(lines)


def test_it_waits_for_enough_ticks_to_mean_anything():
    """A single tick is not a measurement."""
    state = _fresh()
    received = TICK + timedelta(seconds=1.2)
    main._clock_watch(TICK, received, now=0.0, state=state)
    assert main._clock_watch(TICK, received, now=61.0, state=state) is None


def test_the_window_resets_after_it_reports():
    """Otherwise the worst-ever spike would be re-reported forever."""
    state = _fresh()
    received = TICK + timedelta(seconds=1.2)
    main._clock_watch(TICK, received, now=0.0, state=state)
    for _ in range(30):
        if main._clock_watch(TICK, received, now=61.0, state=state):
            break
    assert state["n"] == 0 and state["worst"] == 0.0


# ---------------------------------------------------------------
# THE TWO FAULTS IT ALREADY CAUGHT
# ---------------------------------------------------------------

def test_the_config_names_it_reads_actually_exist():
    """The first version read two names that were never imported -- a
    NameError only a live tick would have found."""
    import config
    assert isinstance(config.CLOCK_REPORT_SECONDS, (int, float))
    assert isinstance(config.CLOCK_DRIFT_WARN_SECONDS, (int, float))


def test_the_sentinel_cannot_collide_with_a_real_clock():
    """'said' must start as None. With 0.0 a caller whose clock read
    zero re-primed on every tick and the line never came out."""
    assert main._CLOCK["said"] is None


def test_it_is_wired_into_the_tick_worker():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "main.py").read_text(encoding="utf-8")
    assert "_clock_watch(tick_time, received_at, symbol=symbol)" in src


def test_a_stock_that_has_not_traded_does_not_count():
    """15 Sep 2026: +7.5s with an empty queue. A quiet stock's quote
    keeps its old last-trade time, so its gap grows every second."""
    state = _fresh()
    main._clock_watch(TICK, TICK + timedelta(seconds=1), now=0.0, state=state,
                      symbol="LIVELY")
    stale = datetime(2026, 9, 15, 9, 50, 0)
    line = None
    for i in range(40):
        t = TICK + timedelta(seconds=i + 1)
        main._clock_watch(t, t + timedelta(seconds=1), now=1.0, state=state,
                          symbol="LIVELY")
        # the same stale stamp, arriving again and again
        main._clock_watch(stale, TICK + timedelta(seconds=i), now=1.0,
                          state=state, symbol="QUIET")
    line = main._clock_watch(TICK + timedelta(seconds=50),
                             TICK + timedelta(seconds=51), now=61.0,
                             state=state, symbol="LIVELY")
    assert line and "+1.0s" in line, line


def test_one_stuck_stock_cannot_move_the_median():
    state = _fresh()
    received = TICK + timedelta(seconds=1)
    main._clock_watch(TICK, received, now=0.0, state=state)
    for _ in range(30):
        main._clock_watch(TICK, received, now=1.0, state=state)
    main._clock_watch(TICK, TICK + timedelta(seconds=900), now=1.0, state=state)
    line = main._clock_watch(TICK, received, now=61.0, state=state)
    assert "+1.0s" in line and "worst +900.0s" in line
