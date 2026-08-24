"""[CARRY] printed "stop None" for positions that had stops.

    "[CARRY]   CDSL  LONG  qty 47  entry 1390.80 ... stop None"
                                    -- operator, 24 August 2026

A position stores `initial_stop`, `atr_stop` and `stop_mode`. There is
no key called `stop`, so `position.get("stop")` returned None for every
carried position -- while the dashboard snapshot showed CDSL 1358.55,
JBMA 648.90 and NCC 145.55 the whole time. Three overnight holdings
read as unprotected.
"""

import json
import os

import pytest

from core.engine import Engine

REAL_STATE = os.path.join("data", "session_state.json")


def _live_stop(position, symbol="X", trailing=None):
    engine = Engine.__new__(Engine)
    engine.trailing_stop = trailing
    return Engine._live_stop_price(engine, symbol, position)


def test_a_real_position_has_no_key_called_stop():
    """The fault itself, read off the real file rather than a fixture."""
    if not os.path.exists(REAL_STATE):
        pytest.skip("no session state on this machine")
    with open(REAL_STATE, encoding="utf-8") as handle:
        book = (json.load(handle).get("open_positions") or {})
    if not book:
        pytest.skip("no open positions to read")
    for symbol, position in book.items():
        assert "stop" not in position, (
            f"{symbol} has a 'stop' key -- this test is guarding the "
            f"wrong thing and the carry print should be re-checked")
        assert "initial_stop" in position


def test_a_swing_position_reports_its_initial_stop():
    position = {"stop_mode": "SWING_TRAILING", "initial_stop": 648.9,
                "atr_stop": None, "fixed_target": 696.91}
    assert _live_stop(position) == 648.9


def test_an_atr_position_reports_its_trailing_stop():
    position = {"stop_mode": "ATR_TRAILING", "initial_stop": 100.0,
                "atr_stop": 118.5}
    assert _live_stop(position) == 118.5


def test_the_printed_line_carries_a_number_not_None(monkeypatch):
    """Runs report_carry_forward and reads what it actually prints.

    The first version of this test grepped the source for
    'position.get("stop")' -- and failed on the COMMENT quoting the
    old code. A source grep cannot tell an explanation from an
    instruction, which is the trap this repo keeps falling into.
    """
    import core.engine as engine_mod

    printed = []
    monkeypatch.setattr(engine_mod, "decision",
                        lambda msg, *a, **k: printed.append(str(msg)))

    engine = Engine.__new__(Engine)
    engine.trailing_stop = None
    engine.open_positions = {
        "CDSL": {"stop_mode": "SWING_TRAILING", "initial_stop": 1358.55,
                 "atr_stop": None, "fixed_target": 1453.2,
                 "entry_price": 1390.8, "qty": 47, "direction": "LONG"},
    }
    engine.report_carry_forward(lambda symbol: 1384.0)

    line = next((p for p in printed if "CDSL" in p), None)
    assert line is not None, printed
    assert "stop None" not in line, line
    assert "1358.5" in line, line


def test_every_carried_position_can_report_a_stop():
    """The three from 21 August, in their real recorded shape."""
    book = {
        "CDSL": {"stop_mode": "SWING_TRAILING", "initial_stop": 1358.55,
                 "atr_stop": None, "fixed_target": 1453.2},
        "JBMA": {"stop_mode": "SWING_TRAILING", "initial_stop": 648.9,
                 "atr_stop": None, "fixed_target": 696.91},
        "NCC": {"stop_mode": "SWING_TRAILING", "initial_stop": 145.55,
                "atr_stop": None, "fixed_target": 158.15},
    }
    for symbol, position in book.items():
        stop = _live_stop(position, symbol)
        assert stop is not None, f"{symbol} still reports no stop"
        assert stop > 0
