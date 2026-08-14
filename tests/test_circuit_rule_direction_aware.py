"""
The circuit rule, made direction-aware -- 29 July 2026.

Until now a stock within 2% of EITHER limit got no new entries and any
open position closed, "irrespective of direction" in the log's own
words. For a LONG the two limits are opposite situations:

    LOWER   real danger. If it locks there are no buyers, the position
            cannot be exited at any price, and on MTF that is how a
            2.5% stop becomes a 20% loss.

    UPPER   the best thing that can happen. Buyers with no sellers.

The rule exists so the bot does not get trapped. Trapped in a RISING
stock is not a trap.

WHAT THE OLD RULE COST, measured:

    COFORGE 28 Jul   bought 1,648.10, rule sold at 1,648.30 for +Rs 24.
                     It ran to 1,692.20 and closed 1,680.10 -- holding
                     was worth Rs 3,872.

    29 Jul           the day's two biggest movers were both off-limits:
                         SMLMAH      3,838 -> 4,566   +18.97%
                         APCOTEXIND    602 ->   709   +17.82%
                     The operator bought SMLMAH by hand and the bot
                     sold it within seconds. APCOTEX it never touched.

For a SHORT it mirrors: covering means BUYING, and at the UPPER limit
there are no sellers. That is the short's trap.
"""

import pytest

import core.engine as engine_module
from core.engine import (
    Engine, ENTRY_REASON_STRUCTURAL_LONG, LONG, SHORT,
)


class _Monitor:
    def __init__(self, side):
        self.side = side

    def is_flagged(self, symbol):
        return True

    def get_flag(self, symbol):
        return {"side": self.side, "gap_pct": 0.015, "ltp": 100.0,
                "limit": 102.0}

    def get_snapshot(self):
        return {}


def _engine(side, direction=LONG):
    engine = Engine(circuit_monitor=_Monitor(side))
    engine.open_positions["COFORGE"] = {
        "symbol": "COFORGE", "security_id": "1", "direction": direction,
        "entry_price": 1648.10, "qty": 60,
        "entry_reason": ENTRY_REASON_STRUCTURAL_LONG,
        "initial_stop": 1606.90, "fixed_target": None, "entry_time": None,
    }
    return engine


# ---------------------------------------------------------------
# The change
# ---------------------------------------------------------------

def test_a_long_near_its_upper_circuit_is_left_alone():
    """COFORGE, 28 July. The rule sold it for +Rs 24; holding was
    worth Rs 3,872."""
    engine = _engine("UPPER")
    engine._check_circuit_proximity("COFORGE", 1690.0, None)
    assert "COFORGE" in engine.open_positions


def test_a_long_near_its_lower_circuit_is_still_closed():
    """Unchanged, and the reason the rule exists. No buyers if it
    locks -- the position cannot be exited at any price."""
    engine = _engine("LOWER")
    engine._check_circuit_proximity("COFORGE", 1600.0, None)
    assert "COFORGE" not in engine.open_positions


def test_a_short_is_the_mirror():
    """Covering a short means BUYING. At the UPPER limit there are no
    sellers -- that is the short's trap. At the LOWER limit it is
    deeply in profit and can cover freely."""
    assert _engine("UPPER", SHORT)._circuit_blocks("COFORGE", SHORT) is True
    assert _engine("LOWER", SHORT)._circuit_blocks("COFORGE", SHORT) is False


# ---------------------------------------------------------------
# Entries
# ---------------------------------------------------------------

def test_a_long_entry_near_the_upper_circuit_is_no_longer_refused():
    """APCOTEXIND went +17.82% to its upper circuit on 29 July and the
    bot was structurally forbidden from entering it."""
    assert Engine(circuit_monitor=_Monitor("UPPER"))._circuit_blocks(
        "APCOTEXIND", LONG) is False


def test_a_long_entry_near_the_lower_circuit_is_still_refused():
    assert Engine(circuit_monitor=_Monitor("LOWER"))._circuit_blocks(
        "SOMETHING", LONG) is True


# ---------------------------------------------------------------
# Unknown data fails CLOSED
# ---------------------------------------------------------------

def test_an_unreadable_side_falls_back_to_the_old_blanket_rule():
    """An unreadable flag is not evidence that the approach is
    favourable. It blocks, exactly as before."""
    for side in (None, "", "SIDEWAYS", 42):
        assert Engine(circuit_monitor=_Monitor(side))._circuit_blocks(
            "X", LONG) is True


def test_a_monitor_that_raises_falls_back_to_blocking():
    class Broken:
        def is_flagged(self, symbol):
            return True

        def get_flag(self, symbol):
            raise RuntimeError("no data")

        def get_snapshot(self):
            return {}

    assert Engine(circuit_monitor=Broken())._circuit_blocks("X", LONG) is True


def test_no_circuit_monitor_blocks_nothing_and_crashes_nothing():
    engine = Engine()
    assert engine._circuit_blocks("X", LONG) is True


# ---------------------------------------------------------------
# One flag back to the old behaviour
# ---------------------------------------------------------------

def test_the_old_blanket_rule_is_one_flag_away(monkeypatch):
    monkeypatch.setattr(
        engine_module, "CIRCUIT_RULE_DIRECTION_AWARE", False)
    engine = _engine("UPPER")
    engine._check_circuit_proximity("COFORGE", 1690.0, None)
    assert "COFORGE" not in engine.open_positions
