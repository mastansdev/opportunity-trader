"""
Tests for "your trades are yours" -- core/engine.py, 2026-07-29.

    "i manual buy - SMLMAH at U.C buy taken & instantly sell by bot
     system"                              -- operator, 2026-07-29

He saw SMLMAH locked at its UPPER circuit, bought it deliberately, and
the bot closed the position within seconds on a housekeeping rule.

The rule these tests hold the engine to:

    The bot may never close a position the operator opened, EXCEPT on
    a genuine hard stop loss.

Three exits are housekeeping and protect nobody -- circuit proximity,
no-progress, slot rotation. None of them fires because money is being
lost. They are blocked outright.

The TRAILING stop reports instead of selling. On 29 July the operator's
own exits made +Rs 5,947 while the trail lost Rs 14,909, so on his
trades the message is worth more than the sale.

The FIXED stop still fires, deliberately. Alert-only on both was
offered and refused: a position left unattended needs one real net.
"""

import pytest

from core.engine import (
    Engine, ENTRY_REASON_MANUAL_DASHBOARD, ENTRY_REASON_STRUCTURAL_LONG,
    EXIT_REASON_FIXED_STOP, LONG,
)


class _FakeCircuitMonitor:
    """Flags everything. The SIDE matters since 2026-07-29 -- a LONG
    near its LOWER circuit is the trapped case these tests are about;
    near its UPPER circuit is the winner, and the bot leaves it alone
    (see test_circuit_rule_direction_aware.py)."""

    def __init__(self, side="LOWER"):
        self.side = side

    def is_flagged(self, symbol):
        return True

    def get_flag(self, symbol):
        return {"side": self.side, "gap_pct": 0.015}

    def get_snapshot(self):
        return {}


def _engine_with_position(entry_reason, side="LOWER", **position_extra):
    engine = Engine(circuit_monitor=_FakeCircuitMonitor(side))
    position = {
        "symbol": "SMLMAH",
        "security_id": "1",
        "direction": LONG,
        "entry_price": 1000.0,
        "qty": 100,
        "entry_reason": entry_reason,
        "initial_stop": 975.0,
        "fixed_target": None,
        "entry_time": None,
    }
    position.update(position_extra)
    engine.open_positions["SMLMAH"] = position
    return engine


# ---------------------------------------------------------------
# The three housekeeping exits
# ---------------------------------------------------------------

def test_circuit_proximity_does_not_touch_a_position_you_opened():
    """SMLMAH itself. Bought by hand at the upper circuit, and the
    bot wanted it gone within seconds."""
    engine = _engine_with_position(ENTRY_REASON_MANUAL_DASHBOARD)
    engine._check_circuit_proximity("SMLMAH", 970.0, None)
    assert "SMLMAH" in engine.open_positions


def test_circuit_proximity_still_closes_the_bots_own_position():
    """The rule is not deleted -- it still governs the bot's own
    inventory, which is what it was written for."""
    engine = _engine_with_position(ENTRY_REASON_STRUCTURAL_LONG)
    engine._check_circuit_proximity("SMLMAH", 970.0, None)
    assert "SMLMAH" not in engine.open_positions


def test_the_refusal_is_reported_in_plain_english():
    """The operator's standing rule: he must be able to read what the
    bot is doing. A silent skip would satisfy the code and fail him."""
    engine = _engine_with_position(ENTRY_REASON_MANUAL_DASHBOARD)
    engine._check_circuit_proximity("SMLMAH", 970.0, None)
    alerts = engine.get_manual_alerts()
    assert len(alerts) == 1
    assert "you bought this one" in alerts[0]["message"]
    assert "did NOT" in alerts[0]["message"]
    assert alerts[0]["symbol"] == "SMLMAH"


def test_the_same_refusal_is_not_repeated_on_every_tick():
    """A circuit flag stays true for hours. One sentence, not four
    hundred."""
    engine = _engine_with_position(ENTRY_REASON_MANUAL_DASHBOARD)
    for _ in range(50):
        engine._check_circuit_proximity("SMLMAH", 970.0, None)
    assert len(engine.get_manual_alerts()) == 1


# ---------------------------------------------------------------
# The trailing stop REPORTS
# ---------------------------------------------------------------

def test_the_trail_warns_instead_of_selling_your_position():
    """KAYNES, 29 July: in profit, dipped 2.5% off its high, sold by
    the trail, then ran to 3,685."""
    engine = _engine_with_position(ENTRY_REASON_MANUAL_DASHBOARD)
    assert engine._trail_only_warns("SMLMAH", 990.0, 992.0) is True
    assert "SMLMAH" in engine.open_positions

    message = engine.get_manual_alerts()[0]["message"]
    assert "NOT sold" in message
    assert "your trade" in message
    assert "-1.00%" in message          # 990 against a 1000 entry


def test_the_trail_still_sells_the_bots_own_position():
    engine = _engine_with_position(ENTRY_REASON_STRUCTURAL_LONG)
    assert engine._trail_only_warns("SMLMAH", 990.0, 992.0) is False


# ---------------------------------------------------------------
# The HARD stop still fires -- the operator's own choice
# ---------------------------------------------------------------

def test_the_fixed_stop_still_closes_a_manual_position():
    """Deliberate. The trail sells winners; the fixed stop only fires
    on a real loss, and it is the one net left for the afternoon the
    operator is away from the desk."""
    engine = _engine_with_position(
        ENTRY_REASON_MANUAL_DASHBOARD,
        initial_stop=975.0, fixed_target=1100.0,
    )
    engine._check_fixed_bracket(
        "SMLMAH", engine.open_positions["SMLMAH"], 970.0, None)
    assert "SMLMAH" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == EXIT_REASON_FIXED_STOP


# ---------------------------------------------------------------
# Flags off = old behaviour, exactly
# ---------------------------------------------------------------

def test_turning_the_protection_off_restores_the_old_behaviour(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(
        engine_module, "MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE", False)
    engine = _engine_with_position(ENTRY_REASON_MANUAL_DASHBOARD)
    engine._check_circuit_proximity("SMLMAH", 970.0, None)
    assert "SMLMAH" not in engine.open_positions


def test_turning_the_trail_flag_off_restores_selling(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(
        engine_module, "MANUAL_POSITIONS_TRAIL_ALERTS_ONLY", False)
    engine = _engine_with_position(ENTRY_REASON_MANUAL_DASHBOARD)
    assert engine._trail_only_warns("SMLMAH", 990.0, 992.0) is False


# ---------------------------------------------------------------
# Nothing here can crash the tick loop
# ---------------------------------------------------------------

def test_an_unknown_symbol_is_not_treated_as_yours():
    engine = Engine(circuit_monitor=_FakeCircuitMonitor())
    assert engine._is_manual_position("NOTHING") is False
    assert engine._bot_may_close("NOTHING", "any reason") is True


def test_alerts_are_capped():
    """Reads the cap from config instead of hardcoding it.

    It asserted `<= 50` literally, and on 30 July MANUAL_ALERT_HISTORY was
    raised to 400 because ALERT_ONLY_MODE makes alerts the bot's primary
    output rather than a footnote about manual positions -- so the test
    failed on a deliberate config change while the behaviour it checks
    (the cap holds, newest first) was still perfectly correct.
    """
    from config import MANUAL_ALERT_HISTORY
    engine = Engine()
    total = MANUAL_ALERT_HISTORY + 50          # comfortably over the cap
    for i in range(total):
        engine._manual_alert(f"SYM{i}", "TRAIL", f"note {i}")
    assert len(engine.manual_alerts) <= MANUAL_ALERT_HISTORY
    assert engine.get_manual_alerts()[0]["symbol"] == f"SYM{total - 1}", \
        "newest alert must be first -- the earliest signals of the day are "
    "the ones worth seeing"


# ---------------------------------------------------------------
# Protecting your trades must not disable OTHER features
# ---------------------------------------------------------------

def _book(engine, entries):
    """entries: [(symbol, entry_reason, strength)]"""
    strengths = {}
    for symbol, reason, strength in entries:
        engine.open_positions[symbol] = {
            "symbol": symbol, "security_id": "1", "direction": LONG,
            "entry_price": 100.0, "qty": 10, "entry_reason": reason,
            "initial_stop": 97.5, "fixed_target": None, "entry_time": None,
        }
        strengths[symbol] = strength
    engine._symbol_strength = lambda s, d: strengths.get(s)
    return engine


def test_rotation_skips_your_position_and_keeps_looking():
    """TODAY'S BOOK AT 10:19, exactly.

        CUB        YOU   -2.26%   <- weakest, and his
        INFY       YOU   +0.31%   <- also his
        MOBIKWIK   BOT   +0.45%   <- the honest answer
        EPACKPEB   BOT   +2.70%

    Before this fix _weakest_holder_for_rotation returned CUB, the
    caller hit the manual guard and gave up -- so rotation was dead for
    the WHOLE book for as long as one of his trades was the laggard.
    CUB was weakest from 09:30 onward, so that meant all day.
    """
    engine = _book(Engine(), [
        ("CUB",      ENTRY_REASON_MANUAL_DASHBOARD,  -0.0226),
        ("INFY",     ENTRY_REASON_MANUAL_DASHBOARD,   0.0031),
        ("MOBIKWIK", ENTRY_REASON_STRUCTURAL_LONG,    0.0045),
        ("EPACKPEB", ENTRY_REASON_STRUCTURAL_LONG,    0.0270),
    ])
    weakest = engine._weakest_holder_for_rotation()
    assert weakest is not None
    assert weakest[0] == "MOBIKWIK"


def test_a_book_of_only_your_positions_rotates_nothing():
    """Correct, and not the same bug: there is genuinely nothing the
    bot may give away."""
    engine = _book(Engine(), [
        ("CUB",  ENTRY_REASON_MANUAL_DASHBOARD, -0.02),
        ("INFY", ENTRY_REASON_MANUAL_DASHBOARD,  0.01),
    ])
    assert engine._weakest_holder_for_rotation() is None


def test_with_the_protection_off_the_weakest_is_the_weakest():
    import core.engine as engine_module
    engine = _book(Engine(), [
        ("CUB",      ENTRY_REASON_MANUAL_DASHBOARD, -0.0226),
        ("MOBIKWIK", ENTRY_REASON_STRUCTURAL_LONG,   0.0045),
    ])
    engine_module.MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE = False
    try:
        assert engine._weakest_holder_for_rotation()[0] == "CUB"
    finally:
        engine_module.MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE = True


# ---------------------------------------------------------------
# Slot rotation, switched on 2026-07-29 -- and capped
# ---------------------------------------------------------------

def test_rotation_stops_after_the_daily_cap():
    """The edge needed is only 0.4%, and as little as 0.1% for a
    confirmed challenger. With 666 symbols breaking out all day and
    nothing counting the swaps, the bot could churn the whole book
    repeatedly -- each swap paying slippage and selling a position the
    new no-trail rule was meant to let run."""
    import core.engine as engine_module
    engine = _book(Engine(), [
        ("MOBIKWIK", ENTRY_REASON_STRUCTURAL_LONG, 0.001),
    ])
    engine._rotations_today = engine_module.ROTATION_MAX_PER_DAY
    assert engine._maybe_rotate_out("CHALLENGER", LONG, None) is False


def test_the_cap_is_announced_once_not_on_every_candle():
    """---- IT NEEDS THE BOT ARMED. 12 August 2026. ----

    ALERT_ONLY_MODE went back to True that day, so a fresh Engine()
    starts observing -- and _maybe_rotate_out() returns at its very
    first line when alert_only is set, long before the cap it is
    supposed to announce.

    So this test was measuring the alert-only short-circuit, not the
    rotation cap. Rotation only exists when the bot is trading; the
    engine is armed here to match what the test is about.
    """
    import core.engine as engine_module
    engine = _book(Engine(), [
        ("MOBIKWIK", ENTRY_REASON_STRUCTURAL_LONG, 0.001),
    ])
    engine.alert_only = False          # rotation is a TRADING behaviour
    engine._rotations_today = engine_module.ROTATION_MAX_PER_DAY
    for _ in range(20):
        engine._maybe_rotate_out("CHALLENGER", LONG, None)
    assert engine._rotation_cap_logged is True


def test_the_day_starts_with_no_rotations_used():
    engine = Engine()
    assert engine._rotations_today == 0


# ---------------------------------------------------------------
# CARRYING WHAT WE OWN ACROSS DAYS
# ---------------------------------------------------------------
# The bot held two halves of one feature that contradicted each other:
#
#   config.FORCE_SQUARE_OFF_AT_CLOSE = False
#       positions are CARRIED, not liquidated -- deliberate, because the
#       operator moved to MTF to hold for days and square-off is MIS
#       machinery that closed TVSMOTOR and CUB on 28 July.
#
#   state_store.load()
#       refuses any file not dated today and returns None for everything,
#       open_positions included.
#
# So it carried them overnight, reported them at 15:15, and forgot them at
# 09:00. In PAPER mode nothing reconciles, so they ceased to exist.
#
# The fix splits SESSION STATE from HOLDINGS. Session state expires at
# midnight and that guard is correct -- yesterday's opening range is not
# today's breakout level. What you own does not expire.

def _write_state(path, date, positions, **extra):
    import json
    payload = {"date": date, "open_positions": positions}
    payload.update(extra)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_positions_survive_to_the_next_day(tmp_path):
    """The bug, stated directly."""
    from core import state_store
    path = str(tmp_path / "session_state.json")
    _write_state(path, "2026-07-30",
                 {"RELAXO": {"qty": 680, "entry_price": 412.92,
                             "direction": "LONG"}})
    positions, stops, opened_on = state_store.load_holdings(
        path, today="2026-07-31")
    assert "RELAXO" in positions, \
        "an MTF position vanished overnight -- the 30 July bug"
    assert positions["RELAXO"]["qty"] == 680
    assert opened_on == "2026-07-30", "must say WHEN it was opened"


def test_session_state_still_expires(tmp_path):
    """The date guard on load() is CORRECT and must stay. Yesterday's
    opening range is not today's breakout level, and acting on one is
    worse than having none."""
    from core import state_store
    path = str(tmp_path / "session_state.json")
    _write_state(path, "2026-07-30", {"RELAXO": {"qty": 1}},
                 orb_ranges={"RELAXO": {"high": 415, "low": 405}},
                 momentum_universe={"long": ["RELAXO"]},
                 session_counters={"swaps": 5})
    orb, pos, stops, port, blocks, mom = state_store.load(
        path, today="2026-07-31")
    assert orb is None and pos is None and mom is None, \
        "stale session state was restored across a day boundary"


def test_holdings_cannot_leak_session_state(tmp_path):
    """load_holdings() has no parameter that could return an opening
    range, so a future edit cannot resurrect one through this door."""
    from core import state_store
    path = str(tmp_path / "session_state.json")
    _write_state(path, "2026-07-30", {"RELAXO": {"qty": 1}},
                 orb_ranges={"RELAXO": {"high": 415, "low": 405}},
                 momentum_universe={"long": ["RELAXO"]})
    out = state_store.load_holdings(path, today="2026-07-31")
    assert len(out) == 3, "load_holdings must return exactly (positions, stops, date)"
    flat = repr(out)
    assert "415" not in flat and "405" not in flat, "an opening range leaked"


def test_same_day_is_left_to_load(tmp_path):
    """No double-restore: on the same day load() already did it."""
    from core import state_store
    path = str(tmp_path / "session_state.json")
    _write_state(path, "2026-07-30", {"RELAXO": {"qty": 1}})
    positions, _, _ = state_store.load_holdings(path, today="2026-07-30")
    assert positions == {}


def test_flat_at_the_close_carries_nothing(tmp_path):
    from core import state_store
    path = str(tmp_path / "session_state.json")
    _write_state(path, "2026-07-30", {})
    assert state_store.load_holdings(path, today="2026-07-31") == ({}, {}, None)


def test_a_corrupt_file_does_not_invent_positions(tmp_path):
    """Better to start flat than to trade a position that may not exist."""
    from core import state_store
    path = tmp_path / "session_state.json"
    path.write_text("{not json", encoding="utf-8")
    assert state_store.load_holdings(str(path), today="2026-07-31") \
        == ({}, {}, None)
