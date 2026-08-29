"""
End-to-end: real tick sequence through the actual Engine
(ORB -> candle -> strategy -> paper buy -> manual exit).
Proves the DECISIONS are right, not just that nothing
crashed.
"""

from datetime import datetime

import pytest

import config

from config import LAYER1_FIXED_QTY
from core.engine import Engine
from trading.portfolio import Portfolio
from config import MTF_MARGIN_PER_POSITION_RS


# ---- AND THE TARGET, ADDED 29 August 2026. ----
#
# config.TARGET_REWARD_BY_REGIME gives the bot's own entries a target
# for the first time -- stop distance x the day's multiple, the same
# number position_plan has always printed on the alert card.
#
# Every test below is about ATR SIZING, TRAILING or the PARTIAL EXIT.
# Six of them broke because a position they expected to ride was
# closed at the new target instead: "rides uncapped" and "a huge
# favourable move must still be open" are statements about the trail,
# not about targets. Pinning the target off here keeps them testing
# what they were written for.
#
# The target's own behaviour is covered in
# tests/test_the_bot_takes_the_target_it_promised.py.
@pytest.fixture(autouse=True)
def _no_target(monkeypatch):
    import core.engine as _engine_module
    monkeypatch.setattr(_engine_module, "TARGET_REWARD_BY_REGIME", {})
    # config.STOP_FROM_RISK_AND_SIZE derives the stop from
    # RISK_PER_TRADE_RS / qty, so the rupee loss is fixed and the
    # width follows. Every test below pins an exact stop LEVEL from
    # the ATR/volatility widths, which is a different question and
    # still the live one whenever that dial is off. Pinned off here
    # so those measurements keep being proved.
    monkeypatch.setattr(_engine_module, "STOP_FROM_RISK_AND_SIZE", False)


@pytest.fixture(autouse=True)
def _pin_sizing_constants(monkeypatch):
    """
    Pin the risk/stop constants this file's ATR-sizing, trailing and
    partial-exit tests were written against.

    These tests assert EXACT quantities and stop levels (e.g. "qty is
    capped at 1538 by the notional cap", "the stop floors at 1% below
    entry"). Those numbers are properties of the MECHANICS being
    tested, not of whatever risk appetite config currently carries --
    and config's live values are deliberately re-tuned as the strategy
    evolves (2026-07-25 moved to a tighter 0.4% stop / Rs800 risk).
    Pinning here keeps the mechanics tests stable against production
    tuning; the tuned values themselves are exercised by the strategy
    replay bench, not by unit assertions. Individual tests still
    monkeypatch these freely to test a specific interaction.
    """
    import core.engine as em
    monkeypatch.setattr(em, "RISK_PER_TRADE_RS", 2000.0)
    monkeypatch.setattr(em, "MIN_STOP_DISTANCE_PCT", 0.01)
    monkeypatch.setattr(em, "ATR_STOP_MULTIPLIER", 2.5)
    monkeypatch.setattr(em, "ATR_TRAIL_MULTIPLIER", 2.5)
    # 2026-08-01: pinned alongside the others because the manual
    # dashboard seeds now read THIS constant, not MIN_STOP_DISTANCE_PCT.
    # The two tests that assert on the manual buffer read it back off
    # the module rather than restating the number, so re-tuning the live
    # stop cannot leave a stale literal asserting the old one.
    monkeypatch.setattr(em, "HARD_STOP_FROM_ENTRY_PCT", 0.025)


# ==========================================================
# FILL PRICES, 30 July 2026
# ==========================================================
# These helpers replaced a pile of hardcoded intent prices.
#
# Sixteen tests in this file asserted `entry_price == 112.0` -- the
# price the engine ASKED for. The engine was using that same intended
# price for the P&L while trading/paper_execution.py filled at 112.22
# and modelled the difference as slippage. The tests agreed with the
# bug, so they passed, and the dashboard reported a session's profit as
# roughly 11x the truth.
#
# The fix is not to hardcode 112.22 instead. It is to assert the
# INVARIANT: a buy never fills below what you asked, a sell never fills
# above it, and every downstream number is computed from the fill. A
# test written that way would have failed the moment the engine started
# ignoring the fill, whatever the slippage model happened to produce.

def _expected_fill(intent, side, turnover_cr=None, at_time=None):
    """What trading/slippage.py says this order fills at."""
    from trading.slippage import fill_price
    return fill_price(intent, side, turnover_cr, at_time)


def _entry_of(engine, symbol):
    return engine.open_positions[symbol]["entry_price"]


def _bought(intent):
    """What a BUY at `intent` actually fills at (paper slippage model)."""
    from trading.slippage import BUY
    return _expected_fill(intent, BUY)


def _sold(intent):
    """What a SELL at `intent` actually fills at."""
    from trading.slippage import SELL
    return _expected_fill(intent, SELL)



def _t(hh, mm, ss=0):
    return datetime(2026, 7, 22, hh, mm, ss)



@pytest.fixture(autouse=True)
def _seed_stop_tests_use_the_legacy_trail(monkeypatch):
    """Most stop assertions in this file predate 2026-07-28 and encode
    the SEEDED stop -- the breakout candle's own low, or a small buffer
    below entry.

    The percent-from-peak trail (config.PEAK_TRAIL_PCT) replaced that:
    the stop now starts exactly 2.5% below entry on every trade, so the
    initial risk is the same known number every time instead of being
    whatever the candle low happened to be -- sometimes a rupee away
    (clipped by noise in seconds), sometimes 6% away.

    The seeding logic is unchanged and still runs when the peak trail is
    off, so these tests keep covering it. New behaviour is covered by
    tests/test_peak_trail.py.
    """
    import core.trailing_stop as _ts
    monkeypatch.setattr(_ts, "ENABLE_PEAK_TRAIL", False)


def _engine(**kwargs):
    """Test-only helper -- constructs Engine with the 2026-07-24
    minimum-tradable-price floor (config.MIN_TRADABLE_PRICE_RS, Rs
    200) DISABLED by default. This whole suite's pre-existing price
    convention uses toy values like TCS=100-130, established long
    before that rule existed and testing entirely different
    mechanics (ORB/trailing/ATR/manual-override behaviour, not price
    realism) -- forcing every one of those fixtures above Rs 200
    would be a large, purely mechanical churn with no correctness
    value. The rule itself is proven separately by the dedicated
    test_min_tradable_price_* tests below, which construct a real
    _engine() (or explicitly pass min_tradable_price) on purpose.
    Callers can still override via kwargs (min_tradable_price=...)
    same as any other _engine() constructor argument."""
    kwargs.setdefault("min_tradable_price", 0)
    # 2026-07-25 strategy-package gates OFF by default here, for the
    # same reason min_tradable_price is: this suite's long-standing
    # fixtures test OTHER mechanics (ORB/ATR/trailing/partial exits) on
    # toy prices and timestamps that predate these gates. The gates
    # have their own dedicated tests below which switch them ON
    # explicitly. Production never passes these, so the live bot always
    # runs the real config values.
    kwargs.setdefault("enable_rs_band", False)
    kwargs.setdefault("enable_staged_entry", False)
    kwargs.setdefault("one_trade_per_symbol", False)
    kwargs.setdefault("enable_no_progress", False)
    # Toy fixtures here move price 100 -> 50 to trigger stops, which
    # the corrupt-tick guard would (correctly) call impossible. Off by
    # default; its own tests below switch it on.
    kwargs.setdefault("enable_tick_sanity", False)
    # ALERT_ONLY_MODE is True in config from 30 July 2026 -- the bot
    # reports signals instead of buying them. This suite tests entry
    # MECHANICS, so it opts out unless a test asks otherwise.
    kwargs.setdefault("alert_only", False)
    engine = Engine(**kwargs)
    # ---- THE BREAKOUT NEEDS ITS OWN ARMING NOW. 6 August 2026. ----
    #
    # engine.breakout_armed defaults to False in production, because
    # one switch arming two buyers is what put eight unwanted fills in
    # his account on 6 August. This suite tests the breakout MECHANICS,
    # so it arms the path explicitly -- the same opt-out shape as
    # alert_only and the strategy gates above.
    #
    # The DEFAULT is proven separately by
    # test_bot_trading_on_does_not_arm_the_breakout below, which builds
    # a real Engine and asserts it refuses.
    engine.breakout_armed = True
    return engine


def _feed_orb_range(engine, symbol="TCS", sid="1", low=100.0, high=110.0):
    engine.process_tick(symbol, sid, low, _t(9, 15, 0))
    engine.process_tick(symbol, sid, high, _t(9, 20, 0))
    engine.process_tick(symbol, sid, 105.0, _t(9, 29, 59))
    engine.process_tick(symbol, sid, 105.0, _t(9, 30, 0))  # completes ORB


def _feed_volume_history_then_breakout(engine, breakout_vol, normal_vol=100):
    """Change 2 helper: ORB, then 6 inside-range candles carrying
    `normal_vol` each (builds the volume average and primes the
    symbol), then a breakout candle (close 112 > ORB high 110)
    carrying `breakout_vol`. Cumulative volume is advanced per candle,
    since the feed reports day-cumulative and the candle engine takes
    the delta. Returns after the breakout candle has CLOSED (so the
    entry has been evaluated)."""
    _feed_orb_range(engine, high=110.0)
    cum = 10_000
    for m in range(31, 37):
        engine.process_tick("TCS", "1", 105.0, _t(9, m, 0), cum)
        cum += normal_vol
        engine.process_tick("TCS", "1", 105.0, _t(9, m, 30), cum)
    # breakout candle (minute 37), close above the ORB high
    engine.process_tick("TCS", "1", 112.0, _t(9, 37, 0), cum)
    cum += breakout_vol
    engine.process_tick("TCS", "1", 112.0, _t(9, 37, 30), cum)
    # first tick of minute 38 closes the breakout candle -> evaluate
    engine.process_tick("TCS", "1", 112.0, _t(9, 38, 0), cum)


def test_volume_surge_lets_a_high_volume_breakout_through():
    """A breakout candle with 3x the recent average volume (300 vs
    100) clears the 1.5x surge bar -> real breakout, enters."""
    engine = _engine()
    _feed_volume_history_then_breakout(engine, breakout_vol=300, normal_vol=100)
    assert "TCS" in engine.open_positions


def test_weak_volume_breakout_is_skipped():
    """The MOIL/TATASTEEL case: a breakout candle whose volume is only
    1.2x the average (120 vs 100) is a thin drift across the line, not
    a real breakout -- below the 1.5x bar, so it's skipped. Silent, no
    entry_blocked record."""
    engine = _engine()
    _feed_volume_history_then_breakout(engine, breakout_vol=120, normal_vol=100)
    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_volume_filter_fails_open_when_the_feed_gives_no_volume():
    """Ticker mode / no volume -> the filter must never block. Same
    scenario but with NO cum_volume fed, so candle volumes are None
    and the trade proceeds on price alone."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    for m in range(31, 37):
        engine.process_tick("TCS", "1", 105.0, _t(9, m, 0))
        engine.process_tick("TCS", "1", 105.0, _t(9, m, 30))
    engine.process_tick("TCS", "1", 112.0, _t(9, 37, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 37, 30))
    engine.process_tick("TCS", "1", 112.0, _t(9, 38, 0))
    assert "TCS" in engine.open_positions


def test_volume_filter_off_by_config_lets_everything_through(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "ENABLE_VOLUME_FILTER", False)
    engine = _engine()
    # Even a weak-volume breakout enters when the filter is disabled.
    _feed_volume_history_then_breakout(engine, breakout_vol=120, normal_vol=100)
    assert "TCS" in engine.open_positions


def test_breakout_close_triggers_a_paper_buy():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)

    # Build a 1-min candle that closes above the ORB high.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    # Next tick in a new minute closes the candle at 112.0.
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["entry_price"] == _bought(112.0)


def test_wick_above_high_without_a_close_does_not_buy():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)

    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 115.0, _t(9, 31, 20))  # wick above high
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 50))  # closes back below
    engine.process_tick("TCS", "1", 108.5, _t(9, 32, 0))   # closes the candle

    assert "TCS" not in engine.open_positions


def test_trailing_stop_auto_exits_on_a_sharp_adverse_move():
    """
    Supersedes the old Layer 1 assumption of "no automated
    exit" -- the trailing stop (core/trailing_stop.py) is a
    deliberate, confirmed addition. Operator-corrected
    2026-07-23: the stop is seeded at the ORB range's OPPOSITE
    boundary (low=100.0 here) minus ORB_STOP_BUFFER_PCT (0.2%)
    -- 99.8 -- not the breakout candle's own low. A tick trading
    through that level must close the position immediately,
    intrabar, not wait for a candle close.
    """
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions
    assert engine.trailing_stop.get_stop("TCS") == 99.8

    # A sharp adverse move through the stop -- must auto-exit,
    # same tick, no candle close required.
    engine.process_tick("TCS", "1", 50.0, _t(9, 40, 0))
    assert "TCS" not in engine.open_positions


def test_position_survives_a_dip_that_stays_above_the_trailing_stop():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    # Dips, but never trades at/below the 99.8 stop (ORB low
    # 100.0 minus the 0.2% buffer).
    engine.process_tick("TCS", "1", 109.0, _t(9, 33, 0))
    assert "TCS" in engine.open_positions


def test_manual_exit_all_closes_the_position():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 113.0, _t(9, 45, 0))

    assert "TCS" not in engine.open_positions


def test_exit_all_flag_resets_so_it_does_not_poison_future_positions():
    """
    Real bug found in review: 'exitall' set a flag that was
    never cleared once every position it applied to had
    actually closed. Left unfixed, EVERY position opened for
    the rest of the session would get force-sold on its very
    next tick, silently -- no error, no crash, just a bot that
    quietly refuses to ever hold a second trade after one
    'exitall'.
    """
    engine = _engine()
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 113.0, _t(9, 45, 0))
    assert "TCS" not in engine.open_positions
    assert engine.trade_controller.is_exit_all_requested() is False

    # A brand new breakout on a DIFFERENT symbol, well after the
    # exitall -- must be allowed to open and STAY open.
    _feed_orb_range(engine, "INFY", "2", low=200.0, high=220.0)
    engine.process_tick("INFY", "2", 218.0, _t(9, 46, 0))
    engine.process_tick("INFY", "2", 225.0, _t(9, 46, 30))
    engine.process_tick("INFY", "2", 224.0, _t(9, 47, 0))

    assert "INFY" in engine.open_positions


def test_exit_all_never_touches_a_position_opened_after_the_request():
    """
    Real bug, live, 2026-07-23: the OLD fix (test above) only
    covered a single position closing cleanly to an empty book.
    With multiple positions open and re-entry unblocked, the book
    can go 74+ minutes without ever being fully empty -- every
    position opened DURING that window (i.e. after "exitall" was
    typed) got force-sold as MANUAL_EXIT on its very next tick,
    2039 phantom trades over the real session. "exitall" must only
    ever apply to what was open at the moment it was issued -- a
    fresh position opened afterward, even while an older exit-all
    batch is still draining, must be left completely alone.
    """
    engine = _engine()
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    _feed_orb_range(engine, "INFY", "2", low=200.0, high=220.0)
    engine.process_tick("INFY", "2", 218.0, _t(9, 33, 0))
    engine.process_tick("INFY", "2", 225.0, _t(9, 33, 30))
    engine.process_tick("INFY", "2", 224.0, _t(9, 34, 0))
    assert "TCS" in engine.open_positions
    assert "INFY" in engine.open_positions

    engine.trade_controller.request_exit_all()

    # This tick both snapshots {"TCS", "INFY"} (the first tick to
    # observe the fresh request) AND closes TCS -- INFY is still
    # open, batch not yet fully drained.
    engine.process_tick("TCS", "1", 113.0, _t(9, 45, 0))
    assert "TCS" not in engine.open_positions
    assert "INFY" in engine.open_positions
    assert engine.trade_controller.is_exit_all_requested() is True

    # A brand-new breakout, opened WHILE the exit-all batch is
    # still mid-drain (INFY hasn't gotten its own tick yet). Under
    # the old bug this would get force-sold on its very next tick
    # just for having the misfortune of opening while the flag was
    # still set -- it was never part of the original request.
    _feed_orb_range(engine, "WAKEFIT", "3", low=150.0, high=160.0)
    engine.process_tick("WAKEFIT", "3", 158.0, _t(9, 46, 0))
    engine.process_tick("WAKEFIT", "3", 165.0, _t(9, 46, 30))
    engine.process_tick("WAKEFIT", "3", 164.0, _t(9, 47, 0))
    assert "WAKEFIT" in engine.open_positions

    # One more unrelated tick for WAKEFIT -- still must not be
    # touched by the still-draining exit-all batch.
    engine.process_tick("WAKEFIT", "3", 164.5, _t(9, 48, 0))
    assert "WAKEFIT" in engine.open_positions

    # Now INFY finally gets a tick -- the batch drains, the flag
    # clears, and WAKEFIT was never affected at any point.
    engine.process_tick("INFY", "2", 226.0, _t(9, 49, 0))
    assert "INFY" not in engine.open_positions
    assert engine.trade_controller.is_exit_all_requested() is False
    assert "WAKEFIT" in engine.open_positions


def test_exit_all_on_a_flat_book_clears_immediately_and_does_not_linger():
    """
    Real bug, same root cause, different shape: if 'exitall' is
    requested with zero open positions, the OLD code's "clear once
    open_positions is empty" check was already vacuously true, so
    on its own that case looked fine. But the actual live bug's
    fix (snapshotting) introduces a NEW failure mode if the empty
    case isn't handled explicitly: an empty snapshot that's never
    cleared would sit there forever, silently waiting -- and the
    NEXT position opened, possibly hours later and with nothing to
    do with the original request, would become the "first" symbol
    to populate that stale snapshot and get phantom-exited on the
    spot. Must clear the instant it's noticed, not linger.
    """
    engine = _engine()
    engine.trade_controller.request_exit_all()
    assert engine.trade_controller.is_exit_all_requested() is True

    # No open positions -- this tick doesn't even build a candle
    # close, just needs to run process_tick once so the snapshot
    # logic gets a chance to observe the flag.
    engine.process_tick("TCS", "1", 100.0, _t(9, 15, 0))
    assert engine.trade_controller.is_exit_all_requested() is False

    # A position opened well afterward, completely unrelated to
    # the earlier request -- must open and stay open normally.
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions


# -- market_data-backed instant exits, 2026-07-23 night -- see
# Engine._process_pending_manual_exits()'s docstring. Operator
# report during live PAPER testing: "some stocks exited, then
# silently stopped exiting" after EXIT ALL -- a quiet symbol just
# sat mid-batch waiting for its own next tick, which could be
# minutes away. These tests wire a fake market_data (last-known-
# price cache) into Engine and confirm the fix: every pending
# symbol resolves and exits off ONE tick for ANY symbol, not its
# own.

class _FakeMarketData:
    def __init__(self, prices=None):
        self.prices = prices or {}

    def get_latest_price(self, symbol):
        return self.prices.get(symbol)

    def is_orb_window_unreliable(self, symbol):
        """2026-07-24 ORB-window-staleness feature -- always False
        here, this fake only exists to test exit-pricing lookups
        (see test names below), not entry-side ORB reliability."""
        return False


def test_exit_all_exits_a_quiet_symbol_immediately_using_cached_price():
    market_data = _FakeMarketData({"TCS": 113.0, "INFY": 226.0})
    engine = _engine(market_data=market_data)

    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    _feed_orb_range(engine, "INFY", "2", low=200.0, high=220.0)
    engine.process_tick("INFY", "2", 218.0, _t(9, 33, 0))
    engine.process_tick("INFY", "2", 225.0, _t(9, 33, 30))
    engine.process_tick("INFY", "2", 224.0, _t(9, 34, 0))
    assert "TCS" in engine.open_positions
    assert "INFY" in engine.open_positions

    engine.trade_controller.request_exit_all()

    # ONE tick, for TCS only -- under the old symbol-scoped check,
    # INFY (a "quiet" symbol with no tick of its own here) would
    # stay open until it happened to tick. With market_data wired,
    # this single tick resolves and exits BOTH.
    engine.process_tick("TCS", "1", 113.0, _t(9, 45, 0))

    assert "TCS" not in engine.open_positions
    assert "INFY" not in engine.open_positions
    exit_prices = {c["symbol"]: c["exit_price"] for c in engine.closed_positions}
    assert exit_prices["TCS"] == _sold(113.0)
    assert exit_prices["INFY"] == _sold(226.0)
    assert engine.trade_controller.is_exit_all_requested() is False


def test_individual_exit_of_a_different_symbol_resolves_via_market_data():
    market_data = _FakeMarketData({"INFY": 230.0})
    engine = _engine(market_data=market_data)

    _feed_orb_range(engine, "INFY", "2", low=200.0, high=220.0)
    engine.process_tick("INFY", "2", 218.0, _t(9, 33, 0))
    engine.process_tick("INFY", "2", 225.0, _t(9, 33, 30))
    engine.process_tick("INFY", "2", 224.0, _t(9, 34, 0))
    assert "INFY" in engine.open_positions

    engine.trade_controller.request_exit("INFY")

    # A tick for a COMPLETELY unrelated symbol still triggers
    # INFY's exit, off its own cached last price (230.0), not this
    # tick's price (100.0) and not INFY's own stale in-position price.
    engine.process_tick("TCS", "1", 100.0, _t(9, 40, 0))

    assert "INFY" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_price"] == _sold(230.0)


def test_exit_all_leaves_a_symbol_pending_with_no_known_price_yet():
    """No price known for HFCL at all (never ticked this session,
    market_data has nothing cached) -- must NOT guess a price or
    crash; stays open until a real price is known."""
    market_data = _FakeMarketData({"TCS": 113.0})  # nothing for HFCL
    engine = _engine(market_data=market_data)

    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    # Note: _feed_orb_range always injects a fixed 105.0 tick, so
    # HFCL's actual ORB range here ends up [90.0, 105.0] regardless
    # of the high=100.0 passed below -- breakout ticks must clear
    # the ACTUAL high (105.0), not the intended one.
    _feed_orb_range(engine, "HFCL", "3", low=90.0, high=100.0)
    engine.process_tick("HFCL", "3", 108.0, _t(9, 33, 0))
    engine.process_tick("HFCL", "3", 112.0, _t(9, 33, 30))
    engine.process_tick("HFCL", "3", 111.0, _t(9, 34, 0))
    assert "HFCL" in engine.open_positions

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 113.0, _t(9, 45, 0))

    assert "TCS" not in engine.open_positions
    assert "HFCL" in engine.open_positions  # left pending, not guessed
    assert engine.trade_controller.is_exit_all_requested() is True


def test_exit_all_with_market_data_still_never_touches_a_position_opened_after_the_request():
    """Same invariant as test_exit_all_never_touches_a_position_opened_after_the_request
    above, but with market_data wired -- confirms the new instant-
    resolution path still only ever acts on symbols that were
    actually IN the snapshot, never a fresh position opened after
    the request just because market_data happens to have a cached
    price for it too."""
    market_data = _FakeMarketData({"TCS": 113.0, "WAKEFIT": 164.5})
    engine = _engine(market_data=market_data)

    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 113.0, _t(9, 45, 0))
    assert "TCS" not in engine.open_positions
    assert engine.trade_controller.is_exit_all_requested() is False

    # Opened AFTER the exit-all request/drain -- market_data already
    # has a cached price for it, but it was never part of the
    # snapshot, so it must stay open regardless.
    _feed_orb_range(engine, "WAKEFIT", "3", low=150.0, high=160.0)
    engine.process_tick("WAKEFIT", "3", 158.0, _t(9, 46, 0))
    engine.process_tick("WAKEFIT", "3", 165.0, _t(9, 46, 30))
    engine.process_tick("WAKEFIT", "3", 164.0, _t(9, 47, 0))

    assert "WAKEFIT" in engine.open_positions


def test_entry_records_the_entry_reason():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert engine.open_positions["TCS"]["entry_reason"] == "STRUCTURAL_LONG_BREAKOUT"


def test_trailing_stop_ratchets_up_as_new_candles_close_above_it():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))  # entry, stop seeded at ORB low (100.0) - 0.2% = 99.8
    assert engine.trailing_stop.get_stop("TCS") == 99.8

    # Three more closed candles, each with a rising low --
    # window is 5, so the initial 99.8 seed is still inside it
    # and the stop should not have moved yet.
    engine.process_tick("TCS", "1", 113.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 114.0, _t(9, 34, 0))
    engine.process_tick("TCS", "1", 115.0, _t(9, 35, 0))
    assert engine.trailing_stop.get_stop("TCS") == 99.8

    # One more -- now the window (last 5 closed candle lows)
    # no longer includes the 99.8 seed, so the stop must ratchet up.
    engine.process_tick("TCS", "1", 116.0, _t(9, 36, 0))
    engine.process_tick("TCS", "1", 117.0, _t(9, 37, 0))
    assert engine.trailing_stop.get_stop("TCS") > 99.8


def test_frozen_feed_stops_the_trailing_stop_from_ratcheting_onto_it():
    """
    Real bug, live, 2026-07-23: HFCL's feed froze (fresh
    timestamps, but the exact same price on every candle) for
    ~4 hours. The rolling trailing-stop window (5 candles) only
    needs FIVE consecutive identical closes before the original,
    safely-seeded stop gets rolled out of the window and replaced
    by the frozen price itself -- at which point the very next
    (still-frozen) tick self-triggers an exit, at breakeven, for
    no real reason. FROZEN_PRICE_STREAK_CANDLES=3 must catch this
    well before the 5-candle window ever empties out -- the stop
    should stay exactly at its original seed forever, no matter
    how many more frozen candles arrive, and the position must
    never self-exit from this.
    """
    engine = _engine()
    # low=100/high=110 -- _feed_orb_range's own filler ticks are a
    # hardcoded 105.0, which must sit inside [low, high] or it
    # corrupts the range itself (same range every other SHORT test
    # in this file already uses, e.g. test_short_position_pnl_...).
    _feed_orb_range(engine, "HFCL", "9", low=100.0, high=110.0)
    # Breakdown entry -- a real, one-off close below the range low.
    engine.process_tick("HFCL", "9", 95.0, _t(9, 31, 0))
    engine.process_tick("HFCL", "9", 95.0, _t(9, 32, 0))  # closes 9:31 candle -> entry
    assert "HFCL" in engine.open_positions
    seeded_stop = engine.trailing_stop.get_stop("HFCL")
    assert seeded_stop > 95.0  # SHORT stop sits above entry, nowhere near price

    # Eight more consecutive candles, all frozen at the exact same
    # 95.0 -- well past the 5-candle window that would normally
    # roll the safe seed out and replace it with the frozen price.
    for minute in range(33, 41):
        engine.process_tick("HFCL", "9", 95.0, _t(9, minute, 0))

    assert engine.trailing_stop.get_stop("HFCL") == seeded_stop
    assert "HFCL" in engine.open_positions  # never self-triggered


def test_frozen_feed_blocks_a_fresh_structural_entry_once_detected():
    """
    Companion to the ratchet test above -- once a symbol's last
    FROZEN_PRICE_STREAK_CANDLES closes are identical, it must not
    be allowed to manufacture a brand new structural entry either,
    the same dead-feed value that already got legitimately traded
    once (and manually closed here, to isolate this from the
    separate BLOCK_REENTRY_AFTER_STOPOUT mechanism) must not keep
    re-triggering "fresh" breakouts for as long as the freeze lasts.
    """
    engine = _engine()
    # low=100/high=110 -- see the ratchet test above for why the
    # helper's hardcoded 105.0 filler requires this specific range.
    _feed_orb_range(engine, "HFCL", "9", low=100.0, high=110.0)

    # First candle at the frozen price -- streak is only 1, not yet
    # frozen, so this is a perfectly legitimate first entry.
    engine.process_tick("HFCL", "9", 95.0, _t(9, 31, 0))
    engine.process_tick("HFCL", "9", 95.0, _t(9, 32, 0))
    assert "HFCL" in engine.open_positions

    # Manual exit (not a stop-out) so BLOCK_REENTRY_AFTER_STOPOUT's
    # separate same-direction block never enters the picture here.
    engine.trade_controller.request_exit("HFCL")
    engine.process_tick("HFCL", "9", 95.0, _t(9, 33, 0))  # closes 9:32 candle, then exits
    assert "HFCL" not in engine.open_positions
    assert len(engine.closed_positions) == 1

    # Streak is now 2 (9:31 and 9:32 candles) -- still not frozen,
    # so a second legitimate re-entry at the same price is allowed.
    engine.process_tick("HFCL", "9", 95.0, _t(9, 34, 0))  # closes 9:33 candle -> streak 3
    # Note: this same tick both closes the 9:33 candle (streak -> 3,
    # frozen from here) AND is itself the candle whose signal is
    # being evaluated -- so the re-entry attempt below is the one
    # that must be refused, not this one.
    # Streak just hit 3 on THIS candle close -- frozen from here on,
    # so this candle's own breakdown signal must be refused.
    assert "HFCL" not in engine.open_positions
    assert len(engine.closed_positions) == 1  # still just the one real trade


def test_no_pyramiding_on_a_second_breakout_while_already_open():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert engine.open_positions["TCS"]["qty"] == LAYER1_FIXED_QTY

    # Another strong candle close above the high while
    # already holding -- must not add to the position.
    engine.process_tick("TCS", "1", 120.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 118.0, _t(9, 34, 0))

    assert engine.open_positions["TCS"]["qty"] == LAYER1_FIXED_QTY


class _FakeSectorMonitor:
    def __init__(self, panicking=None, sector="PHARMA"):
        self.panicking = panicking or set()
        self.sector = sector

    def is_symbol_in_panicking_sector(self, symbol):
        return symbol in self.panicking

    def sector_of(self, symbol):
        return self.sector


def test_export_entry_blocks_then_load_entry_blocks_round_trips():
    """Uses the SECTOR-PANIC block -- the news block was deleted with the
    news subsystem on 2026-07-26, and sector panic is now the only thing
    that writes an entry_blocked reason."""
    monitor = _FakeSectorMonitor(panicking={"TCS"}, sector="IT")
    engine = _engine(sector_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" not in engine.open_positions

    snapshot = engine.export_entry_blocks()
    restarted = _engine()
    restarted.load_entry_blocks(snapshot)

    assert restarted.entry_blocked == engine.entry_blocked


def test_sector_panic_blocks_new_long_entries_in_that_sector():
    monitor = _FakeSectorMonitor(panicking={"TCS"})
    engine = _engine(sector_monitor=monitor)
    _feed_orb_range(engine, high=110.0)

    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked["TCS"]["LONG"].startswith(
        "sector 'PHARMA' is panic-flagged"
    )


def test_sector_panic_never_blocks_a_short():
    """A genuine breakdown inside a panicking sector is going
    WITH the market -- must stay fully tradeable."""
    monitor = _FakeSectorMonitor(panicking={"TCS"})
    engine = _engine(sector_monitor=monitor)
    _feed_orb_range(engine, low=100.0, high=110.0)

    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["direction"] == "SHORT"


def test_no_sector_check_when_no_sector_monitor_wired_in():
    engine = _engine()  # sector_monitor defaults to None
    _feed_orb_range(engine, high=110.0)

    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


# -- SHORT side, mirror of the LONG structural tests above --

def test_breakdown_close_triggers_a_paper_short():
    engine = _engine()
    _feed_orb_range(engine, low=100.0, high=110.0)

    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    position = engine.open_positions["TCS"]
    assert position["direction"] == "SHORT"
    # A short ENTERS by selling, so it fills below what it asked for.
    assert position["entry_price"] == _sold(95.0)
    assert position["entry_reason"] == "STRUCTURAL_SHORT_BREAKDOWN"


def test_short_trailing_stop_seeded_at_orb_high_plus_buffer():
    """Operator-corrected 2026-07-23: seeded at the ORB range's
    OPPOSITE boundary (high=110.0) plus ORB_STOP_BUFFER_PCT
    (0.2%) -- 110.22 -- not the breakdown candle's own high."""
    engine = _engine()
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))

    assert engine.trailing_stop.get_stop("TCS") == 110.22
    assert engine.trailing_stop.get_direction("TCS") == "SHORT"


def test_short_auto_covers_on_a_sharp_adverse_move_upward():
    engine = _engine()
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    # Sharp adverse move UP through the stop -- must auto-cover,
    # same tick, no candle close required.
    engine.process_tick("TCS", "1", 150.0, _t(9, 40, 0))
    assert "TCS" not in engine.open_positions


def test_long_stop_out_blocks_same_direction_re_entry_for_the_rest_of_the_day(monkeypatch):
    """Operator-approved 2026-07-23, after the first live session
    showed the same symbol re-triggering the same direction 3-4
    times, each a fresh small loss: a STRUCTURAL stop-out now
    blocks that symbol+direction for the rest of the day -- see
    core/engine.py's _exit(). Reuses the same entry_blocked ledger
    as the news/sector blocks.

    The rule itself defaults OFF for 2026-07-23 only (config.py's
    BLOCK_REENTRY_AFTER_STOPOUT -- today's stop-outs came from the
    too-tight-stop bug, not a genuine failed signal), so this test
    force-enables it to prove the mechanism itself still works
    correctly for when it's back on by default."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", True)

    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    # Sharp adverse move through the stop -- stops out.
    engine.process_tick("TCS", "1", 50.0, _t(9, 40, 0))
    assert "TCS" not in engine.open_positions
    assert "LONG" in engine.entry_blocked.get("TCS", {})

    # A fresh breakout close back above the ORB high must NOT
    # re-enter -- LONG is blocked on this symbol for today.
    engine.process_tick("TCS", "1", 120.0, _t(9, 41, 0))
    engine.process_tick("TCS", "1", 122.0, _t(9, 41, 30))
    engine.process_tick("TCS", "1", 121.0, _t(9, 42, 0))
    assert "TCS" not in engine.open_positions


def test_short_stop_out_blocks_same_direction_but_not_the_opposite_one(monkeypatch):
    """Mirror of the LONG case, plus confirms the block is scoped
    to ONE direction only -- a failed short says nothing about
    whether a later long setup on the same symbol is valid.
    Force-enables BLOCK_REENTRY_AFTER_STOPOUT -- see the LONG
    test's docstring above for why it's off by default today."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", True)

    engine = _engine()
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    engine.process_tick("TCS", "1", 150.0, _t(9, 40, 0))
    assert "TCS" not in engine.open_positions
    assert "SHORT" in engine.entry_blocked.get("TCS", {})
    assert "LONG" not in engine.entry_blocked.get("TCS", {})

    # A fresh breakdown close back below the ORB low must NOT
    # re-enter -- SHORT is blocked on this symbol for today.
    engine.process_tick("TCS", "1", 90.0, _t(9, 41, 0))
    engine.process_tick("TCS", "1", 88.0, _t(9, 41, 30))
    engine.process_tick("TCS", "1", 89.0, _t(9, 42, 0))
    assert "TCS" not in engine.open_positions


def test_stopout_blocks_same_direction_reentry_when_the_flag_is_on():
    """When BLOCK_REENTRY_AFTER_STOPOUT is on, a stop-out must block
    same-direction re-entry for the rest of the day.

    RENAMED 2026-07-27. This used to assert the LIVE DEFAULT ("with no
    monkeypatch involved"). That default is now False -- the rule was
    switched off because it and ONE_TRADE_PER_SYMBOL_PER_DAY together
    retired a stock permanently after one stop-out, and on 2026-07-27
    that locked out CAPLIPOINT at 09:32 in an 88/100 bullish tape,
    four minutes after a 0.4% trail floor closed it at +0.22%.

    The MECHANISM is still correct and still tested -- tests/conftest.py
    turns it on for the suite. What is no longer asserted here is which
    way the production switch is set, because a test that pins a
    strategy choice fails every time the strategy legitimately changes,
    and teaches us to edit the test instead of think."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    engine.process_tick("TCS", "1", 50.0, _t(9, 40, 0))
    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}).get("LONG") is not None

    # A fresh breakout close back above the ORB high must NOT
    # re-enter -- the direction is blocked for the rest of the day.
    engine.process_tick("TCS", "1", 120.0, _t(9, 41, 0))
    engine.process_tick("TCS", "1", 122.0, _t(9, 41, 30))
    engine.process_tick("TCS", "1", 121.0, _t(9, 42, 0))
    assert "TCS" not in engine.open_positions


def test_no_short_pyramiding_while_already_short():
    engine = _engine()
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))
    assert engine.open_positions["TCS"]["qty"] == LAYER1_FIXED_QTY

    engine.process_tick("TCS", "1", 90.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 85.0, _t(9, 34, 0))

    assert engine.open_positions["TCS"]["qty"] == LAYER1_FIXED_QTY


def test_short_position_pnl_is_profit_when_price_falls():
    portfolio = Portfolio(starting_capital=1_000_000.0)
    engine = _engine(portfolio=portfolio)
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))
    # Credited at the FILL, not the intent -- a short sells to open.
    short_entry = _entry_of(engine, "TCS")
    assert short_entry <= 95.0
    assert portfolio.available_capital == \
        1_000_000.0 + short_entry * LAYER1_FIXED_QTY

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 90.0, _t(9, 45, 0))

    # Both legs at their FILLS: sold to open below 95, bought to cover
    # above 90. Slippage bites twice on a short, and the honest P&L is
    # smaller than the arithmetic on the intended prices.
    cover = engine.closed_positions[0]["exit_price"]
    assert cover >= 90.0, "a buy-to-cover cannot fill below what it asked"
    expected = (short_entry - cover) * LAYER1_FIXED_QTY
    assert portfolio.realized_pnl == pytest.approx(expected)
    assert engine.closed_positions[0]["pnl"] == pytest.approx(expected)
    assert expected < (95.0 - 90.0) * LAYER1_FIXED_QTY
    assert engine.closed_positions[0]["direction"] == "SHORT"


# -- MIS buying power gate (core/engine.py's _enter(), trading/portfolio.py) --

def test_margin_blocks_a_new_structural_entry_once_buying_power_is_exhausted(monkeypatch):
    # ---- THIS TEST ISOLATES THE MARGIN GATE. 10 August 2026. ----
    #
    # Rs 11,200 is deliberately below core/capital.FREE_CASH_FLOOR_RS,
    # so with ENABLE_CASH_SIZED_BOOK on the SLOT gate answers zero and
    # returns before the margin gate is ever reached. That is correct
    # behaviour under his own rule -- "keep at least 1 lakh free cash"
    # -- and it is not what this test is about.
    #
    # Pinning the flag here keeps the two gates testable separately.
    # The interaction itself is covered by the capital tests.
    import core.engine as _eng
    monkeypatch.setattr(_eng, "ENABLE_CASH_SIZED_BOOK", False,
                        raising=False)
    # 100% margin (no leverage) so notional == margin blocked.
    portfolio = Portfolio(starting_capital=11_200.0, default_margin_pct=1.0)
    engine = _engine(portfolio=portfolio)
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions  # uses exactly all 11,200 buying power

    _feed_orb_range(engine, "INFY", "2", low=200.0, high=220.0)
    engine.process_tick("INFY", "2", 218.0, _t(9, 33, 0))
    engine.process_tick("INFY", "2", 225.0, _t(9, 33, 30))
    engine.process_tick("INFY", "2", 224.0, _t(9, 34, 0))

    assert "INFY" not in engine.open_positions  # no buying power left


def test_margin_gate_applies_to_manual_buy_too():
    """Margin is a hard capital constraint, unlike news/sector --
    even an explicit operator override can't buy shares that
    don't fit the available buying power."""
    portfolio = Portfolio(starting_capital=100.0, default_margin_pct=1.0)  # only Rs 100 cash
    engine = _engine(portfolio=portfolio)
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 250.0, _t(9, 20, 0))

    assert "TCS" not in engine.open_positions


def test_margin_frees_up_after_a_position_closes_not_a_permanent_block(monkeypatch):
    # ---- THIS TEST ISOLATES THE MARGIN GATE. 10 August 2026. ----
    #
    # Rs 11,200 is deliberately below core/capital.FREE_CASH_FLOOR_RS,
    # so with ENABLE_CASH_SIZED_BOOK on the SLOT gate answers zero and
    # returns before the margin gate is ever reached. That is correct
    # behaviour under his own rule -- "keep at least 1 lakh free cash"
    # -- and it is not what this test is about.
    #
    # Pinning the flag here keeps the two gates testable separately.
    # The interaction itself is covered by the capital tests.
    import core.engine as _eng
    monkeypatch.setattr(_eng, "ENABLE_CASH_SIZED_BOOK", False,
                        raising=False)
    """Unlike entry_blocked, a margin skip is NOT for the rest of
    the day -- closing a position frees the capital immediately
    for the very next valid signal."""
    portfolio = Portfolio(starting_capital=11_200.0, default_margin_pct=1.0)
    engine = _engine(portfolio=portfolio)
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 115.0, _t(9, 40, 0))
    assert "TCS" not in engine.open_positions

    _feed_orb_range(engine, "INFY", "2", low=100.0, high=110.0)
    engine.process_tick("INFY", "2", 108.0, _t(9, 41, 0))
    engine.process_tick("INFY", "2", 111.0, _t(9, 41, 30))
    engine.process_tick("INFY", "2", 111.5, _t(9, 42, 0))

    assert "INFY" in engine.open_positions


def test_no_margin_check_when_no_portfolio_wired_in():
    engine = _engine()  # portfolio defaults to None
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


def test_export_positions_then_load_positions_survives_a_restart():
    """
    Without this, a restart forgets any PAPER position it
    already holds -- the trade log still shows it as bought,
    but the engine no longer knows it's open, which risks a
    second, duplicate entry on the next breakout close.
    """
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    snapshot = engine.export_positions()

    restarted = _engine()
    restarted.load_positions(snapshot)

    assert restarted.open_positions == engine.open_positions
    # Must be a real copy, not shared state.
    restarted.open_positions["TCS"]["qty"] = 99
    assert engine.open_positions["TCS"]["qty"] == LAYER1_FIXED_QTY


def test_atr_trailing_position_survives_a_restart_with_its_own_stop_intact():
    """The ATR redesign's new fields (stop_mode, atr_stop,
    atr_extreme, atr_value) must round-trip through export/load
    exactly like every other position field -- a restart mid-trade
    must not silently drop back to swing-trailing behaviour or lose
    the live-ratcheted ATR stop."""
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert engine.open_positions["TCS"]["stop_mode"] == "ATR_TRAILING"

    snapshot = engine.export_positions()

    restarted = _engine(momentum_universe=universe)
    restarted.load_positions(snapshot)

    restored = restarted.open_positions["TCS"]
    original = engine.open_positions["TCS"]
    assert restored["stop_mode"] == "ATR_TRAILING"
    assert restored["atr_stop"] == original["atr_stop"]
    assert restored["atr_extreme"] == original["atr_extreme"]

    # And it must still be managed via the ATR path post-restart,
    # not silently fall back to the (never-started) swing engine.
    stop = restored["atr_stop"]
    restarted.process_tick("TCS", "1", stop, _t(9, 40, 0))
    assert "TCS" not in restarted.open_positions
    assert restarted.closed_positions[-1]["exit_reason"] == "TRAILING_STOP"


def test_paused_new_entries_blocks_structural_entry_but_not_manual_buy():
    """2026-07-24, EXIT ALL popup's "Stop New Entries + Exit All"
    option -- trade_controller.request_pause_new_entries() gates off
    automated structural entries but must NOT touch the manual
    buy/short override path, same "explicit operator override"
    reasoning already applied to the news/sector blocks."""
    engine = _engine()
    engine.trade_controller.request_pause_new_entries()
    _feed_orb_range(engine, high=110.0)

    # Would normally be a breakout -- must be silently skipped while paused.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}

    # Manual BUY still works while paused.
    engine.trade_controller.request_buy("INFY")
    engine.process_tick("INFY", "2", 250.0, _t(9, 33, 0))
    assert "INFY" in engine.open_positions


def test_paused_new_entries_stays_paused_even_after_the_book_goes_flat():
    """2026-07-24 (evening): auto-resume-when-flat was REMOVED. It
    re-opened 10 fresh positions the instant Exit All finished,
    defeating the "Stop New Entries" button (operator report). The
    pause now STAYS on until the operator explicitly resumes -- so
    after the last position exits, entries must remain paused."""
    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 100.0, _t(9, 20, 0))
    assert "TCS" in engine.open_positions

    engine.trade_controller.request_pause_new_entries()
    assert engine.trade_controller.is_new_entries_paused() is True

    engine.trade_controller.request_exit("TCS")
    engine.process_tick("TCS", "1", 105.0, _t(9, 21, 0))
    assert "TCS" not in engine.open_positions

    # Book is flat, but the pause must PERSIST -- no auto-resume.
    assert engine.trade_controller.is_new_entries_paused() is True

    # Only an explicit resume turns entries back on.
    engine.trade_controller.resume_new_entries()
    assert engine.trade_controller.is_new_entries_paused() is False


def test_paused_new_entries_stays_paused_while_any_position_remains_open():
    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 100.0, _t(9, 20, 0))
    engine.trade_controller.request_buy("INFY")
    engine.process_tick("INFY", "2", 200.0, _t(9, 21, 0))
    assert "TCS" in engine.open_positions
    assert "INFY" in engine.open_positions

    engine.trade_controller.request_pause_new_entries()

    # Close only ONE of the two open positions.
    engine.trade_controller.request_exit("TCS")
    engine.process_tick("TCS", "1", 105.0, _t(9, 22, 0))
    assert "TCS" not in engine.open_positions
    assert "INFY" in engine.open_positions

    # Book is not flat yet -- must still be paused.
    assert engine.trade_controller.is_new_entries_paused() is True


# ==========================================================
# Minimum tradable price -- hard floor, 2026-07-24, operator's own
# rule: "never trade in stocks which are lower than 200 rs price
# range... no matter what." These use the REAL Engine() (real
# config.MIN_TRADABLE_PRICE_RS=200), not the _engine() test helper
# above, specifically to prove the production floor actually works.
# ==========================================================

# ==========================================================
# entry_blocked_reason() -- built 12 August 2026 so core/auto_entry.py's
# risk-layer check (previously a silent no-op, see
# tests/test_a_broken_check_refuses_the_trade.py) has a real method to
# call. It crashed live at 09:30 the same morning it shipped --
# _entry_cutoff_reason() calls .time() on what it is given, and this
# passed datetime.now().time() (already a time, no .time() method)
# instead of datetime.now() (a datetime, which has one). Every ranked
# and early-bird entry that morning was refused by "the risk check
# itself failed", not by a real block. Fixed to pass the full
# datetime.now(). This test calls the REAL Engine(), not a mock, so a
# regression here fails loudly instead of being swallowed by
# auto_entry.py's own fail-closed exception handler.
#
# ---- AND THEN THEY ONLY PASSED BEFORE 15:30. 12 August 2026. ----
# Both asserted on a real Engine reading the WALL CLOCK, so from 15:30
# every evening they failed with "the market is closed (15:30)" -- true,
# and not the thing being measured. Run at 17:14 they were the only two
# red lines in a 4,025-test suite, which is how a suite stops being
# believed. Commit 1691b16 fixed this exact bug in two other files and
# these were written after it.
#
# entry_blocked_reason() now takes the moment being asked about, so the
# test states its own time instead of inheriting the machine's.
# ==========================================================

# Mid-session on a real trading Wednesday: past the 09:30 ORB close,
# well before any square-off, so nothing about the clock is in play.
MIDSESSION = datetime(2026, 8, 12, 11, 30)


def test_entry_blocked_reason_does_not_crash_on_a_real_engine():
    engine = Engine()
    # Must not raise, and with nothing actually blocking, must say so.
    assert engine.entry_blocked_reason("TCS", "LONG",
                                       at_time=MIDSESSION) is None


def test_entry_blocked_reason_reports_an_existing_block():
    engine = Engine()
    engine._block_entry("TCS", "LONG", "same-day HIGH-confidence news "
                        "points the other way")
    assert "news points the other way" in \
        engine.entry_blocked_reason("TCS", "LONG", at_time=MIDSESSION)
    # A block on one direction must not leak onto the other.
    assert engine.entry_blocked_reason("TCS", "SHORT",
                                       at_time=MIDSESSION) is None


def test_the_clock_still_blocks_when_the_market_is_shut():
    """The parameter must not have made the square-off guard optional --
    passing a time AFTER the cutoff has to still refuse."""
    engine = Engine()
    after_hours = datetime(2026, 8, 12, 17, 14)
    assert engine.entry_blocked_reason("TCS", "LONG",
                                       at_time=after_hours) is not None


def test_structural_entry_below_price_floor_is_silently_skipped():
    engine = Engine()
    _feed_orb_range(engine, low=90.0, high=100.0)
    # Breakout close at 105 -- a real ORB breakout, but still under
    # the Rs 200 floor.
    engine.process_tick("TCS", "1", 102.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 104.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    # Silent skip -- no entry_blocked entry, same "not eligible"
    # convention as the momentum-universe shortlist check.
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_structural_entry_at_or_above_price_floor_works_normally():
    # Real Engine() on purpose -- this proves the PRODUCTION price floor
    # (config.MIN_TRADABLE_PRICE_RS = 200) actually admits a stock above
    # it. alert_only is switched off because that is a different rule:
    # from 30 July 2026 config.ALERT_ONLY_MODE stops the bot buying at
    # all, which would make this test pass for the wrong reason.
    # breakout_armed likewise -- from 6 August 2026 the structural path
    # needs its own arming, and leaving it off would make this pass for
    # the wrong reason too.
    engine = Engine(alert_only=False)
    engine.breakout_armed = True
    _feed_orb_range(engine, low=190.0, high=200.0)
    engine.process_tick("TCS", "1", 205.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 212.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 211.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["entry_price"] == _bought(212.0)


def test_a_cheap_stock_is_no_longer_refused():
    """Floor removed 2026-07-29: "Remove cap on below 200 & above
    10,000 rs as we have moved from MIS to MTF". A Rs 50 stock the
    operator asks for is now bought."""
    engine = Engine()
    engine.trade_controller.request_buy("PENNY")

    engine.process_tick("PENNY", "1", 50.0, _t(9, 20, 0))

    assert "PENNY" in engine.open_positions


def test_the_floor_still_works_if_it_is_ever_put_back():
    """MIN_TRADABLE_PRICE_RS was set to 0.0 rather than deleted, so
    restoring a floor is a one-number change. That claim is only worth
    making if the plumbing behind it still runs -- this is the test
    that keeps it honest."""
    engine = Engine(min_tradable_price=200.0)
    engine.trade_controller.request_buy("PENNY")

    engine.process_tick("PENNY", "1", 50.0, _t(9, 20, 0))

    assert "PENNY" not in engine.open_positions


def test_manual_buy_at_or_above_price_floor_still_works():
    engine = Engine()
    engine.trade_controller.request_buy("TCS")

    engine.process_tick("TCS", "1", 250.0, _t(9, 20, 0))

    assert "TCS" in engine.open_positions


def test_manual_buy_is_sized_by_MTF_MARGIN_not_flat_100_shares(monkeypatch):
    """SUPERSEDED 2026-07-28 -- this used to assert 13 shares from the
    old risk formula (min(2000/stop, 200000/price)).

    That formula was replaced on the operator's own instruction:

        "Buy no of shares worth equal to 1 Lakh = mtf power. ex - as of
         now if i want to buy coforge 1686 rs - qty 225 with 99657.31
         rs worth."

    It had to go because at the 1% stop floor its two halves are
    algebraically identical -- 2000/(0.01*p) == 200000/p -- so every one
    of 2026-07-28's eighteen trades came out at Rs 1.90-2.00 lakh. It
    could not tell NILKAMAL (11% daily swing) from MANAPPURAM (2%).

    No margin book is wired here, so this exercises the OWN-CASH
    fallback: Rs 1 lakh buys Rs 1 lakh of stock. 100000 // 14610 = 6.
    The original point of the test still holds -- it must not be the old
    flat 100 shares that produced the Rs 53k APAR loss.
    """
    # These test the RISK SIZER. config.MANUAL_TEST_QTY overrides it for
    # manual clicks (Friday's one-share order), so it has to be off here
    # or they would be testing the override instead.
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", None)
    engine = _engine()
    engine.trade_controller.request_buy("APAR")
    engine.process_tick("APAR", "1", 14610.0, _t(9, 20, 0))

    assert "APAR" in engine.open_positions
    qty = engine.open_positions["APAR"]["qty"]
    assert qty == int(MTF_MARGIN_PER_POSITION_RS // 14610.0)
    assert qty * 14610.0 <= MTF_MARGIN_PER_POSITION_RS        # never more than the commitment
    assert qty != 100                      # the old flat placeholder is gone


def test_manual_buy_uses_the_MTF_margin_book_when_one_is_wired(monkeypatch):
    """With a real margin book the same Rs 1 lakh buys a LEVERAGED
    position -- the operator's COFORGE case: 225 shares, Rs 3.79L of
    stock, Rs 99,655 blocked."""
    # These test the RISK SIZER. config.MANUAL_TEST_QTY overrides it for
    # manual clicks (Friday's one-share order), so it has to be off here
    # or they would be testing the override instead.
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", None)
    from core.mtf_margin import MtfMarginBook
    book = MtfMarginBook(
        calculator=lambda sid, price, qty: {"data": {"totalMargin": price * 0.2627}}
    )
    engine = _engine(mtf_margin=book)
    engine.trade_controller.request_buy("COFORGE")
    engine.process_tick("COFORGE", "11543", 1686.0, _t(9, 20, 0))

    qty = engine.open_positions["COFORGE"]["qty"]
    assert qty == int(MTF_MARGIN_PER_POSITION_RS // (1686.0 * 0.2627))
    assert qty * 1686.0 * 0.2627 <= MTF_MARGIN_PER_POSITION_RS


def test_manual_short_is_sized_the_same_way(monkeypatch):
    # These test the RISK SIZER. config.MANUAL_TEST_QTY overrides it for
    # manual clicks (Friday's one-share order), so it has to be off here
    # or they would be testing the override instead.
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", None)
    engine = _engine()
    engine.trade_controller.request_short("APAR")
    engine.process_tick("APAR", "1", 14610.0, _t(9, 20, 0))

    assert "APAR" in engine.open_positions
    assert engine.open_positions["APAR"]["qty"] == int(MTF_MARGIN_PER_POSITION_RS // 14610.0)



def test_manual_buy_price_floor_is_injectable_and_overridable_in_tests():
    """Proves the _engine() test helper's min_tradable_price=0
    override actually works, rather than accidentally silently
    disabling the check globally in production too."""
    engine = _engine()
    engine.trade_controller.request_buy("PENNY")

    engine.process_tick("PENNY", "1", 50.0, _t(9, 20, 0))

    assert "PENNY" in engine.open_positions


def test_manual_buy_request_opens_a_position_outside_the_orb_rule():
    """
    Dashboard BUY button: a deliberate operator override, does
    NOT require a completed ORB range or a candle-close signal
    -- unlike structural entries.
    """
    engine = _engine()
    engine.trade_controller.request_buy("TCS")

    engine.process_tick("TCS", "1", 250.0, _t(9, 20, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["entry_price"] == _bought(250.0)
    assert engine.open_positions["TCS"]["entry_reason"] == "MANUAL_BUY_DASHBOARD"
    # One-shot: must not fire again on the next tick.
    engine.process_tick("TCS", "1", 251.0, _t(9, 21, 0))
    assert engine.open_positions["TCS"]["entry_price"] == _bought(250.0)


def test_manual_buy_request_is_ignored_if_already_open_no_pyramiding():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert engine.open_positions["TCS"]["entry_price"] == _bought(112.0)

    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 200.0, _t(9, 33, 0))

    # Still the original position -- manual buy request was ignored.
    assert engine.open_positions["TCS"]["entry_price"] == _bought(112.0)


def test_manual_buy_seeds_trailing_stop_from_last_closed_candle_low():
    engine = _engine()
    # A closed candle exists before the manual buy fires, and its
    # low (100) is safely below the price at buy time (106).
    engine.process_tick("TCS", "1", 100.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 21, 0))  # closes 9:20 candle, low=100
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 106.0, _t(9, 21, 30))

    assert "TCS" in engine.open_positions
    # ---- THE STOP MOVED HOUSE. 23 August 2026 ----
    # A manual buy now trails via the ATR engine, so the level lives
    # in position["atr_stop"] rather than in trailing_stop. Asking
    # _live_stop_price() instead of one particular mechanism is what
    # this test was always about -- "is the seeded stop the candle
    # low" -- and it keeps working whichever engine owns the position.
    position = engine.open_positions["TCS"]
    assert engine._live_stop_price("TCS", position) == 100.0


def test_manual_buy_falls_back_to_a_buffer_when_candle_low_is_stale_or_inverted():
    """
    If the last closed candle's low is AT or ABOVE the current
    price (price fell since that candle closed, or there's no
    candle history at all), using it as the stop would place the
    stop at/above entry -- self-triggering the trailing stop on
    the very same tick. Must fall back to a small buffer below
    entry instead.
    """
    engine = _engine()
    engine.process_tick("TCS", "1", 100.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 21, 0))  # closes 9:20 candle, low=100
    engine.trade_controller.request_buy("TCS")
    # Price (96) is now BELOW that stale candle low (100).
    engine.process_tick("TCS", "1", 96.0, _t(9, 21, 30))

    assert "TCS" in engine.open_positions
    # See the note above: a manual buy trails via the ATR engine now,
    # so ask for the stop IN FORCE rather than one mechanism's copy.
    stop = engine._live_stop_price("TCS", engine.open_positions["TCS"])
    assert stop < 96.0
    # The buffer is HARD_STOP_FROM_ENTRY_PCT -- 2.5%, the same stop the
    # bot's own entries use. It read MIN_STOP_DISTANCE_PCT (1%) until
    # 2026-08-01; that constant is the floor under the ATR TRAIL, and
    # the trail was switched off on 29 July. See
    # tests/test_manual_stop_is_the_hard_stop.py for the measurements.
    #
    # Read back off the module rather than hardcoded: the literal 0.99
    # sat here while the value it mirrored changed underneath it, which
    # is how the operator ended up trading a stop he never approved.
    import core.engine as em
    assert stop == pytest.approx(96.0 * (1 - em.HARD_STOP_FROM_ENTRY_PCT))


# -- Manual SHORT (dashboard's per-row SHORT button, Top 50 Losers) --
# Exact mirror of the manual buy tests above, direction flipped.

def test_manual_short_request_opens_a_position_outside_the_orb_rule():
    engine = _engine()
    engine.trade_controller.request_short("TCS")

    engine.process_tick("TCS", "1", 250.0, _t(9, 20, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["entry_price"] == _sold(250.0)
    assert engine.open_positions["TCS"]["direction"] == "SHORT"
    assert engine.open_positions["TCS"]["entry_reason"] == "MANUAL_SHORT_DASHBOARD"
    # One-shot: must not fire again on the next tick.
    engine.process_tick("TCS", "1", 249.0, _t(9, 21, 0))
    assert engine.open_positions["TCS"]["entry_price"] == _sold(250.0)


def test_manual_short_request_is_ignored_if_already_open_no_pyramiding():
    engine = _engine()
    _feed_orb_range(engine, low=90.0)
    engine.process_tick("TCS", "1", 92.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 88.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 89.0, _t(9, 32, 0))
    assert engine.open_positions["TCS"]["entry_price"] == _sold(88.0)

    engine.trade_controller.request_short("TCS")
    engine.process_tick("TCS", "1", 50.0, _t(9, 33, 0))

    # Still the original position -- manual short request was ignored.
    assert engine.open_positions["TCS"]["entry_price"] == _sold(88.0)


def test_manual_short_seeds_trailing_stop_from_last_closed_candle_high():
    engine = _engine()
    # A closed candle exists before the manual short fires, and its
    # high (110) is safely above the price at short time (105).
    engine.process_tick("TCS", "1", 110.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 106.0, _t(9, 21, 0))  # closes 9:20 candle, high=110
    engine.trade_controller.request_short("TCS")
    engine.process_tick("TCS", "1", 105.0, _t(9, 21, 30))

    assert "TCS" in engine.open_positions
    assert engine.trailing_stop.get_stop("TCS") == 110.0


def test_manual_short_falls_back_to_a_buffer_when_candle_high_is_stale_or_inverted():
    """
    Mirror of the manual-buy fallback test -- if the last closed
    candle's high is AT or BELOW the current price (price rose
    since that candle closed), using it as the stop would place
    the stop at/below entry -- self-triggering the trailing stop
    on the very same tick. Must fall back to a small buffer above
    entry instead.
    """
    engine = _engine()
    engine.process_tick("TCS", "1", 100.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 21, 0))  # closes 9:20 candle (single tick), high=100
    engine.trade_controller.request_short("TCS")
    # Price (104) is now ABOVE that stale candle high (100).
    engine.process_tick("TCS", "1", 104.0, _t(9, 21, 30))

    assert "TCS" in engine.open_positions
    stop = engine.trailing_stop.get_stop("TCS")
    assert stop > 104.0
    # Mirror of the manual-BUY buffer test above. 2026-08-01: moved from
    # MIN_STOP_DISTANCE_PCT (1%) to HARD_STOP_FROM_ENTRY_PCT (2.5%), and
    # read off the module rather than restated as a literal.
    import core.engine as em
    assert stop == pytest.approx(104.0 * (1 + em.HARD_STOP_FROM_ENTRY_PCT))


def test_manual_short_is_blocked_after_square_off_when_square_off_is_armed(
        monkeypatch):
    """Blocked because the bot would flatten it minutes later.

    31 July 2026: this used to be a bare "past 15:15" rule. It is now
    tied to the thing that justified it -- see
    core/engine._entry_cutoff_reason(). With FORCE_SQUARE_OFF_AT_CLOSE
    ON, the old behaviour must come back exactly.
    """
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", True)
    engine = _engine()
    engine.trade_controller.request_short("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 20, 0))

    assert "TCS" not in engine.open_positions


def test_manual_short_is_allowed_after_1515_when_carrying_overnight(
        monkeypatch):
    """
        "Pls remove this 15:15 Hard rule as we moved from MIS to MTF.
         this hard square off is not ideal to have."

    With FORCE_SQUARE_OFF_AT_CLOSE off nothing is flattened at 15:15,
    so refusing the entry was protecting it from a liquidation that no
    longer happens.
    """
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", False)
    engine = _engine()
    engine.trade_controller.request_short("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 20, 0))

    assert "TCS" in engine.open_positions


def test_manual_short_still_works_before_square_off_time():
    engine = _engine()
    engine.trade_controller.request_short("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 10, 0))

    assert "TCS" in engine.open_positions


def test_closed_position_is_recorded_with_full_history():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 120.0, _t(9, 45, 0))

    assert len(engine.closed_positions) == 1
    record = engine.closed_positions[0]
    assert record["symbol"] == "TCS"
    assert record["entry_price"] == _bought(112.0)
    assert record["exit_price"] == _sold(120.0)
    assert record["exit_reason"] == "MANUAL_EXIT"
    assert record["entry_reason"] == "STRUCTURAL_LONG_BREAKOUT"
    # entry_time is the last tick INSIDE the breakout candle
    # (9:31:30, the 112.0 tick) -- the 9:32:00 tick is what
    # CLOSED that candle and triggered the buy, not part of it.
    assert record["entry_time"] == _t(9, 31, 30)
    assert record["holding_seconds"] == (_t(9, 45, 0) - _t(9, 31, 30)).total_seconds()
    assert record["pnl"] is None  # no portfolio wired in this test


def test_portfolio_is_updated_on_buy_and_sell_when_wired_in():
    portfolio = Portfolio(starting_capital=1_000_000.0)
    engine = _engine(portfolio=portfolio)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    # The capital blocked is the price PAID, not the price wanted.
    entry = _entry_of(engine, "TCS")
    assert entry >= 112.0, "a buy cannot fill below what it asked for"
    assert portfolio.available_capital == 1_000_000.0 - entry * LAYER1_FIXED_QTY

    engine.trade_controller.request_exit_all()
    engine.process_tick("TCS", "1", 120.0, _t(9, 45, 0))

    exit_price = engine.closed_positions[0]["exit_price"]
    assert exit_price <= 120.0, "a sell cannot fill above what it asked for"
    # And the P&L is built from both fills -- which is the whole bug.
    expected = (exit_price - entry) * LAYER1_FIXED_QTY
    assert portfolio.realized_pnl == pytest.approx(expected)
    assert engine.closed_positions[0]["pnl"] == pytest.approx(expected)
    assert expected < (120.0 - 112.0) * LAYER1_FIXED_QTY, (
        "slippage must REDUCE the reported profit, never be dropped")


# ==========================================================
# TOP_N_MOMENTUM_MODE (config.py, 2026-07-24 experiment) --
# eligibility gating + fixed SL/target bracket exits.
# TOP_N_MOMENTUM_MODE defaults to True (config.py), so these tests
# just need to wire a momentum_universe in; the ones ABOVE this
# section never do, which is exactly what keeps them on the
# original ORB-boundary dynamic-trailing behaviour regardless of
# the flag's default -- see core/engine.py's
# _entry_stop_and_target() docstring.
# ==========================================================

class _FakeMomentumUniverse:
    def __init__(self, long_symbols=(), short_symbols=()):
        self.long_symbols = set(long_symbols)
        self.short_symbols = set(short_symbols)

    def is_eligible(self, symbol, direction):
        if direction == "LONG":
            return symbol in self.long_symbols
        return symbol in self.short_symbols


def test_no_shortlist_restriction_any_symbol_can_trade_with_atr_sizing():
    """2026-07-24 (evening): the frozen 9:30 top-25 shortlist was
    REMOVED. A symbol NOT on any momentum list must now trade
    normally (with ATR sizing) -- this is the whole point of the
    change, so late-day movers like TATA ELXSI / MOTILAL aren't
    locked out. The empty _FakeMomentumUniverse still signals "ATR
    sizing mode" but no longer restricts eligibility."""
    universe = _FakeMomentumUniverse(long_symbols=set(), short_symbols=set())
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["stop_mode"] == "ATR_TRAILING"


def test_momentum_mode_allows_a_structural_long_inside_the_locked_universe(monkeypatch):
    """2026-07-24 ATR redesign: stop/qty are now ATR-derived, not a
    flat rupee bracket. With _feed_orb_range(high=110)'s candles
    (100/110/105/105) plus the 108/112/111 breakout ticks, ATR(14)
    over the resulting 5 closed candles works out to 5.5 (verified
    directly against core.atr.compute_atr on this exact candle
    sequence) -> stop distance 2.5*5.5=13.75, which still sets the
    STOP.

    The SIZE, since 2026-07-29, is the operator's own rule instead:
    Rs 1 lakh of margin per position. No mtf_margin book is wired in
    a bare test engine, so it falls back to own-cash sizing --
    100000 // 112 = 892 shares.""" 
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    position = engine.open_positions["TCS"]
    assert position["qty"] == 892
    assert position["initial_stop"] == 112.0 - 13.75
    assert position["fixed_target"] is None
    assert position["stop_mode"] == "ATR_TRAILING"
    assert position["atr_stop"] == 112.0 - 13.75
    assert position["atr_extreme"] == _bought(112.0)


def test_momentum_mode_short_side_mirrors_long_gating_and_atr_sizing(monkeypatch):
    """Mirrors the LONG test above -- same seed candles, breakout
    ticks 99/95/96 instead. ATR(14) over the resulting 5 candles
    works out to 6.25 -> stop distance 2.5*6.25=15.625,
    which still sets the STOP. Size is the operator's Rs 1 lakh rule
    (2026-07-29): 100000 // 95 = 1052 shares."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)
    universe = _FakeMomentumUniverse(short_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    position = engine.open_positions["TCS"]
    assert position["direction"] == "SHORT"
    assert position["qty"] == 1052
    assert position["initial_stop"] == 95.0 + 15.625
    assert position["fixed_target"] is None
    assert position["stop_mode"] == "ATR_TRAILING"
    # (Direction-scoped eligibility no longer exists -- the frozen
    # shortlist was removed 2026-07-24 evening; any symbol can trade
    # either direction on a real breakout now.)


def test_momentum_mode_skips_entry_when_fewer_than_min_atr_candles_exist():
    """A symbol whose ORB range completed on the very first two
    ticks (no intermediate candles) won't have MIN_ATR_CANDLES(5)
    closed candles by the time a breakout could theoretically fire
    moments later -- entry must be skipped, not sized off 1-2 noisy
    candles. Silent skip, no entry_blocked entry, same convention as
    "not on today's shortlist"."""
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    # Only 2 ticks total before the breakout attempt -- far short of
    # the 5-candle floor.
    engine.process_tick("TCS", "1", 100.0, _t(9, 15, 0))
    engine.process_tick("TCS", "1", 110.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 30, 0))  # completes ORB
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_atr_trailing_target_hit_never_closes_it_no_fixed_target_exists():
    """Operator's explicit 2026-07-24 choice: no fixed target at
    all, ATR-trailing instead. A position that runs up hard must
    stay open (no target to hit) -- it only closes when the ATR
    trail itself is eventually breached."""
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["fixed_target"] is None

    # A huge favourable move -- would have closed a fixed-bracket
    # trade at +2500rs/qty long ago. Must still be open.
    engine.process_tick("TCS", "1", 200.0, _t(9, 40, 0))
    assert "TCS" in engine.open_positions


def test_atr_trailing_stop_hit_closes_the_position_at_the_current_atr_stop(monkeypatch):
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions
    stop = engine.open_positions["TCS"]["atr_stop"]
    assert stop == 112.0 - 13.75

    engine.process_tick("TCS", "1", stop, _t(9, 36, 0))
    assert "TCS" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == "TRAILING_STOP"
    # The stop is the price it TRIED to get out at. What it got is the
    # fill -- which is the point of a stop being a market order.
    assert engine.closed_positions[-1]["exit_price"] == _sold(stop)


def test_atr_trailing_stop_out_blocks_same_direction_reentry_when_flag_is_on():
    """Same operator-approved "one attempt per direction per day"
    rule as a swing trailing stop-out -- see core/engine.py's
    _exit(). EXIT_REASON_TRAILING_STOP covers both swing and ATR
    trailing exits, so this falls out of the existing rule for free."""
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    stop = engine.open_positions["TCS"]["atr_stop"]
    engine.process_tick("TCS", "1", stop, _t(9, 36, 0))
    assert "TCS" not in engine.open_positions
    assert "LONG" in engine.entry_blocked.get("TCS", {})


def test_atr_trailing_ratchets_up_on_a_favourable_candle_close_and_never_loosens(monkeypatch):
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions
    initial_stop = engine.open_positions["TCS"]["atr_stop"]

    # A strong favourable candle close should pull the ATR stop up
    # (never down) -- feed a clearly higher candle.
    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))  # closes the 130/135 candle

    new_stop = engine.open_positions["TCS"]["atr_stop"]
    assert new_stop > initial_stop

    # A mild pullback after that -- still above the current stop, so
    # the position must stay open -- must NOT drag the stop back
    # down either way.
    engine.process_tick("TCS", "1", 128.0, _t(9, 35, 0))
    engine.process_tick("TCS", "1", 126.0, _t(9, 36, 0))  # closes the 128/126 candle
    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["atr_stop"] >= new_stop


# ==========================================================
# Partial profit-taking ("dynamic position building" scale-out
# extension, config.ENABLE_PARTIAL_EXIT -- a test rig, OFF by
# default, see its docstring). Force-enabled here via monkeypatch,
# same established pattern as the BLOCK_REENTRY_AFTER_STOPOUT tests
# above -- core/engine.py imported the config name directly, so the
# module attribute is what actually needs patching.
# ==========================================================

def test_partial_exit_disabled_position_rides_uncapped(monkeypatch):
    """ENABLE_PARTIAL_EXIT=False (monkeypatched -- the shipped
    default flipped to True in the 2026-07-24 revamp) must behave
    exactly like the plain item-3 redesign, with zero partial-exit
    side effects, even on a candle that would trigger one when
    enabled -- the OFF switch has to genuinely turn it all off."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "ENABLE_PARTIAL_EXIT", False)
    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    original_qty = engine.open_positions["TCS"]["qty"]

    # Same big favourable candle the enabled tests below use to
    # trigger a partial -- must be a no-op here.
    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))

    assert engine.open_positions["TCS"]["qty"] == original_qty
    assert engine.closed_positions == []


def test_partial_exit_trims_qty_at_the_configured_atr_multiple(monkeypatch):
    """Verified directly against the real engine: entry qty=892 @
    112.00 (Rs 1 lakh of margin // 112, the operator's sizing rule
    since 2026-07-29). The 130/135/134 candle closes at
    135.00 with a freshly recomputed ATR of ~7.833 -- comfortably past
    entry_price + 2*ATR (~127.67), so the partial fires at that
    candle's own close (135.00, not the wick), trimming
    round(892*0.5)=446 shares and leaving 446 open."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "ENABLE_PARTIAL_EXIT", True)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert engine.open_positions["TCS"]["qty"] == 892

    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))

    assert "TCS" in engine.open_positions  # remainder still open
    assert engine.open_positions["TCS"]["qty"] == 446
    assert engine.open_positions["TCS"]["partial_exit_done"] is True

    assert len(engine.closed_positions) == 1
    partial = engine.closed_positions[0]
    assert partial["qty"] == 446
    assert partial["exit_price"] == _sold(135.0)
    assert partial["exit_reason"] == "PARTIAL_PROFIT_ATR"
    assert partial["entry_price"] == _bought(112.0)


def test_partial_exit_only_fires_once_even_across_many_more_candles(monkeypatch):
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "ENABLE_PARTIAL_EXIT", True)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))
    qty_after_first_partial = engine.open_positions["TCS"]["qty"]
    assert len(engine.closed_positions) == 1

    # Keep pushing the price up hard -- must NOT trigger a second partial.
    engine.process_tick("TCS", "1", 150.0, _t(9, 35, 0))
    engine.process_tick("TCS", "1", 160.0, _t(9, 35, 30))
    engine.process_tick("TCS", "1", 158.0, _t(9, 36, 0))

    assert engine.open_positions["TCS"]["qty"] == qty_after_first_partial
    assert len(engine.closed_positions) == 1


def test_partial_exit_leaves_the_atr_trail_completely_unaffected(monkeypatch):
    """The partial-exit trim changes qty ONLY -- atr_stop/atr_extreme
    ratchet exactly as they would have without it, same values a
    non-partial position would show after the identical candle
    sequence (test_atr_trailing_ratchets_up_... above)."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "ENABLE_PARTIAL_EXIT", True)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    initial_stop = engine.open_positions["TCS"]["atr_stop"]

    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))

    # Partial fired (qty dropped) AND the trail still ratcheted up
    # from this same candle, same as the non-partial test.
    assert engine.open_positions["TCS"]["qty"] == 446
    assert engine.open_positions["TCS"]["atr_stop"] > initial_stop


def test_partial_exit_skipped_when_trim_would_round_to_zero(monkeypatch):
    """A 1-share position can't be meaningfully split -- the partial
    is skipped (but still marked done, so it's not re-evaluated
    every candle for the rest of the trade). Reuses the same real,
    naturally-triggering momentum-mode scenario as the tests above,
    just shrinks qty to 1 right after entry -- round(1*0.5)=0."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "ENABLE_PARTIAL_EXIT", True)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    engine.open_positions["TCS"]["qty"] = 1

    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))

    assert engine.open_positions["TCS"]["qty"] == 1  # unchanged
    assert engine.open_positions["TCS"]["partial_exit_done"] is True
    assert engine.closed_positions == []


def test_partial_exit_credits_portfolio_and_frees_margin(monkeypatch):
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "ENABLE_PARTIAL_EXIT", True)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    portfolio = Portfolio()
    engine = _engine(momentum_universe=universe, portfolio=portfolio)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    margin_before = portfolio.used_margin(engine.open_positions)

    engine.process_tick("TCS", "1", 130.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 135.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 134.0, _t(9, 34, 0))

    # 446 shares realized, both legs at their fills rather than at the
    # intended 112 -> 135.
    trimmed = engine.closed_positions[0]
    assert trimmed["pnl"] == pytest.approx(
        446 * (trimmed["exit_price"] - trimmed["entry_price"]))
    assert trimmed["pnl"] < 446 * (135.0 - 112.0), (
        "slippage on both legs must reduce a partial exit too")
    # used_margin is derived fresh from qty*entry_price -- must have
    # dropped now that 60 fewer shares are held.
    margin_after = portfolio.used_margin(engine.open_positions)
    assert margin_after < margin_before


# ==========================================================
# Square-off gate -- real bug found live, 2026-07-23 15:18: 74 open
# positions and the bot was still trying to BUY MORE three minutes
# past SQUARE_OFF_TIME (15:15), blocked only by margin exhaustion,
# not by time. flatten_all() (main.py) is a one-shot close of
# whatever was open AT square-off -- nothing ever stopped a brand
# new entry from opening right after. See core/engine.py's
# SQUARE_OFF_T module-level comment for the full writeup.
# ==========================================================

def test_structural_entry_is_blocked_after_square_off_time():
    engine = _engine()
    _feed_orb_range(engine, high=110.0)

    # A breakout candle whose CLOSE TIME is past 15:15 must not enter.
    engine.process_tick("TCS", "1", 108.0, _t(15, 15, 30))
    engine.process_tick("TCS", "1", 112.0, _t(15, 16, 0))
    engine.process_tick("TCS", "1", 111.0, _t(15, 16, 30))

    assert "TCS" not in engine.open_positions


def test_structural_entry_still_works_right_up_to_last_entry_time():
    """Sanity check the time gates aren't overly aggressive -- a
    breakout closing BEFORE LAST_ENTRY_TIME (14:30, the 2026-07-24
    revamp's fresh-entry cutoff, tighter than square-off) must still
    enter normally."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(14, 28, 0))
    engine.process_tick("TCS", "1", 112.0, _t(14, 28, 30))
    engine.process_tick("TCS", "1", 111.0, _t(14, 29, 0))

    assert "TCS" in engine.open_positions


def test_structural_entry_still_fires_in_the_afternoon_no_cutoff():
    """2026-07-24 (evening): the 14:30 fresh-entry cutoff was REMOVED
    (operator wants full-day data before live). A breakout closing at
    15:13 -- well into the afternoon but before the 15:15 square-off
    -- must now enter normally. Only square-off stops new entries."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(15, 13, 0))
    engine.process_tick("TCS", "1", 112.0, _t(15, 13, 30))
    engine.process_tick("TCS", "1", 111.0, _t(15, 14, 0))

    assert "TCS" in engine.open_positions


def test_manual_buy_is_blocked_after_square_off_when_square_off_is_armed(
        monkeypatch):
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", True)
    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 20, 0))

    assert "TCS" not in engine.open_positions


def test_manual_buy_is_allowed_at_1520_on_mtf(monkeypatch):
    """The operator's actual Monday. He buys by hand, on MTF, to carry.
    15:20 is a legitimate overnight entry, not stray intraday
    exposure."""
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", False)
    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 20, 0))

    assert "TCS" in engine.open_positions


def test_no_entry_is_ever_accepted_after_the_market_closes(monkeypatch):
    """The one cutoff that never goes away. 15:29 is a real entry;
    15:31 is not, whatever the product."""
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", False)
    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 31, 0))

    assert "TCS" not in engine.open_positions


def test_manual_buy_still_works_before_square_off_time():
    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 500.0, _t(15, 10, 0))

    assert "TCS" in engine.open_positions


def test_74_open_positions_scenario_does_not_accept_a_new_entry_after_square_off(
        monkeypatch):
    """Reproduces the exact shape of the live bug: many positions
    already open, market data still flowing past square-off, a
    fresh breakout signal on an UNRELATED symbol arrives -- must be
    refused, not just silently ignored because of margin.

    31 July 2026: square-off is armed explicitly now. The cutoff moved
    from a bare clock to whether the bot actually flattens (see
    core/engine._entry_cutoff_reason()), and this incident only makes
    sense in the world where it does."""
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", True)
    engine = _engine()
    # Simulate a handful of pre-existing open positions (stand-in
    # for the 74 seen live) -- doesn't need real portfolio wiring,
    # just needs open_positions to be non-empty so this isn't
    # trivially the "no positions at all" case.
    for i in range(5):
        symbol = f"SYM{i}"
        engine.open_positions[symbol] = {
            "security_id": str(i), "qty": 100, "entry_price": 100.0,
            "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "entry_time": _t(9, 31, 0),
            "direction": "LONG", "initial_stop": 90.0, "fixed_target": None,
        }

    _feed_orb_range(engine, "FRESH", "99", high=110.0)
    engine.process_tick("FRESH", "99", 108.0, _t(15, 18, 0))
    engine.process_tick("FRESH", "99", 112.0, _t(15, 18, 30))
    engine.process_tick("FRESH", "99", 111.0, _t(15, 19, 0))

    assert "FRESH" not in engine.open_positions


def test_square_off_leak_boundary_candle_confirmed_by_a_1515_tick_is_blocked(
        monkeypatch):
    """#0 fix, 2026-07-24 (evening): the live leak. A breakout candle
    that BUILT during 15:14 (all its ticks < 15:15, so its own label
    time is ~15:14:59) but only CLOSES when the first 15:15:00 tick
    arrives must NOT enter -- the real execution is at/after square-
    off, racing the flatten. The guard now checks the processing
    tick_time (15:15:00), not the candle's 15:14 label.

    The RACE is the point of this test and it is unchanged. Only the
    time it guards is now derived from whether square-off is armed, so
    the test arms it."""
    import config
    monkeypatch.setattr(config, "FORCE_SQUARE_OFF_AT_CLOSE", True)
    engine = _engine()
    # Build the ORB and a breakout candle entirely within 15:14, so
    # the closing candle's own "time" is 15:14:xx (< square-off)...
    engine.process_tick("TCS", "1", 100.0, _t(9, 15, 0))
    engine.process_tick("TCS", "1", 110.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 30, 0))  # ORB complete
    engine.process_tick("TCS", "1", 108.0, _t(15, 14, 0))
    engine.process_tick("TCS", "1", 112.0, _t(15, 14, 30))
    # ...but the candle only CLOSES on the first tick of the 15:15
    # minute -- that tick_time is >= SQUARE_OFF_T, so the entry the
    # close would otherwise trigger must be blocked.
    engine.process_tick("TCS", "1", 111.0, _t(15, 15, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_structural_entry_just_before_square_off_still_fires():
    """The mirror sanity check -- a breakout whose closing tick is at
    15:14:xx (genuinely before square-off) must still enter, so the
    #0 fix isn't over-blocking the final legitimate minute."""
    engine = _engine()
    engine.process_tick("TCS", "1", 100.0, _t(9, 15, 0))
    engine.process_tick("TCS", "1", 110.0, _t(9, 20, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 30, 0))
    engine.process_tick("TCS", "1", 108.0, _t(15, 12, 0))
    engine.process_tick("TCS", "1", 112.0, _t(15, 12, 30))
    engine.process_tick("TCS", "1", 111.0, _t(15, 13, 0))  # closes @ 15:13 < 15:15

    assert "TCS" in engine.open_positions


# --------------------------------------------------------------
# Circuit-proximity (core/circuit_monitor.py) -- proactive, direction-
# agnostic close-ahead-of-lock. See config.py's CIRCUIT_PROXIMITY_PCT
# docstring for the operator instruction this implements, post-HFCL
# discussion 2026-07-23: "Bullish & Bearish irrespective we will
# close the open position before circuits." Distinct from the
# frozen-feed tests above, which only detect a lock AFTER it happens.
# --------------------------------------------------------------

class _FakeCircuitMonitor:
    """Minimal stand-in for core/circuit_monitor.py's CircuitMonitor
    -- exposes exactly the read interface core/engine.py actually
    calls (is_flagged/get_flag), settable directly by a test, no
    polling, no network, same fake-reader pattern as
    _FakeSectorMonitor/_FakeMomentumUniverse above."""
    def __init__(self):
        self._flagged = {}

    def flag(self, symbol, side="UPPER", gap_pct=0.01):
        self._flagged[symbol] = {"side": side, "gap_pct": gap_pct}

    def unflag(self, symbol):
        self._flagged.pop(symbol, None)

    def is_flagged(self, symbol):
        return symbol in self._flagged

    def get_flag(self, symbol):
        return self._flagged.get(symbol)

    def get_snapshot(self):
        """2026-07-24 revamp -- the regime gate reads this. Empty =
        fewer than REGIME_MIN_SYMBOLS usable rows = "BOTH" (fail-
        open), so these circuit-proximity tests stay regime-neutral."""
        return {}


def test_circuit_proximity_blocks_a_fresh_structural_entry():
    # 2026-07-29: the rule is direction-aware now. A LONG near its
    # UPPER circuit is the day's best position and is deliberately
    # left alone -- see tests/test_circuit_rule_direction_aware.py.
    # The trapped case this test means is the LOWER circuit.
    monitor = _FakeCircuitMonitor()
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    monitor.flag("TCS", side="LOWER")

    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions


def test_circuit_proximity_force_exits_an_open_long_position():
    # 2026-07-29: the rule is direction-aware now. A LONG near its
    # UPPER circuit is the day's best position and is deliberately
    # left alone -- see tests/test_circuit_rule_direction_aware.py.
    # The trapped case this test means is the LOWER circuit.
    """Even though UPPER is the FAVOURABLE side for a long (the
    position is winning), the operator's instruction was explicit:
    close it anyway -- no real counterparty for an exit order once
    the lock actually happens, same practical problem either way."""
    monitor = _FakeCircuitMonitor()
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    monitor.flag("TCS", side="LOWER")
    engine.process_tick("TCS", "1", 113.0, _t(9, 33, 0))

    assert "TCS" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == "CIRCUIT_PROXIMITY"


def test_circuit_proximity_force_exits_an_open_short_position():
    # 2026-07-29, direction-aware: the trap for a SHORT is the UPPER
    # circuit -- covering means BUYING, and at the upper limit there
    # are no sellers. At the LOWER limit a short is deeply in profit
    # and can cover freely, so it is left alone now.
    """The unfavourable case for a SHORT is the LOWER circuit
    (position winning but locked), and the favourable-but-still-
    closed case is the UPPER circuit (position losing) -- both must
    close, direction-agnostic, exactly like the long case above."""
    monitor = _FakeCircuitMonitor()
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, "HFCL", "9", low=100.0, high=110.0)
    engine.process_tick("HFCL", "9", 95.0, _t(9, 31, 0))
    engine.process_tick("HFCL", "9", 95.0, _t(9, 32, 0))
    assert "HFCL" in engine.open_positions

    monitor.flag("HFCL", side="UPPER")
    engine.process_tick("HFCL", "9", 94.0, _t(9, 33, 0))

    assert "HFCL" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == "CIRCUIT_PROXIMITY"


def test_circuit_proximity_exit_triggers_the_stopout_reentry_block():
    # 2026-07-29: the rule is direction-aware now. A LONG near its
    # UPPER circuit is the day's best position and is deliberately
    # left alone -- see tests/test_circuit_rule_direction_aware.py.
    # The trapped case this test means is the LOWER circuit.
    """Changed 2026-07-24 after a live bug: STYL round-tripped SHORT
    5x in 11 minutes, every exit tagged CIRCUIT_PROXIMITY, each one
    immediately followed by a fresh structural re-entry as the stock
    kept sliding toward its circuit band. A circuit-proximity exit
    now blocks same-direction re-entry for the rest of the day, same
    "one attempt per symbol per direction" rule as a stopout -- the
    opposite direction stays free (see the sibling test below)."""
    monitor = _FakeCircuitMonitor()
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    monitor.flag("TCS", side="LOWER")
    engine.process_tick("TCS", "1", 113.0, _t(9, 33, 0))
    assert "TCS" not in engine.open_positions

    # Price genuinely moves back to safety -- circuit_monitor would
    # naturally clear the flag on its next real poll (see
    # core/circuit_monitor.py's own test for that half); simulated
    # here directly since this test is about the re-entry block, not
    # the monitor's own clearing logic.
    monitor.unflag("TCS")
    assert "LONG" in engine.entry_blocked.get("TCS", {})


def test_circuit_proximity_exit_leaves_the_opposite_direction_free():
    # 2026-07-29: the rule is direction-aware now. A LONG near its
    # UPPER circuit is the day's best position and is deliberately
    # left alone -- see tests/test_circuit_rule_direction_aware.py.
    # The trapped case this test means is the LOWER circuit.
    """A LONG flagged near its circuit still leaves SHORT open on the
    same symbol, exactly like the stopout block -- a failed/flagged
    long says nothing about whether a later short setup is valid."""
    monitor = _FakeCircuitMonitor()
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    monitor.flag("TCS", side="LOWER")
    engine.process_tick("TCS", "1", 113.0, _t(9, 33, 0))
    assert "TCS" not in engine.open_positions

    assert "LONG" in engine.entry_blocked.get("TCS", {})
    assert "SHORT" not in engine.entry_blocked.get("TCS", {})


# ==========================================================
# ATR sizing safety floor/ceiling, 2026-07-24 -- SWIGGY incident
# (qty=2522 on a 46-paise stop, ATR read Rs 0.264). See config.py's
# MIN_STOP_DISTANCE_PCT/MAX_NOTIONAL_PER_TRADE_RS docstrings for the
# full writeup. compute_atr is monkeypatched to a fixed value here
# (same "patch the name engine.py imported" pattern used for the
# config constants above) so the exact ATR at entry is under test
# control instead of depending on hand-verified candle arithmetic.
# ==========================================================

def test_atr_entry_sizing_floors_stop_distance_and_caps_qty_when_atr_is_tiny(monkeypatch):
    """The STOP is still ATR-derived and still floored.

    entry_price=300, ATR patched to 0.1 -> raw stop distance
    2.5*0.1=0.25, floored up to 0.01*300=3.0 (MIN_STOP_DISTANCE_PCT).
    That floor is the point of this test and is unchanged.

    The SIZE is now the operator's rule -- Rs 1 lakh of margin per
    position, 100000 // 300 = 333 shares -- and is deliberately
    INDEPENDENT of the stop distance."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "compute_atr", lambda candles, period: 0.1)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 295.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 300.0, _t(9, 31, 30))
    # 299.0 stays above the floored stop (297.0) so the entry tick's
    # own post-entry stop check doesn't fire immediately.
    engine.process_tick("TCS", "1", 299.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    position = engine.open_positions["TCS"]
    assert position["initial_stop"] == 300.0 - 3.0
    assert position["qty"] == 333


def test_atr_entry_sizing_notional_cap_binds_independently_of_the_stop_floor(monkeypatch):
    """THE REGRESSION TEST FOR 29 JULY.

    Same entry price and the same Rs 1 lakh rule as the test above,
    but a twenty-fold larger ATR: 2.0 instead of 0.1. The stop moves
    accordingly (2.5*2.0=5.0, above the 3.0 floor, so the floor
    correctly does not bind) -- and the SHARE COUNT DOES NOT MOVE AT
    ALL. 333 either way.

    That independence is the whole fix. Until 29 July the size came
    from min(RISK_PER_TRADE_RS / stop_distance,
    MAX_NOTIONAL_PER_TRADE_RS / price), which at the 1% stop floor is
    algebraically the same number -- so the notional ceiling bound on
    every single trade and ATR did nothing. All 29 of that day's
    structural entries came out between Rs 197,041 and Rs 200,382,
    double the size the operator had specified, while his manual buys
    correctly landed at Rs 1 lakh.

    Both stale knobs are pinned to absurd values here on purpose: if
    either one ever reaches the size again, this test fails."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "compute_atr", lambda candles, period: 2.0)
    monkeypatch.setattr(engine_module, "MTF_MARGIN_PER_POSITION_RS", 100000.0)
    monkeypatch.setattr(engine_module, "RISK_PER_TRADE_RS", 1.0)
    monkeypatch.setattr(engine_module, "MAX_NOTIONAL_PER_TRADE_RS", 1.0)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 295.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 300.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 298.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    position = engine.open_positions["TCS"]
    assert position["initial_stop"] == 300.0 - 5.0
    assert position["qty"] == 333


def test_atr_trailing_ratchet_also_respects_the_min_stop_distance_floor(monkeypatch):
    """Same tiny ATR (0.1) throughout, including the post-entry
    candle-close recompute. Entry 300, so the trail-activation
    distance is max(1.0*0.1, 0.01*300)=3.0 -- once the extreme reaches
    400 (well past 300+3) the trail activates, and the trail distance
    floor is 0.01*400=4.0 (bigger than 2.5*0.1=0.25), so the ratcheted
    stop must sit exactly 4.0 below the new extreme."""
    import core.engine as engine_module
    # 2026-07-29: the ATR trail is OFF by default now (it turned
    # +Rs 21,374 of entries into -Rs 1,252 over 80 real trades).
    # Enabled explicitly here so the old path stays covered rather
    # than silently untested -- see config ENABLE_BOT_TRAILING_STOP.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    # 29 August 2026: the trail flag no longer selects the entry WIDTH
    # -- VOLATILITY_SCALED_STOP decides that on its own terms now, so
    # turning the trail on cannot silently collapse the stop to the 1%
    # floor. These tests are about the ATR-multiplier sizing, so they
    # ask for that branch directly instead of reaching it sideways.
    monkeypatch.setattr(engine_module, "VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr(engine_module, "compute_atr", lambda candles, period: 0.1)

    universe = _FakeMomentumUniverse(long_symbols={"TCS"})
    engine = _engine(momentum_universe=universe)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 295.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 300.0, _t(9, 31, 30))
    # 299.0 stays above the floored stop (297.0).
    engine.process_tick("TCS", "1", 299.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    # Favourable candle close pushing the extreme up to 400.
    engine.process_tick("TCS", "1", 395.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 400.0, _t(9, 33, 30))
    engine.process_tick("TCS", "1", 399.0, _t(9, 34, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["atr_extreme"] == 400.0
    assert engine.open_positions["TCS"]["atr_stop"] == 400.0 - 4.0


# ==========================================================
# Earnings-day entry exclusion, 2026-07-24 -- config.EARNINGS_CALENDAR.
# Structural entries only; manual buy/short are a deliberate human
# override and stay untouched. _t() fixes every test datetime to
# 2026-07-22, so that's the date used to key the patched calendar.
# ==========================================================

def test_earnings_day_structural_entry_is_silently_skipped(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "EARNINGS_CALENDAR", {"2026-07-22": {"TCS"}})

    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_earnings_day_does_not_block_a_manual_buy(monkeypatch):
    """"Auto skips, human overrides" -- same pattern as the
    new-entries-pause feature. A symbol on today's earnings list is
    still buyable manually."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "EARNINGS_CALENDAR", {"2026-07-22": {"TCS"}})

    engine = _engine()
    engine.trade_controller.request_buy("TCS")
    engine.process_tick("TCS", "1", 250.0, _t(9, 20, 0))

    assert "TCS" in engine.open_positions


def test_a_symbol_not_on_the_earnings_list_trades_normally_that_day(monkeypatch):
    """Sanity check the mechanism is symbol-specific, not a blanket
    date-wide block -- INFY on the same earnings date is untouched."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "EARNINGS_CALENDAR", {"2026-07-22": {"INFY"}})

    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


# ==========================================================
# ORB-window feed staleness, 2026-07-24 -- SONACOMS incident (bought
# on a false breakout because a ~30s stale-feed gap right at market
# open meant the true intraday high never reached orb_engine.update(),
# see core/market_data.py::is_orb_window_unreliable's docstring for
# the full writeup). market_data is optional on Engine -- these tests
# use a minimal fake exposing just that one method.
# ==========================================================

class _FakeUnreliableMarketData:
    def __init__(self, unreliable_symbols=()):
        self._unreliable = set(unreliable_symbols)

    def get_latest_price(self, symbol):
        return None

    def is_orb_window_unreliable(self, symbol):
        return symbol in self._unreliable


def test_structural_entry_is_skipped_for_a_symbol_flagged_orb_window_unreliable():
    market_data = _FakeUnreliableMarketData(unreliable_symbols={"TCS"})
    engine = _engine(market_data=market_data)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_structural_entry_works_normally_when_not_flagged_unreliable():
    market_data = _FakeUnreliableMarketData(unreliable_symbols={"INFY"})
    engine = _engine(market_data=market_data)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


def test_orb_window_unreliable_check_is_skipped_entirely_when_market_data_is_none():
    """No market_data wired up (most tests, and a valid production
    configuration) -- the check must not blow up on a None reader,
    same "optional dependency" pattern as the exit-pricing lookup."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


# ==========================================================
# 2026-07-24 REVAMP gates -- market-regime, max-open-positions,
# daily loss/profit guardrails, breakout-quality margin. See
# config.py's trading-policy block and TRADING_POLICY.md.
# ==========================================================

class _FakeRegimeCircuitMonitor:
    """Circuit-monitor fake whose snapshot paints an arbitrary
    breadth picture for the regime gate -- n_up symbols above
    prev_close, n_down below. is_flagged always False (these tests
    are about regime, not circuit proximity)."""
    def __init__(self, n_up, n_down):
        self._snap = {}
        for i in range(n_up):
            self._snap[f"UP{i}"] = {"last_price": 101.0, "prev_close": 100.0}
        for i in range(n_down):
            self._snap[f"DN{i}"] = {"last_price": 99.0, "prev_close": 100.0}

    def is_flagged(self, symbol):
        return False

    def get_flag(self, symbol):
        return None

    def get_snapshot(self):
        return self._snap


def test_regime_gate_blocks_a_long_when_the_tape_is_broadly_declining(monkeypatch):
    """7 of 10 declining (70% >= 60% threshold) -> SHORT_ONLY -> a
    perfectly valid LONG breakout is skipped, silently."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "REGIME_MIN_SYMBOLS", 5)
    # The gate is OFF in production since 2026-07-28
    # (config.ENABLE_MARKET_REGIME_GATE) -- it left the bot unable
    # to take a single long on a 67%-red tape. These two tests
    # cover the GATE ITSELF, so they switch it back on rather
    # than silently testing a code path nobody runs.
    monkeypatch.setattr(engine_module, "ENABLE_MARKET_REGIME_GATE", True)

    monitor = _FakeRegimeCircuitMonitor(n_up=3, n_down=7)
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_regime_gate_still_allows_a_short_when_the_tape_is_broadly_declining(monkeypatch):
    """Same 70%-declining tape as above -- the WITH-the-tape
    direction must still trade normally."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "REGIME_MIN_SYMBOLS", 5)

    monitor = _FakeRegimeCircuitMonitor(n_up=3, n_down=7)
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["direction"] == "SHORT"


def test_regime_gate_blocks_a_short_when_the_tape_is_broadly_advancing(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "REGIME_MIN_SYMBOLS", 5)
    # The gate is OFF in production since 2026-07-28
    # (config.ENABLE_MARKET_REGIME_GATE) -- it left the bot unable
    # to take a single long on a 67%-red tape. These two tests
    # cover the GATE ITSELF, so they switch it back on rather
    # than silently testing a code path nobody runs.
    monkeypatch.setattr(engine_module, "ENABLE_MARKET_REGIME_GATE", True)

    monitor = _FakeRegimeCircuitMonitor(n_up=7, n_down=3)
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 95.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 96.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions


def test_regime_gate_fails_open_on_a_thin_snapshot(monkeypatch):
    """Fewer than REGIME_MIN_SYMBOLS usable rows = no opinion = both
    directions allowed -- a thin 09:15 snapshot must never lock the
    bot one-sided. REGIME_MIN_SYMBOLS left at its real value (100);
    the fake only paints 10 rows."""
    monitor = _FakeRegimeCircuitMonitor(n_up=1, n_down=9)
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


def test_regime_gate_neutral_tape_allows_both_directions(monkeypatch):
    """55/45 split -- under the 60% threshold both ways -> BOTH."""
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "REGIME_MIN_SYMBOLS", 5)

    monitor = _FakeRegimeCircuitMonitor(n_up=11, n_down=9)
    engine = _engine(circuit_monitor=monitor)
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


def test_max_open_positions_cap_skips_new_signals_once_full(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "MAX_OPEN_POSITIONS", 1)

    engine = _engine()
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    _feed_orb_range(engine, "INFY", "2", low=200.0, high=220.0)

    # First entry fills the single slot.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions

    # Second, equally valid signal must be skipped -- book is full.
    engine.process_tick("INFY", "2", 221.0, _t(9, 33, 0))
    engine.process_tick("INFY", "2", 225.0, _t(9, 33, 30))
    engine.process_tick("INFY", "2", 224.0, _t(9, 34, 0))
    assert "INFY" not in engine.open_positions
    assert engine.entry_blocked.get("INFY", {}) == {}


def test_daily_loss_halt_blocks_new_entries(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "DAILY_MAX_LOSS_RS", 500.0)

    engine = _engine()
    # Seed a realized loss past the switch -- shape matches a real
    # closed_positions record's pnl field, which is all
    # _daily_realized_pnl() reads.
    engine.closed_positions.append({"symbol": "X", "pnl": -600.0})

    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions


def test_daily_profit_goal_blocks_new_entries_once_met(monkeypatch):
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "DAILY_PROFIT_TARGET_RS", 500.0)

    engine = _engine()
    engine.closed_positions.append({"symbol": "X", "pnl": 600.0})

    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions


def test_daily_guardrails_do_not_block_below_their_thresholds():
    """A modest realized loss, inside the real Rs 10k switch, must
    change nothing -- the guardrails only bite at their lines."""
    engine = _engine()
    engine.closed_positions.append({"symbol": "X", "pnl": -1500.0})

    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


def test_breakout_margin_rejects_a_close_that_barely_grazes_the_line():
    """ORB high 110 -> the 0.1% margin needs a close >= 110.11. A
    close at 110.05 'broke out' by 5 paise -- range noise, skipped.
    The SONACOMS class of entry."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 110.02, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 110.05, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 110.04, _t(9, 32, 0))

    assert "TCS" not in engine.open_positions
    assert engine.entry_blocked.get("TCS", {}) == {}


def test_breakout_margin_accepts_a_close_with_real_conviction():
    """Close 112 vs high 110 = 1.8% clear -- comfortably past the
    0.1% margin, enters normally (this is also every pre-existing
    breakout fixture in this file, all still green)."""
    engine = _engine()
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))

    assert "TCS" in engine.open_positions


def test_breakout_margin_mirrors_on_the_short_side():
    """ORB low 100 -> the margin needs a close <= 99.9. A close at
    99.95 is 5 paise of 'breakdown' -- skipped; a close at 96 is
    real -- entered."""
    engine = _engine()
    _feed_orb_range(engine, low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 99.97, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 99.95, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 99.96, _t(9, 32, 0))
    assert "TCS" not in engine.open_positions

    engine.process_tick("TCS", "1", 95.0, _t(9, 33, 0))
    engine.process_tick("TCS", "1", 96.0, _t(9, 34, 0))
    assert "TCS" in engine.open_positions
    assert engine.open_positions["TCS"]["direction"] == "SHORT"


# ==========================================================
# Trend-rank entry priority + slot rotation (2026-07-24)
# ==========================================================

class _FakeTrendCircuit:
    """Minimal circuit_monitor: serves a fixed %change snapshot for the
    trend leaderboard, flags nothing."""
    def __init__(self, snapshot):
        self._snap = snapshot

    def get_snapshot(self):
        return self._snap

    def is_flagged(self, symbol):
        return False


def _snap(**pcts):
    """Build a circuit snapshot from symbol=%change kwargs. prev_close
    is 100 for all; last_price encodes the %move so (last-prev)/prev
    == the requested pct."""
    return {sym: {"prev_close": 100.0, "last_price": 100.0 * (1 + p)}
            for sym, p in pcts.items()}


def _long_breakout(engine, sym, sid, hour=9, minute=31):
    """`hour`/`minute` let a caller place the breakout LATER in the
    session -- rotation now requires the sitting position to have been
    held ROTATION_MIN_HOLD_MINUTES before its seat can be taken."""
    _feed_orb_range(engine, sym, sid, low=100.0, high=110.0)
    engine.process_tick(sym, sid, 108.0, _t(hour, minute, 0))
    engine.process_tick(sym, sid, 112.0, _t(hour, minute, 30))
    engine.process_tick(sym, sid, 111.0, _t(hour, minute + 1, 0))


def test_trend_rank_blocks_a_long_that_is_not_a_top_gainer(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 2)
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    # X is barely positive -> NOT one of the top-2 gainers (G1, G2 are).
    snap = _snap(G1=0.05, G2=0.04, X=0.001, M=-0.001, L1=-0.04, L2=-0.05)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap))

    _long_breakout(engine, "X", "9")
    assert "X" not in engine.open_positions          # blocked: not a leader


def test_trend_rank_allows_a_long_that_is_a_top_gainer(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 2)
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    snap = _snap(X=0.06, G2=0.04, M=0.001, M2=-0.001, L1=-0.04, L2=-0.05)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap))

    _long_breakout(engine, "X", "9")
    assert "X" in engine.open_positions              # top gainer -> allowed


def test_trend_rank_fails_open_without_a_circuit_monitor():
    # No circuit_monitor -> no leaderboard -> gate is a no-op, trades
    # exactly as before.
    engine = _engine()
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions


def test_slot_rotation_evicts_the_weakest_for_a_stronger_breakout(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "MAX_OPEN_POSITIONS", 1)     # book fills at one
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)  # always recompute
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    # WEAK is a mild gainer; STRONG is a big one. Fillers are all
    # negative so both positives are top-5 gainers (eligible), and there
    # are enough symbols for the gate to be active (usable >= 2*N).
    snap = _snap(STRONG=0.05, WEAK=0.005,
                 F1=-0.01, F2=-0.02, F3=-0.03, F4=-0.04, F5=-0.05,
                 F6=-0.06, F7=-0.07, F8=-0.08)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap))

    _long_breakout(engine, "WEAK", "8")
    assert "WEAK" in engine.open_positions               # took the only slot

    # ---- THE SEAT IS HELD FOR 45 MINUTES. 23 August 2026 ----
    # Rotation had no minimum hold, which is how CDSL was bought and
    # sold ELEVEN SECONDS apart on 21 August. STRONG must now arrive
    # after ROTATION_MIN_HOLD_MINUTES -- which is what the real case
    # looks like anyway: SOLARA reached rank 1 at 10:24, an hour after
    # the seats were filled, and closed +16.4%.
    _long_breakout(engine, "STRONG", "9", hour=10, minute=31)
    # STRONG (+5%) is decisively stronger than WEAK (+0.5%) -> rotate.
    assert "STRONG" in engine.open_positions
    assert "WEAK" not in engine.open_positions
    rotated = [c for c in engine.closed_positions
               if c["symbol"] == "WEAK" and c["exit_reason"] == "ROTATED_OUT"]
    assert len(rotated) == 1


def test_a_seat_cannot_be_taken_in_the_first_minutes(monkeypatch):
    """THE CDSL CASE. Same setup, challenger arrives immediately --
    and the sitting position keeps its seat."""
    import core.engine as em
    monkeypatch.setattr(em, "MAX_OPEN_POSITIONS", 1)
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    snap = _snap(STRONG=0.05, WEAK=0.005,
                 F1=-0.01, F2=-0.02, F3=-0.03, F4=-0.04, F5=-0.05,
                 F6=-0.06, F7=-0.07, F8=-0.08)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap))

    _long_breakout(engine, "WEAK", "8")
    assert "WEAK" in engine.open_positions

    _long_breakout(engine, "STRONG", "9", hour=9, minute=35)
    assert "WEAK" in engine.open_positions, (
        "a seat was taken inside the minimum hold -- the CDSL bug")
    assert "STRONG" not in engine.open_positions


class _RecordingMemory:
    """TradeMemory stand-in that just captures what it was handed."""
    def __init__(self):
        self.records = []

    def record(self, closed_position):
        self.records.append(closed_position)
        return True


def test_completed_trade_is_recorded_with_its_entry_context(monkeypatch):
    """LEARN -> MEMORY: a closed trade must carry the CONDITIONS it was
    taken in (sector, relative strength, hour), not just the P&L --
    that's the part worth learning from later."""
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_TOP_N", 3)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)

    mem = _RecordingMemory()
    snap, mapping = _sector_world("X", "DEFENCE", 0.02, 0.04)
    engine = _engine(trade_memory=mem,
                     portfolio=Portfolio(),      # P&L comes from here
                     circuit_monitor=_FakeTrendCircuit(snap),
                     sector_monitor=_SectorAwareMonitor(mapping))

    _long_breakout(engine, "X", "9")
    assert "X" in engine.open_positions

    engine.trade_controller.request_exit("X")
    engine.process_tick("X", "9", 118.0, _t(10, 15, 0))
    assert "X" not in engine.open_positions

    assert len(mem.records) == 1
    rec = mem.records[0]
    assert rec["symbol"] == "X"
    assert rec["direction"] == "LONG"
    assert rec["sector"] == "DEFENCE"          # context, not just P&L
    assert rec["rel_strength"] is not None
    assert rec["pnl"] is not None


def test_a_broken_trade_memory_never_breaks_an_exit(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)

    class _Broken:
        def record(self, _):
            raise RuntimeError("disk full")

    engine = _engine(trade_memory=_Broken())
    _long_breakout(engine, "TCS", "1")
    engine.trade_controller.request_exit("TCS")
    engine.process_tick("TCS", "1", 115.0, _t(10, 15, 0))
    assert "TCS" not in engine.open_positions    # the exit still happened
    assert engine.closed_positions[-1]["symbol"] == "TCS"


class _FakeMemory:
    """StockMemory stand-in: returns a fixed {symbol: [reasons]} map."""
    def __init__(self, distorting=None, raises=False):
        self._d = distorting or {}
        self._raises = raises

    def price_distorting_symbols(self, on_date, window_days=1):
        if self._raises:
            raise RuntimeError("memory unavailable")
        return self._d


def test_stock_memory_blocks_a_split_symbol(monkeypatch):
    """THE JLHL CASE. On 2026-07-24 a 2:10 split read as an -80% crash
    and the bot ranked it the day's biggest loser. With memory, the
    corporate action is known and the trade is refused."""
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    engine = _engine(stock_memory=_FakeMemory({"TCS": ["SPLIT (2:10)"]}))
    _long_breakout(engine, "TCS", "1")
    assert "TCS" not in engine.open_positions
    # And it says WHY -- this block is loud, not silent.
    assert "corporate action" in engine.entry_blocked["TCS"]["LONG"]


def test_stock_memory_allows_a_clean_symbol(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    engine = _engine(stock_memory=_FakeMemory({"OTHER": ["SPLIT"]}))
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions


def test_stock_memory_fails_open_when_unavailable(monkeypatch):
    """A broken memory must never stop trading."""
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    engine = _engine(stock_memory=_FakeMemory(raises=True))
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions


def test_no_memory_wired_behaves_exactly_as_before(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    engine = _engine()                    # stock_memory=None
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions


def test_daily_pnl_carries_across_a_restart():
    """Real money risk: lose the daily limit, restart (crash / feed
    drop / code change -- all happened 2026-07-24), and the old code
    reset the counter to zero and let the bot lose it all again."""
    engine = _engine()
    assert engine._daily_realized_pnl() == 0
    engine.seed_daily_pnl(-7500.0)
    assert engine._daily_realized_pnl() == -7500.0
    # In-session P&L adds on top of what was carried in.
    engine.closed_positions.append({"pnl": -300.0})
    assert engine._daily_realized_pnl() == -7800.0


def test_seed_daily_pnl_handles_junk_safely():
    engine = _engine()
    engine.seed_daily_pnl(None)
    assert engine._daily_realized_pnl() == 0
    engine.seed_daily_pnl("not-a-number")
    assert engine._daily_realized_pnl() == 0


def test_daily_loss_halt_uses_the_carried_pnl(monkeypatch):
    """A restart must NOT re-arm the loss switch."""
    import core.engine as em
    monkeypatch.setattr(em, "DAILY_MAX_LOSS_RS", 8000.0)
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    engine = _engine()
    engine.seed_daily_pnl(-8500.0)        # already past the limit today
    _long_breakout(engine, "TCS", "1")
    assert "TCS" not in engine.open_positions


def test_liquidity_floor_blocks_a_thin_stock(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "ENABLE_LIQUIDITY_FLOOR", True)
    monkeypatch.setattr(em, "MIN_TURNOVER_RS", 20_000_000)
    # 100 shares x ~110 = Rs 11,000 turnover -- far too thin.
    cm = _FakeOHLCCircuit({"TCS": {"volume": 100, "last_price": 110.0,
                                   "prev_close": 100.0}})
    engine = _engine(circuit_monitor=cm)
    _long_breakout(engine, "TCS", "1")
    assert "TCS" not in engine.open_positions


def test_liquidity_floor_allows_a_liquid_stock(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "ENABLE_LIQUIDITY_FLOOR", True)
    monkeypatch.setattr(em, "MIN_TURNOVER_RS", 20_000_000)
    cm = _FakeOHLCCircuit({"TCS": {"volume": 5_000_000, "last_price": 110.0,
                                   "prev_close": 100.0}})
    engine = _engine(circuit_monitor=cm)
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions


def test_liquidity_floor_fails_open_without_volume_data(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "ENABLE_LIQUIDITY_FLOOR", True)
    cm = _FakeOHLCCircuit({"TCS": {"last_price": 110.0, "prev_close": 100.0}})
    engine = _engine(circuit_monitor=cm)
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions      # missing volume never blocks


def test_early_range_is_reconciled_from_the_exchange():
    """The early 5-min range is USED at ~09:21, before the main ORB
    reconcile at 09:30 -- so it needs its own exchange correction or
    early entries fire on a too-narrow, sampled range."""
    cm = _FakeOHLCCircuit({"X": {"high": 118.0, "low": 92.0,
                                 "last_price": 112.0, "prev_close": 100.0}})
    engine = _engine(circuit_monitor=cm)
    engine.process_tick("X", "9", 100.0, _t(9, 15, 0))
    engine.process_tick("X", "9", 110.0, _t(9, 17, 0))
    engine.process_tick("X", "9", 105.0, _t(9, 21, 0))   # closes early range
    engine.process_tick("X", "9", 106.0, _t(9, 22, 0))   # triggers reconcile
    early = engine.orb_engine.get_early_range("X")
    assert early["high"] == 118.0 and early["low"] == 92.0


def test_corrupt_tick_is_rejected_before_it_can_trade():
    """The INFY/JLHL class of bad data: 1037 -> 111 -> back in a
    minute. Live, that would fire every stop in the symbol. It must
    never reach the ORB range, a candle, or a position."""
    engine = _engine(enable_tick_sanity=True)
    engine.process_tick("TCS", "1", 1000.0, _t(9, 15, 0))
    engine.process_tick("TCS", "1", 1005.0, _t(9, 16, 0))
    engine.process_tick("TCS", "1", 111.0, _t(9, 17, 0))     # corrupt
    rng = engine.orb_engine.get_range("TCS")
    assert rng["low"] == 1000.0        # the garbage never widened it
    assert rng["high"] == 1005.0


def test_corrupt_tick_does_not_drag_the_reference_price():
    """A RUN of bad ticks must all be rejected -- the last GOOD price
    stays the reference, so garbage can't walk the bot down."""
    engine = _engine(enable_tick_sanity=True)
    engine.process_tick("TCS", "1", 1000.0, _t(9, 15, 0))
    for i in range(3):
        engine.process_tick("TCS", "1", 111.0, _t(9, 16 + i, 0))
    engine.process_tick("TCS", "1", 1002.0, _t(9, 20, 0))    # good again
    rng = engine.orb_engine.get_range("TCS")
    assert rng["low"] == 1000.0
    assert rng["high"] == 1002.0


def test_normal_moves_are_never_rejected():
    """A real 5% move must pass untouched."""
    engine = _engine(enable_tick_sanity=True)
    engine.process_tick("TCS", "1", 1000.0, _t(9, 15, 0))
    engine.process_tick("TCS", "1", 1050.0, _t(9, 16, 0))
    assert engine.orb_engine.get_range("TCS")["high"] == 1050.0


def test_non_positive_price_is_always_rejected():
    engine = _engine(enable_tick_sanity=False)   # even with the gate off
    engine.process_tick("TCS", "1", 100.0, _t(9, 15, 0))
    engine.process_tick("TCS", "1", 0.0, _t(9, 16, 0))
    engine.process_tick("TCS", "1", -5.0, _t(9, 17, 0))
    rng = engine.orb_engine.get_range("TCS")
    assert rng["low"] == 100.0 and rng["high"] == 100.0


class _SectorAwareMonitor:
    """sector_monitor stand-in: maps symbol -> sector, panics nothing."""
    def __init__(self, mapping):
        self.mapping = mapping

    def sector_of(self, symbol):
        return self.mapping.get(symbol)

    def is_symbol_in_panicking_sector(self, symbol):
        return False


def _sector_snap(spec):
    """spec: {symbol: pct}. Builds a circuit snapshot."""
    return {s: {"prev_close": 100.0, "last_price": 100.0 * (1 + p)}
            for s, p in spec.items()}


def _sector_world(target_sym, target_sector, target_pct, sector_pct):
    """Build a snapshot + sector map where `target_sector` has 3 members
    moving `sector_pct`, plus 9 other sectors spread out so the
    leaderboard has enough entries to be judged."""
    snap_spec, mapping = {}, {}
    for i in range(3):
        s = f"{target_sector}_{i}"
        snap_spec[s] = sector_pct; mapping[s] = target_sector
    for k in range(9):
        sec = f"SEC{k}"
        for i in range(3):
            s = f"{sec}_{i}"
            snap_spec[s] = (k - 4) * 0.004
            mapping[s] = sec
    snap_spec[target_sym] = target_pct
    mapping[target_sym] = target_sector
    return _sector_snap(snap_spec), mapping


def test_sector_gate_blocks_a_long_in_a_weak_sector(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_TOP_N", 3)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_REFRESH_SECONDS", 0)
    # X's own sector is the WORST performer -> a long there is refused.
    snap, mapping = _sector_world("X", "LAGGARD", 0.02, -0.05)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap),
                     sector_monitor=_SectorAwareMonitor(mapping))
    _long_breakout(engine, "X", "9")
    assert "X" not in engine.open_positions


def test_sector_gate_allows_a_long_in_a_leading_sector(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_TOP_N", 3)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_REFRESH_SECONDS", 0)
    snap, mapping = _sector_world("X", "LEADER", 0.02, 0.05)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap),
                     sector_monitor=_SectorAwareMonitor(mapping))
    _long_breakout(engine, "X", "9")
    assert "X" in engine.open_positions


def test_sector_gate_fails_open_without_a_sector_monitor(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(_sector_snap({"X": 0.02})))
    _long_breakout(engine, "X", "9")
    assert "X" in engine.open_positions


def test_early_momentum_entry_fires_before_the_full_orb(monkeypatch):
    """A strong name in a leading sector can break its FIVE-minute
    range at ~09:22 instead of waiting for the 09:30 ORB."""
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_TOP_N", 3)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    snap, mapping = _sector_world("X", "LEADER", 0.03, 0.05)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap),
                     sector_monitor=_SectorAwareMonitor(mapping),
                     enable_rs_band=False)

    # Build the 09:15-09:19 early range 100-110, then break it at 09:22.
    engine.process_tick("X", "9", 100.0, _t(9, 15, 0))
    engine.process_tick("X", "9", 110.0, _t(9, 17, 0))
    engine.process_tick("X", "9", 105.0, _t(9, 19, 30))
    engine.process_tick("X", "9", 112.0, _t(9, 21, 0))   # closes early range
    engine.process_tick("X", "9", 113.0, _t(9, 22, 0))   # breakout candle closes
    engine.process_tick("X", "9", 113.0, _t(9, 23, 0))
    assert "X" in engine.open_positions


def test_early_momentum_entry_refuses_a_weak_relative_strength(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_TOP_N", 3)
    monkeypatch.setattr(em, "SECTOR_STRENGTH_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "EARLY_ENTRY_MIN_RS", 0.05)   # very high bar
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    snap, mapping = _sector_world("X", "LEADER", 0.005, 0.05)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap),
                     sector_monitor=_SectorAwareMonitor(mapping),
                     enable_rs_band=False)

    engine.process_tick("X", "9", 100.0, _t(9, 15, 0))
    engine.process_tick("X", "9", 110.0, _t(9, 17, 0))
    engine.process_tick("X", "9", 105.0, _t(9, 19, 30))
    engine.process_tick("X", "9", 112.0, _t(9, 21, 0))
    engine.process_tick("X", "9", 113.0, _t(9, 22, 0))
    engine.process_tick("X", "9", 113.0, _t(9, 23, 0))
    assert "X" not in engine.open_positions


def test_early_momentum_is_off_after_the_orb_window():
    """Past 09:30 the normal path owns entries -- the early path must
    not double-fire."""
    engine = _engine()
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 112.0, _t(9, 45, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 46, 0))
    assert engine._early_entries_taken == 0


class _FakeOHLCCircuit:
    """circuit_monitor stand-in serving the exchange's own day OHLC."""
    def __init__(self, snapshot):
        self._snap = snapshot

    def get_snapshot(self):
        return self._snap

    def is_flagged(self, symbol):
        return False


def test_orb_range_widens_to_the_exchange_high_low():
    """The sampled tick feed misses real trades, so the tick-built ORB
    is too NARROW and manufactures false breakouts (ZENTEC seen
    1784.20 vs real 1792.00, live 2026-07-24). Once the window closes,
    the exchange's own high/low must widen it."""
    cm = _FakeOHLCCircuit({"TCS": {"high": 115.0, "low": 95.0,
                                   "last_price": 105.0, "prev_close": 100.0}})
    engine = _engine(circuit_monitor=cm)
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    # A candle close after the window triggers the one-shot reconcile.
    engine.process_tick("TCS", "1", 105.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 32, 0))
    rng = engine.orb_engine.get_range("TCS")
    assert rng["high"] == 115.0        # widened up
    assert rng["low"] == 95.0          # widened down


def test_orb_reconcile_never_narrows_a_range():
    """A REST snapshot can lag; a tick we genuinely saw is real data
    and must never be discarded."""
    cm = _FakeOHLCCircuit({"TCS": {"high": 108.0, "low": 102.0,
                                   "last_price": 105.0, "prev_close": 100.0}})
    engine = _engine(circuit_monitor=cm)
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 105.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 105.0, _t(9, 32, 0))
    rng = engine.orb_engine.get_range("TCS")
    assert rng["high"] == 110.0        # kept the wider tick-built high
    assert rng["low"] == 100.0


def test_orb_reconcile_fails_open_without_a_snapshot():
    engine = _engine()                 # no circuit_monitor at all
    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 105.0, _t(9, 31, 0))
    rng = engine.orb_engine.get_range("TCS")
    assert rng == {"high": 110.0, "low": 100.0}


def _wide_snap(target_pct, sym="X"):
    """A snapshot with `sym` at target_pct and 20 filler symbols spread
    around 0, so the market MEDIAN is ~0 and relative strength ~= the
    symbol's own move (keeps the band tests readable). Enough symbols
    that the usable>=2N guard passes."""
    snap = {sym: {"prev_close": 100.0, "last_price": 100.0 * (1 + target_pct)}}
    for i in range(20):
        p = (i - 10) * 0.0002          # tiny spread, median ~0
        snap[f"F{i}"] = {"prev_close": 100.0, "last_price": 100.0 * (1 + p)}
    return snap


def _rs_engine(monkeypatch, pct):
    import core.engine as em
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "RS_BAND_MIN", 0.006)
    monkeypatch.setattr(em, "RS_BAND_MAX", 0.030)
    monkeypatch.setattr(em, "MAX_ABS_MOVE_PCT", 0.05)
    return _engine(circuit_monitor=_FakeTrendCircuit(_wide_snap(pct)),
                   enable_rs_band=True)


class _GapMarketData:
    """market_data stand-in with a controllable day-open and last price."""
    def __init__(self, day_open, last):
        self._open, self._last = day_open, last

    def get_day_open(self, symbol):
        return self._open

    def get_latest_price(self, symbol):
        return self._last

    def is_orb_window_unreliable(self, symbol):
        return False


def _range_circuit(high, low, last):
    return _FakeOHLCCircuit({"X": {"high": high, "low": low,
                                   "last_price": last, "prev_close": 100.0}})


def test_a_big_mover_still_at_its_high_IS_tradeable(monkeypatch):
    """The operator's objection: the day's BEST trend is by definition
    the stock that moved most. Up 7% and still making highs is the trend
    of the day -- it must be tradeable."""
    import core.engine as em
    monkeypatch.setattr(em, "STILL_TRENDING_MIN_POSITION", 0.65)
    engine = _engine(market_data=_GapMarketData(100.0, 107.0),
                     circuit_monitor=_range_circuit(high=107.0, low=100.0,
                                                    last=107.0))
    assert engine._is_still_trending("X", "LONG") is True


def test_the_same_big_mover_ROLLED_OVER_is_refused(monkeypatch):
    """Peaked at 109, back to 103 -- same 'percent up today', but the
    move is spent. The old flat ceiling could not tell these apart."""
    import core.engine as em
    monkeypatch.setattr(em, "STILL_TRENDING_MIN_POSITION", 0.65)
    engine = _engine(market_data=_GapMarketData(100.0, 103.0),
                     circuit_monitor=_range_circuit(high=109.0, low=100.0,
                                                    last=103.0))
    assert engine._is_still_trending("X", "LONG") is False


def test_short_side_is_mirrored(monkeypatch):
    """A short needs price near the day's LOW."""
    import core.engine as em
    monkeypatch.setattr(em, "STILL_TRENDING_MIN_POSITION", 0.65)
    engine = _engine(market_data=_GapMarketData(100.0, 93.0),
                     circuit_monitor=_range_circuit(high=100.0, low=93.0,
                                                    last=93.0))
    assert engine._is_still_trending("X", "SHORT") is True
    # bounced back up off the low -> no longer trending down
    engine2 = _engine(market_data=_GapMarketData(100.0, 98.0),
                      circuit_monitor=_range_circuit(high=100.0, low=91.0,
                                                     last=98.0))
    assert engine2._is_still_trending("X", "SHORT") is False


def test_still_trending_fails_open_without_a_usable_range():
    engine = _engine(market_data=_GapMarketData(100.0, 105.0))  # no monitor
    assert engine._is_still_trending("X", "LONG") is True
    flat = _engine(market_data=_GapMarketData(100.0, 100.0),
                   circuit_monitor=_range_circuit(high=100.0, low=100.0,
                                                  last=100.0))
    assert flat._is_still_trending("X", "LONG") is True


def test_gap_up_stock_is_NOT_treated_as_exhausted(monkeypatch):
    """THE FIX. Closed 100, gapped to 106 on real news, now 109.
    Measured from yesterday's close that reads +9% -> the old code
    blocked it all day. Measured from the OPEN it is +2.8% -- barely
    started -- and it must be allowed to trade."""
    import core.engine as em
    monkeypatch.setattr(em, "MAX_ABS_MOVE_PCT", 0.05)
    engine = _engine(market_data=_GapMarketData(day_open=106.0, last=109.0))
    assert engine._is_exhausted("X") is False        # +2.8% intraday


def test_a_genuinely_spent_intraday_move_is_still_blocked(monkeypatch):
    """The ceiling still works -- opened 100, now 107 = +7% intraday,
    with no gap involved. That IS exhaustion."""
    import core.engine as em
    monkeypatch.setattr(em, "MAX_ABS_MOVE_PCT", 0.05)
    engine = _engine(market_data=_GapMarketData(day_open=100.0, last=107.0))
    assert engine._is_exhausted("X") is True


def test_gap_down_stock_is_also_judged_on_intraday_only(monkeypatch):
    """Mirror case for shorts: gapped down hard, then drifted slightly."""
    import core.engine as em
    monkeypatch.setattr(em, "MAX_ABS_MOVE_PCT", 0.05)
    engine = _engine(market_data=_GapMarketData(day_open=92.0, last=90.0))
    assert engine._is_exhausted("X") is False        # -2.2% intraday


def test_exhaustion_fails_open_without_a_day_open():
    """No day-open known (no tick yet, or market_data not wired) means we
    cannot judge -- so it must not block."""
    engine = _engine()                                # no market_data
    assert engine._is_exhausted("X") is False
    engine2 = _engine(market_data=_GapMarketData(day_open=0, last=100.0))
    assert engine2._is_exhausted("X") is False


def test_rs_band_blocks_a_breakout_below_the_band(monkeypatch):
    """+0.2% vs market is noise, not outperformance -- no trade."""
    engine = _rs_engine(monkeypatch, 0.002)
    _long_breakout(engine, "X", "9")
    assert "X" not in engine.open_positions


def test_rs_band_allows_a_breakout_inside_the_band(monkeypatch):
    """+1.5% vs market sits in the sweet spot -> trade."""
    engine = _rs_engine(monkeypatch, 0.015)
    _long_breakout(engine, "X", "9")
    assert "X" in engine.open_positions


def test_rs_band_blocks_an_exhausted_breakout_above_the_band(monkeypatch):
    """+4% vs market is past the band -- the 2026-07-24 study's
    inverted-U: the most extended names underperform."""
    engine = _rs_engine(monkeypatch, 0.04)
    _long_breakout(engine, "X", "9")
    assert "X" not in engine.open_positions


def test_rs_band_fails_open_without_ranking_data():
    """No circuit_monitor -> no leaderboard -> gate must not block."""
    engine = _engine(enable_rs_band=True)
    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions


def test_one_trade_per_symbol_per_day_blocks_a_second_attempt(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "BLOCK_REENTRY_AFTER_STOPOUT", False)
    engine = _engine(one_trade_per_symbol=True)

    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions
    # Close it by hand (not a stop-out, so the stopout block is not
    # what's being tested here), then try to re-enter on a fresh cross.
    engine.trade_controller.request_exit("TCS")
    engine.process_tick("TCS", "1", 111.0, _t(9, 33, 0))
    assert "TCS" not in engine.open_positions

    engine.process_tick("TCS", "1", 108.0, _t(9, 40, 0))
    engine.process_tick("TCS", "1", 113.0, _t(9, 41, 0))
    engine.process_tick("TCS", "1", 113.0, _t(9, 42, 0))
    assert "TCS" not in engine.open_positions      # one attempt only


def test_staged_entry_caps_positions_early_in_the_session(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "STAGED_POSITION_LIMITS", [("10:00", 2), ("14:00", 10)])
    monkeypatch.setattr(em, "STAGED_NO_ENTRY_AFTER", "14:00")
    engine = _engine(enable_staged_entry=True)

    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        _long_breakout(engine, sym, str(i + 1))
    # Before 10:00 the cap is 2 -- the third breakout gets no slot.
    assert len(engine.open_positions) == 2


def test_staged_entry_blocks_everything_after_the_cutoff(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "STAGED_NO_ENTRY_AFTER", "14:00")
    engine = _engine(enable_staged_entry=True)

    _feed_orb_range(engine, "TCS", "1", low=100.0, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(14, 20, 0))
    engine.process_tick("TCS", "1", 112.0, _t(14, 21, 0))
    engine.process_tick("TCS", "1", 111.0, _t(14, 22, 0))
    assert "TCS" not in engine.open_positions


def test_no_progress_exit_closes_dead_money(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "NO_PROGRESS_MINUTES", 30)
    monkeypatch.setattr(em, "NO_PROGRESS_R", 0.5)
    engine = _engine(enable_no_progress=True)

    _long_breakout(engine, "TCS", "1")
    assert "TCS" in engine.open_positions
    # 31 minutes later, price has gone nowhere -> freed.
    engine.process_tick("TCS", "1", 112.2, _t(10, 3, 0))
    assert "TCS" not in engine.open_positions
    assert engine.closed_positions[-1]["exit_reason"] == "NO_PROGRESS"


def test_no_progress_exit_leaves_a_working_trade_alone(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    monkeypatch.setattr(em, "NO_PROGRESS_MINUTES", 30)
    monkeypatch.setattr(em, "NO_PROGRESS_R", 0.5)
    engine = _engine(enable_no_progress=True)

    _long_breakout(engine, "TCS", "1")
    entry = engine.open_positions["TCS"]["entry_price"]
    risk = entry - engine.open_positions["TCS"]["initial_stop"]
    # Comfortably beyond +0.5R -> it IS working, must not be closed.
    engine.process_tick("TCS", "1", entry + 2 * risk, _t(10, 3, 0))
    assert "TCS" in engine.open_positions


def test_no_rotation_when_the_challenger_is_not_clearly_stronger(monkeypatch):
    import core.engine as em
    monkeypatch.setattr(em, "MAX_OPEN_POSITIONS", 1)
    monkeypatch.setattr(em, "TREND_RANK_TOP_N", 5)
    monkeypatch.setattr(em, "TREND_RANK_REFRESH_SECONDS", 0)
    monkeypatch.setattr(em, "ENABLE_VOLUME_FILTER", False)
    # HOLD and NEW are near-identical strength -> no eviction (needs a
    # clear ROTATION_MIN_STRENGTH_EDGE).
    snap = _snap(HOLD=0.020, NEW=0.021,
                 F1=-0.01, F2=-0.02, F3=-0.03, F4=-0.04, F5=-0.05,
                 F6=-0.06, F7=-0.07, F8=-0.08)
    engine = _engine(circuit_monitor=_FakeTrendCircuit(snap))

    _long_breakout(engine, "HOLD", "8")
    assert "HOLD" in engine.open_positions

    _long_breakout(engine, "NEW", "9")
    assert "HOLD" in engine.open_positions               # not evicted
    assert "NEW" not in engine.open_positions            # book stays full


# ---------------------------------------------------------------
# MTF: hold overnight instead of flattening at 15:15 (2026-07-28).
# Square-off is MIS machinery. It closed TVSMOTOR and CUB on the day
# the operator had already moved to MTF to hold for days.
# ---------------------------------------------------------------

def test_carry_forward_reports_instead_of_closing():
    """The whole point: positions must STILL BE OPEN afterwards."""
    engine = _engine()
    engine.open_positions["TVSMOTOR"] = {
        "entry_price": 3991.0, "qty": 50, "direction": "LONG",
        "stop": 3957.53, "security_id": 1,
    }
    engine.report_carry_forward(lambda s: 3997.10)
    assert "TVSMOTOR" in engine.open_positions
    assert engine.closed_positions == []


def test_carry_forward_on_an_empty_book_is_harmless():
    engine = _engine()
    engine.report_carry_forward(lambda s: 100.0)
    assert engine.open_positions == {}


def test_carry_forward_survives_a_missing_price():
    """No live price must not stop the report or close the position."""
    engine = _engine()
    engine.open_positions["CUB"] = {
        "entry_price": 239.61, "qty": 834, "direction": "LONG",
        "stop": 237.21, "security_id": 2,
    }
    engine.report_carry_forward(lambda s: None)
    assert "CUB" in engine.open_positions


def test_square_off_never_books_a_fake_flat_pnl_on_a_missing_price():
    """It used to fall back to the position's OWN ENTRY price, recording
    a perfectly flat P&L for a trade that had one -- a silent
    falsification of the book. It must skip and stay open instead."""
    engine = _engine()
    engine.open_positions["CUB"] = {
        "entry_price": 239.61, "qty": 834, "direction": "LONG",
        "stop": 237.21, "security_id": 2,
    }
    engine.flatten_all(lambda s: None)
    assert "CUB" in engine.open_positions
    assert engine.closed_positions == []


def test_square_off_still_closes_when_a_price_is_available():
    engine = _engine()
    engine.open_positions["CUB"] = {
        "entry_price": 239.61, "qty": 834, "direction": "LONG",
        "stop": 237.21, "security_id": 2,
    }
    engine.flatten_all(lambda s: 240.40)
    assert "CUB" not in engine.open_positions


# ---------------------------------------------------------------
# MARKET REGIME GATE, switched off 2026-07-28.
#
# On that day 445 of 665 symbols were declining, the regime read
# SHORT_ONLY, and the operator -- who trades LONG ONLY -- had a bot that
# could not take a single entry, silently, all session. CUB reported and
# went +8.47% on that same tape.
# ---------------------------------------------------------------

def test_a_long_is_allowed_on_a_red_tape_when_the_gate_is_off(monkeypatch):
    import core.engine as eng
    monkeypatch.setattr(eng, "ENABLE_MARKET_REGIME_GATE", False)
    engine = _engine()
    monkeypatch.setattr(engine, "_market_regime", lambda: "SHORT_ONLY")
    engine.trade_controller.request_buy("CUB")
    engine.process_tick("CUB", "1", 240.0, _t(9, 45, 0))
    assert "CUB" in engine.open_positions


def test_the_gate_still_blocks_when_switched_back_on(monkeypatch):
    """Not deleted -- one flag away. "Trade with the tape" may prove
    right once there is data to judge it on."""
    import core.engine as eng
    monkeypatch.setattr(eng, "ENABLE_MARKET_REGIME_GATE", True)
    engine = _engine()
    monkeypatch.setattr(engine, "_market_regime", lambda: "SHORT_ONLY")
    engine.process_tick("CUB", "1", 240.0, _t(9, 20, 0))
    engine.process_tick("CUB", "1", 250.0, _t(9, 45, 0))
    assert "CUB" not in engine.open_positions


# ==========================================================
# ALERT ONLY -- the bot stops trading and starts telling
# ==========================================================
#     "we will stop completely bot from trade taking as of now. it must
#      show me the stock in alerts only."   -- operator, 30 July 2026
#
# Why: on 30 July the bot placed 16 of 29 trades between 09:31 and 09:35,
# filling all ten slots in four minutes, then refused 665 signals for the
# rest of the day. It took THYROCARE on 0.03x volume because a slot was
# free and six minutes later refused KSB on 715x volume because the book
# was full. Nothing compared them -- there is no ranking between
# candidates, only per-stock gates and arrival order.

def test_alert_only_does_not_buy():
    engine = _engine(alert_only=True)
    _feed_orb_range(engine, high=110.0)
    # Same sequence as test_breakout_close_triggers_a_paper_buy: the third
    # tick lands in a NEW minute, which is what closes the 112 candle.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert not engine.open_positions, \
        "alert-only mode bought something"


def test_alert_only_still_raises_an_alert_naming_the_stock():
    """Silence is the failure mode to avoid. trade_controller's pause
    already skips entries -- but SILENTLY, by design ("no log line"),
    because it fires on every candle close. The whole point here is to be
    told, so this is a separate path that speaks."""
    engine = _engine(alert_only=True)
    _feed_orb_range(engine, high=110.0)
    # Same sequence as test_breakout_close_triggers_a_paper_buy: the third
    # tick lands in a NEW minute, which is what closes the 112 candle.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    alerts = engine.get_manual_alerts()
    assert alerts, "the signal was dropped in silence"
    assert any(a.get("symbol") == "TCS" for a in alerts)
    text = " ".join(str(a.get("message", "")) for a in alerts)
    assert "ALERT ONLY" in text, "he cannot tell whether the bot acted"

    # ---- THE WORDING CHANGED, THE MEANING DID NOT. 19 Aug 2026 ----
    # This asserted "would have been entered". He asked for a fixed
    # field order instead:
    #
    #     "TIME  SYMBOL BUY REASON QTY  ENTRY - TARGET - EXIT -
    #      TRAILING POINTS"
    #
    # So the hypothetical is now carried by ALERT ONLY above, and what
    # this test actually needs to guarantee is that the alert still
    # names the price and the size it would have taken -- an alert
    # without those is a notification, not a trade he can act on.
    assert "entry" in text
    assert "qty" in text
    assert "exit" in text


def test_alert_only_ignores_a_full_book():
    """THE bug this nearly shipped with.

    The slot cap returns BEFORE the alert point. The operator is carrying
    10 positions into the next session and MAX_OPEN_POSITIONS is 10, so
    the book is full at 09:15 -- every signal would have died at the cap
    and alert-only mode would have produced ZERO alerts all day. A silent
    bot looks exactly like a quiet market.

    Capacity limits how much money is committed. In alert-only mode
    nothing is committed, so they do not apply.
    """
    engine = _engine(alert_only=True)
    # Fill the book well past any cap.
    for i in range(12):
        engine.open_positions[f"FILLER{i}"] = {
            "security_id": str(100 + i), "qty": 1, "entry_price": 100.0,
            "direction": "LONG", "entry_reason": "test",
        }
    _feed_orb_range(engine, high=110.0)
    # Same sequence as test_breakout_close_triggers_a_paper_buy: the third
    # tick lands in a NEW minute, which is what closes the 112 candle.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert any(a.get("symbol") == "TCS" for a in engine.get_manual_alerts()), \
        "a full book silenced the alert -- capacity must not gate telling"


def test_alert_only_off_still_trades():
    """The switch must be a switch, not a one-way door."""
    engine = _engine(alert_only=False)
    _feed_orb_range(engine, high=110.0)
    # Same sequence as test_breakout_close_triggers_a_paper_buy: the third
    # tick lands in a NEW minute, which is what closes the 112 candle.
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 111.0, _t(9, 32, 0))
    assert "TCS" in engine.open_positions


# ===================================================================
# THE SWITCH THAT ARMED TWO BUYERS
# ===================================================================
#
#     "even morning i asked can bot trade ? u replied with all rules .
#      but again random entries taken that too with 1 L capital right?"
#                                       -- operator, 6 August 2026
#
# He was told the RANKER's rules -- up 1%, above its own open, a
# written reason, beating its sector, liquid enough. He turned bot
# trading ON. Every fill that day came from the STRUCTURAL BREAKOUT
# path, which applies none of those:
#
#     EXIDEIND JAMNAAUTO BASF JKLAKSHMI RHIM BELRISE VGUARD GMDCLTD
#
# Both paths read engine.alert_only, so one switch armed both.
#
# These two tests drive a real Engine -- not _engine(), which arms the
# breakout for the mechanics suite -- and prove the default refuses.
def test_bot_trading_on_does_not_arm_the_breakout():
    """alert_only=False must NOT be enough to buy a level break."""
    engine = Engine(alert_only=False, min_tradable_price=0,
                    enable_rs_band=False, enable_staged_entry=False,
                    one_trade_per_symbol=False, enable_no_progress=False,
                    enable_tick_sanity=False)
    assert engine.breakout_armed is False, (
        "the breakout must be off until it is armed on its own")
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 112.5, _t(9, 32, 0))
    assert "TCS" not in engine.open_positions, (
        "bot trading ON bought a breakout -- this is the 6 August bug")


def test_arming_the_breakout_explicitly_lets_it_trade_again():
    """It is a switch, not a removal. He can still turn it on."""
    engine = Engine(alert_only=False, min_tradable_price=0,
                    enable_rs_band=False, enable_staged_entry=False,
                    one_trade_per_symbol=False, enable_no_progress=False,
                    enable_tick_sanity=False)
    engine.breakout_armed = True
    _feed_orb_range(engine, high=110.0)
    engine.process_tick("TCS", "1", 108.0, _t(9, 31, 0))
    engine.process_tick("TCS", "1", 112.0, _t(9, 31, 30))
    engine.process_tick("TCS", "1", 112.5, _t(9, 32, 0))
    assert "TCS" in engine.open_positions, (
        "armed explicitly, the breakout must still work")

# ---------------------------------------------------------------
# A BREAKOUT MAKES THE HIGH. IT DOES NOT RETURN TO IT.
# ---------------------------------------------------------------
#
#     "bot alert system unable to identify the difference of fresh
#      breakout or fall backs . just now alert triggered =
#      NAVINFLUOR LONG would have been entered at 8240.00 ... but this
#      stock had made high 8300 rs & fell to current levels.
#      MAKE SURE THE BOT LEARN ABOUT THESE BREAKOUTS."
#                                 -- operator, 18 August 2026, 12:30
#
# The real numbers off the board that minute:
#
#     open 8155   HIGH 8300   low 8151   ltp 8247   +1.18%
#     ORB (09:15-09:30)  high 8230  low 8151
#
# The structural path measures the break against the ORB, and the ORB
# is FIXED AT 09:30. So a re-cross of 8230 at 12:30 -- after the stock
# had run to 8300 and come back -- read as a fresh break of it.
#
# _is_still_trending() was the only gate in the way and it answers a
# different question: position inside the day range, generous at 0.65.
# NAVINFLUOR sat at (8240-8151)/(8300-8151) = 0.60 of its range and
# 0.72% under its high. The range test is not able to say "this high
# is already history"; that is what these tests pin.

from core import tick_ohlc as _tick_ohlc


def _breakout_engine():
    engine = _engine()
    _tick_ohlc.reset()
    return engine


def test_the_navinfluor_alert_is_refused():
    """THE EXACT CASE HE SENT, with his numbers."""
    engine = _breakout_engine()
    _tick_ohlc.remember("NAVINFLUOR", {
        "open": 8155.0, "high": 8300.0, "low": 8151.0, "close": 8151.0,
        "LTP": 8247.0})
    assert engine._is_at_the_days_extreme(
        "NAVINFLUOR", "LONG", {"close": 8240.0}) is False
    _tick_ohlc.reset()


def test_a_close_that_makes_the_high_is_allowed():
    """The control. Without it a gate that always refuses would pass
    the test above and take the whole lane down with it."""
    engine = _breakout_engine()
    _tick_ohlc.remember("FRESH", {"open": 100.0, "high": 108.0,
                                  "low": 99.0, "close": 99.0, "LTP": 108.0})
    assert engine._is_at_the_days_extreme(
        "FRESH", "LONG", {"close": 108.0}) is True
    _tick_ohlc.reset()


def test_a_close_a_whisker_under_the_high_is_still_a_breakout():
    """A breakout candle rarely closes exactly on its own high. 0.1%
    is the wick; 0.72% is a stock that went there and came back."""
    engine = _breakout_engine()
    _tick_ohlc.remember("WICK", {"open": 100.0, "high": 108.0,
                                 "low": 99.0, "close": 99.0, "LTP": 107.9})
    assert engine._is_at_the_days_extreme(
        "WICK", "LONG", {"close": 107.9}) is True
    _tick_ohlc.reset()


def test_the_short_side_is_mirrored_against_the_low():
    engine = _breakout_engine()
    _tick_ohlc.remember("DOWN", {"open": 100.0, "high": 101.0,
                                 "low": 92.0, "close": 100.0, "LTP": 95.0})
    assert engine._is_at_the_days_extreme(
        "DOWN", "SHORT", {"close": 95.0}) is False
    assert engine._is_at_the_days_extreme(
        "DOWN", "SHORT", {"close": 92.05}) is True
    _tick_ohlc.reset()


def test_it_fails_OPEN_when_the_feed_has_told_it_nothing():
    """A missing reading is not a refusal -- same posture as every
    other gate on this path. A gate that refuses on absent data would
    silence the whole lane the first morning a tick was late."""
    engine = _breakout_engine()
    assert engine._is_at_the_days_extreme(
        "NEVERSEEN", "LONG", {"close": 100.0}) is True
    _tick_ohlc.remember("ZERO", {"open": 0, "high": 0, "low": 0, "close": 0})
    assert engine._is_at_the_days_extreme(
        "ZERO", "LONG", {"close": 100.0}) is True
    assert engine._is_at_the_days_extreme("X", "LONG", None) is True
    assert engine._is_at_the_days_extreme("X", "LONG", {"close": None}) is True
    _tick_ohlc.reset()


def test_the_refusal_is_recorded_where_he_can_read_it():
    """A silent skip is indistinguishable from a bot that never saw
    the stock, and he asked to be able to tell the two apart."""
    engine = _breakout_engine()
    _tick_ohlc.remember("NAVINFLUOR", {"open": 8155.0, "high": 8300.0,
                                       "low": 8151.0, "close": 8151.0})
    engine._is_at_the_days_extreme("NAVINFLUOR", "LONG", {"close": 8240.0})
    blocks = engine.export_entry_blocks() or {}
    said = str(blocks)
    assert "8300" in said and "not a fresh breakout" in said
    _tick_ohlc.reset()


def test_the_gate_reads_the_feed_not_the_opening_range():
    """The ORB is fixed at 09:30 and is precisely what made a stale
    level look fresh. If this gate ever starts asking orb_engine, the
    bug is back."""
    import inspect
    from core.engine import Engine
    body = inspect.getsource(Engine._is_at_the_days_extreme)
    code = chr(10).join(ln for ln in body.splitlines()
                        if not ln.lstrip().startswith("#"))
    code = code.split(chr(34) * 3)[0] + code.split(chr(34) * 3)[-1]
    assert "orb" not in code.lower()
    assert "tick_ohlc" in code


def test_the_threshold_lives_in_the_rules_file():
    from core import rules
    assert hasattr(rules, "BREAKOUT_MAX_OFF_HIGH_PCT")
    assert 0 < rules.BREAKOUT_MAX_OFF_HIGH_PCT < 1.0, (
        "a limit this loose stops telling a breakout from a pullback")
