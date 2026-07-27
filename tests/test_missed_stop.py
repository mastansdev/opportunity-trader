"""
The stop must survive a sampled tick feed.

Operator-found live on 2026-07-27: SWIGGY traded below its stop on
TradingView, no tick in the Dhan WebSocket feed ever showed a price at
or under that level, and the bot went on holding the position.

core/trailing_stop.py's is_hit() is `price <= stop` -- it can only ever
see prices that ARRIVE. The feed sends periodic snapshots, not every
trade. This project already proved that for the opening range (ZENTEC
seen 1784.20 vs a real 1792.00, which is why the ORB reconcile exists);
nobody had applied the same reasoning to the stop.

Consequence, and the reason these tests exist: without reconciliation
RISK_PER_TRADE_RS is not enforced. It is the risk taken IF the feed
catches the breach, and unbounded if it does not.

The reconciliation uses the one fact a snapshot can still be trusted
for: a day LOW only ever falls and a day HIGH only ever rises. If the
exchange's extreme extends past our stop AFTER entry, that trade
happened after we bought and we missed it.
"""

import core.engine as engine_module
from core.engine import Engine, EXIT_REASON_MISSED_STOP


class _Snap:
    """circuit_monitor stand-in whose day OHLC can be moved between
    calls, the way a real polled snapshot moves."""

    def __init__(self, low, high, last=100.0):
        self.rows = {"X": {"low": low, "high": high,
                           "last_price": last, "prev_close": 100.0}}

    def set(self, low=None, high=None):
        if low is not None:
            self.rows["X"]["low"] = low
        if high is not None:
            self.rows["X"]["high"] = high

    def get_snapshot(self):
        return self.rows

    def is_flagged(self, symbol):
        return False


def _engine_with(snap):
    return Engine(min_tradable_price=0, circuit_monitor=snap,
                  enable_rs_band=False, enable_staged_entry=False,
                  one_trade_per_symbol=False, enable_no_progress=False,
                  enable_tick_sanity=False)


def _open_long(engine, entry=100.0, stop=98.0):
    """Places a position directly, bypassing the entry path -- these
    tests are about the STOP, not about how the trade was chosen."""
    engine.open_positions["X"] = {
        "security_id": "1", "qty": 10, "entry_price": entry,
        "direction": "LONG", "initial_stop": stop, "fixed_target": None,
        "stop_mode": engine_module.STOP_MODE_ATR_TRAILING,
        "atr_stop": stop, "atr_extreme": entry, "atr_value": 1.0,
        "entry_reason": engine_module.ENTRY_REASON_STRUCTURAL_LONG,
        "entry_time": None, "sector": None, "rel_strength": None,
        "regime": None,
        "exchange_extreme_at_entry": engine._exchange_extreme("X"),
    }


def test_a_breach_the_feed_skipped_is_caught_and_tagged():
    """The SWIGGY case. Day low falls to 97 -- below our 98 stop --
    after entry, and no tick ever printed under 98."""
    snap = _Snap(low=99.0, high=101.0)
    engine = _engine_with(snap)
    _open_long(engine, entry=100.0, stop=98.0)

    snap.set(low=97.0)                       # traded through, unseen
    engine._check_trailing_stop("X", 99.5, None)

    assert "X" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == EXIT_REASON_MISSED_STOP


def test_the_exit_is_tagged_separately_from_a_normal_stop():
    """These have to be COUNTABLE. A missed stop carried overnight on
    MTF is a different animal from one squared off at 15:15, and we
    cannot judge that risk without knowing how often it happens."""
    assert EXIT_REASON_MISSED_STOP != engine_module.EXIT_REASON_TRAILING_STOP


def test_a_new_low_that_stays_above_the_stop_does_nothing():
    snap = _Snap(low=99.0, high=101.0)
    engine = _engine_with(snap)
    _open_long(engine, entry=100.0, stop=98.0)

    snap.set(low=98.5)                       # lower, but not through
    engine._check_trailing_stop("X", 99.0, None)

    assert "X" in engine.open_positions


def test_a_low_set_BEFORE_entry_is_not_treated_as_a_breach():
    """The day low was already 97 when we bought at 100 with a 98 stop
    -- that low is history, not something that happened to us. Firing
    here would close every trade entered after a morning dip."""
    snap = _Snap(low=97.0, high=101.0)
    engine = _engine_with(snap)
    _open_long(engine, entry=100.0, stop=98.0)

    engine._check_trailing_stop("X", 100.0, None)

    assert "X" in engine.open_positions


def test_it_fails_open_with_no_circuit_monitor():
    """Every existing test and the whole replay bench run without a
    monitor. A safety net that changes behaviour when it is absent is
    not a safety net."""
    engine = Engine(min_tradable_price=0, enable_rs_band=False,
                    enable_staged_entry=False, one_trade_per_symbol=False,
                    enable_no_progress=False, enable_tick_sanity=False)
    _open_long(engine, entry=100.0, stop=98.0)
    engine._check_trailing_stop("X", 99.0, None)
    assert "X" in engine.open_positions


def test_it_fails_open_when_the_snapshot_has_no_row_yet():
    snap = _Snap(low=99.0, high=101.0)
    snap.rows = {}
    engine = _engine_with(snap)
    _open_long(engine, entry=100.0, stop=98.0)
    engine._check_trailing_stop("X", 99.0, None)
    assert "X" in engine.open_positions


def test_short_side_is_mirrored_on_the_day_high():
    snap = _Snap(low=99.0, high=101.0)
    engine = _engine_with(snap)
    engine.open_positions["X"] = {
        "security_id": "1", "qty": 10, "entry_price": 100.0,
        "direction": "SHORT", "initial_stop": 102.0, "fixed_target": None,
        "stop_mode": engine_module.STOP_MODE_ATR_TRAILING,
        "atr_stop": 102.0, "atr_extreme": 100.0, "atr_value": 1.0,
        "entry_reason": engine_module.ENTRY_REASON_STRUCTURAL_SHORT,
        "entry_time": None, "sector": None, "rel_strength": None,
        "regime": None,
        "exchange_extreme_at_entry": engine._exchange_extreme("X"),
    }

    snap.set(high=103.0)                     # spiked through, unseen
    engine._check_trailing_stop("X", 100.5, None)

    assert "X" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == EXIT_REASON_MISSED_STOP
