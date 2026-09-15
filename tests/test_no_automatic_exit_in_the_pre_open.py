"""---- NO AUTOMATIC EXIT BEFORE 09:15. 15 September 2026. ----

At 09:00:00-09:00:05 eight carried positions were sold in the PRE-OPEN
call auction -- OIL, INDORAMA, IKIO on the trailing stop; GMDCLTD,
GANDHAR, SPLPETRO, SUNDRMFAST, KINGFA on the drift exit. Nothing trades
continuously before 09:15, and those ticks carried the previous
session's last-trade time (15:59:50), so tick_time could not guard it.

His own EXIT ALL / SELL still goes through before 09:15.
"""

from datetime import datetime

import core.engine as engine_module
from core.engine import Engine


def _engine(monkeypatch, clock):
    eng = Engine()
    monkeypatch.setattr(Engine, "_wall_clock", staticmethod(lambda: clock))
    called = []
    for name in ("_check_circuit_proximity", "_check_trailing_stop",
                 "_check_no_progress", "_check_move_died"):
        monkeypatch.setattr(eng, name,
                            lambda *a, _n=name, **k: called.append(_n))
    monkeypatch.setattr(eng, "_process_pending_manual_exits",
                        lambda *a, **k: called.append("manual"))
    return eng, called


def _tick(eng):
    # A stale pre-open tick: the last trade's time from the previous day.
    eng.process_tick("OIL", "17438", 488.82, datetime(2026, 9, 15, 15, 59, 50))


def test_the_pre_open_runs_no_automatic_exit(monkeypatch):
    eng, called = _engine(monkeypatch, datetime(2026, 9, 15, 9, 0, 2))
    _tick(eng)
    assert "_check_trailing_stop" not in called
    assert "_check_circuit_proximity" not in called
    assert "manual" in called, "his own EXIT ALL must still go through"


def test_from_09_15_the_exits_run(monkeypatch):
    eng, called = _engine(monkeypatch, datetime(2026, 9, 15, 9, 15, 0))
    _tick(eng)
    assert "_check_trailing_stop" in called


def test_the_guard_reads_the_machine_clock_not_the_tick():
    assert engine_module._MARKET_OPEN_T.hour == 9
    assert engine_module._MARKET_OPEN_T.minute == 15
