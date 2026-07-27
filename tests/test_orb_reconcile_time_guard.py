"""
The opening range must not be re-widened hours after the opening.

Operator-found live on 2026-07-27, on TBZ. From that day's log:

    09:30:16  [ORB_FIX] TBZ 263.80/260.84 -> 263.80/260.39   correct
    10:36:10  [ORB_FIX] TBZ 263.80/260.39 -> 270.00/260.39   WRONG

263.80 is what the exchange itself publishes for 09:15-09:30, and it is
what the operator's chart showed. The 10:36 pass -- one minute after a
restart -- pulled the range high up by Rs 6.20.

Cause: `_orb_reconciled` is an in-memory set, so a restart empties it,
and the reconcile then re-ran against `circuit_monitor`'s DAY high/low.
The day high equals the opening-range high only at 09:30. An hour later
it is simply the day's range so far.

Why it matters beyond one number: after any restart past 09:30, EVERY
symbol's breakout level silently becomes its running day high. The bot
stops hunting opening-range breaks and starts demanding fresh day
highs, which is a far harder bar -- and explains the near-total absence
of structural entries after that day's 10:35 restart.
"""

from datetime import datetime as _datetime, time as dtime

import pytest

import core.engine as engine_module
from core.engine import Engine


@pytest.fixture
def at_clock(monkeypatch):
    """Pin the engine's wall clock.

    These tests used to fake "the deadline has passed" by monkeypatching
    the deadline to 00:00:01 and trusting that the real clock was later
    than that. It is not, for one second every night: this file failed at
    00:00:0x IST on 2026-07-28 and passed again at 00:00:27.

    A test about a time guard that itself depends on what time it is run
    is the same class of bug it exists to catch. So the CLOCK is pinned
    and the deadline left alone.
    """
    def _set(hh, mm, ss=0):
        fixed = _datetime(2026, 7, 27, hh, mm, ss)

        class _Clock(_datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(engine_module, "datetime", _Clock)
        return fixed
    return _set


class _Quote:
    """circuit_monitor stand-in serving a DAY high/low."""
    def __init__(self, high, low):
        self.rows = {"X": {"high": high, "low": low,
                           "last_price": (high + low) / 2,
                           "prev_close": low}}

    def get_snapshot(self):
        return self.rows

    def is_flagged(self, symbol):
        return False


def _engine_with_range(quote, high, low):
    e = Engine(min_tradable_price=0, circuit_monitor=quote,
               enable_rs_band=False, enable_staged_entry=False,
               one_trade_per_symbol=False, enable_no_progress=False,
               enable_tick_sanity=False)
    e.orb_engine._ranges = {
        "X": {"high": high, "low": low, "complete": True}
    }
    return e


def test_reconcile_runs_just_after_the_window_closes(monkeypatch, at_clock):
    """The legitimate case: at 09:30 the day range IS the opening range,
    and a sampled tick feed leaves ours too narrow."""
    monkeypatch.setattr(engine_module, "_ORB_RECONCILE_DEADLINE_T",
                        dtime(9, 35))
    at_clock(9, 31)                                # inside the grace
    e = _engine_with_range(_Quote(263.80, 260.39), 263.80, 260.84)
    e._reconcile_orb_once("X")
    assert e.orb_engine.get_range("X")["low"] == 260.39


def test_reconcile_is_refused_once_the_deadline_has_passed(monkeypatch,
                                                           at_clock):
    """The TBZ bug. A restart at 10:36 must NOT widen the range to a day
    high that has been running for an hour."""
    monkeypatch.setattr(engine_module, "_ORB_RECONCILE_DEADLINE_T",
                        dtime(9, 35))
    at_clock(10, 36)                               # the real restart time
    e = _engine_with_range(_Quote(270.00, 260.39), 263.80, 260.39)
    e._reconcile_orb_once("X")
    r = e.orb_engine.get_range("X")
    assert r["high"] == 263.80, (
        f"opening-range high was stretched to {r['high']:.2f} by a stale "
        f"day high -- this is the TBZ bug"
    )


def test_a_refused_reconcile_is_not_retried_on_every_tick(monkeypatch,
                                                          at_clock):
    """Once past the deadline it must give up for the day, not re-check
    the snapshot on every incoming tick."""
    monkeypatch.setattr(engine_module, "_ORB_RECONCILE_DEADLINE_T",
                        dtime(9, 35))
    at_clock(10, 36)
    e = _engine_with_range(_Quote(270.00, 260.39), 263.80, 260.39)
    e._reconcile_orb_once("X")
    assert "X" in e._orb_reconciled


def test_these_tests_do_not_depend_on_when_they_are_run(monkeypatch, at_clock):
    """The guard on the guard. This file failed at 00:00:0x IST on
    2026-07-28 and passed at 00:00:27, because it faked "past the
    deadline" with 00:00:01 and trusted the real clock. Midnight to
    23:59 must all behave identically."""
    monkeypatch.setattr(engine_module, "_ORB_RECONCILE_DEADLINE_T",
                        dtime(9, 35))
    for hh, mm in ((0, 0), (9, 30), (10, 36), (15, 29), (23, 59)):
        at_clock(hh, mm)
        e = _engine_with_range(_Quote(270.00, 260.39), 263.80, 260.39)
        e._reconcile_orb_once("X")
        expected = 270.00 if (hh, mm) < (9, 35) else 263.80
        assert e.orb_engine.get_range("X")["high"] == expected, \
            f"behaviour changed at {hh:02d}:{mm:02d}"


def test_the_grace_is_a_few_minutes_not_hours():
    """A wide grace would reintroduce the bug quietly.

    Reads the CONFIGURED grace, not `_ORB_RECONCILE_DEADLINE_T` -- the
    autouse fixture in conftest.py pushes that to 23:59 so the rest of
    the suite doesn't depend on what time of day it is run."""
    assert 0 < engine_module.ORB_RECONCILE_GRACE_MINUTES <= 15, (
        f"reconcile grace is {engine_module.ORB_RECONCILE_GRACE_MINUTES} "
        f"minutes; anything long lets a restart corrupt every range again"
    )
