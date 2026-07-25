import time as _time
from datetime import datetime, timedelta

from core.market_data import MarketData


def _t(hh, mm, ss=0):
    return datetime(2026, 7, 22, hh, mm, ss)


def _past_warmup(md):
    """Push the instance's start time far enough back that the
    warm-up grace period is over, so systemic-stale console logic is
    active (tests otherwise run entirely inside the 60s grace)."""
    md._started_at = _time.monotonic() - 10_000
    return md


def test_premarket_tick_is_rejected_and_does_not_reach_callbacks():
    md = MarketData()
    seen = []
    md.on_new_tick(lambda s, p, t, v=None: seen.append((s, p, t)))

    accepted = md.on_tick("TCS", 100.0, _t(9, 10, 0), now=_t(9, 10, 0))

    assert accepted is False
    assert seen == []
    assert md.get_latest_price("TCS") is None


def test_live_tick_is_accepted_and_updates_latest_price():
    md = MarketData()
    seen = []
    md.on_new_tick(lambda s, p, t, v=None: seen.append((s, p, t)))

    accepted = md.on_tick("TCS", 100.0, _t(9, 20, 0), now=_t(9, 20, 0))

    assert accepted is True
    assert len(seen) == 1
    assert md.get_latest_price("TCS") == 100.0


def test_stale_tick_is_still_accepted_but_does_not_silently_hide_staleness():
    """
    A stale tick must still be processed (the bot can't
    just stall), but it must never be indistinguishable
    from a fresh one -- checked here via the return value
    plus the fact that get_latest_price still updates.
    """
    md = MarketData()
    old_tick_time = _t(9, 20, 0)
    now = old_tick_time + timedelta(seconds=30)

    accepted = md.on_tick("TCS", 100.0, old_tick_time, now=now)

    assert accepted is True
    assert md.get_latest_price("TCS") == 100.0


def test_tick_count_increments_only_on_accepted_ticks():
    md = MarketData()

    md.on_tick("TCS", 100.0, _t(9, 10, 0), now=_t(9, 10, 0))  # pre-market
    md.on_tick("TCS", 100.0, _t(9, 20, 0), now=_t(9, 20, 0))  # accepted
    md.on_tick("INFY", 200.0, _t(9, 21, 0), now=_t(9, 21, 0))  # accepted

    assert md.get_tick_count() == 2


def test_repeated_stale_ticks_for_same_symbol_warn_only_once_until_recovery():
    """
    At 750 symbols, warning on every repeat of the same
    stale symbol is exactly what floods a terminal. This
    proves it's edge-triggered: one warning per stale
    episode, not one per tick.
    """
    md = MarketData()
    stale_time = _t(9, 20, 0)
    now = stale_time + timedelta(seconds=30)

    md.on_tick("TCS", 100.0, stale_time, now=now)
    md.on_tick("TCS", 100.5, stale_time, now=now)
    md.on_tick("TCS", 101.0, stale_time, now=now)

    assert md.get_stale_warning_count() == 1

    fresh_time = now
    md.on_tick("TCS", 102.0, fresh_time, now=fresh_time)  # recovers

    md.on_tick("TCS", 100.0, stale_time, now=now)  # stale again

    assert md.get_stale_warning_count() == 2


def test_day_open_is_the_first_accepted_tick_and_never_changes():
    md = MarketData()
    md.on_tick("TCS", 100.0, _t(9, 20, 0), now=_t(9, 20, 0))
    md.on_tick("TCS", 105.0, _t(9, 25, 0), now=_t(9, 25, 0))
    md.on_tick("TCS", 95.0, _t(9, 40, 0), now=_t(9, 40, 0))

    assert md.get_day_open("TCS") == 100.0
    assert md.get_latest_price("TCS") == 95.0


def test_day_open_unknown_for_a_symbol_with_no_ticks_yet():
    md = MarketData()
    assert md.get_day_open("NOPE") is None


# ==========================================================
# ORB-window feed staleness, 2026-07-24 -- SONACOMS incident. A
# symbol that goes stale WHILE its own [09:15, 09:30) ORB window is
# still open can't be trusted to have a complete range -- see this
# module's own docstring on is_orb_window_unreliable() for the full
# writeup (a ~30s gap right at market open meant the true intraday
# high never reached orb_engine.update(), understating the range by
# Rs 3.80 and producing a false breakout signal).
# ==========================================================

def test_stale_tick_inside_the_orb_window_flags_the_symbol_unreliable():
    md = MarketData()
    stale_time = _t(9, 20, 0)  # inside [09:15, 09:30)
    now = stale_time + timedelta(seconds=30)

    md.on_tick("TCS", 100.0, stale_time, now=now)

    assert md.is_orb_window_unreliable("TCS") is True
    assert md.get_orb_window_unreliable_count() == 1


def test_stale_tick_after_the_orb_window_does_not_flag_it():
    """The range is already frozen by 09:30 -- a late/stale tick
    after the window closes can't corrupt a range that no longer
    moves, so there's nothing to flag."""
    md = MarketData()
    stale_time = _t(9, 35, 0)  # after ORB_WINDOW_END
    now = stale_time + timedelta(seconds=30)

    md.on_tick("TCS", 100.0, stale_time, now=now)

    assert md.is_orb_window_unreliable("TCS") is False
    assert md.get_orb_window_unreliable_count() == 0


def test_orb_window_unreliable_flag_persists_after_the_symbol_recovers():
    """Recovering from staleness doesn't un-happen the gap that
    already occurred during the window -- the flag must never clear
    once set, unlike the ordinary _stale_symbols tracking."""
    md = MarketData()
    stale_time = _t(9, 20, 0)
    now = stale_time + timedelta(seconds=30)
    md.on_tick("TCS", 100.0, stale_time, now=now)
    assert md.is_orb_window_unreliable("TCS") is True

    # A fresh, non-stale tick arrives -- ordinary staleness clears...
    fresh_time = now
    md.on_tick("TCS", 101.0, fresh_time, now=fresh_time)

    # ...but the ORB-window-unreliable flag must still be set.
    assert md.is_orb_window_unreliable("TCS") is True


def test_a_symbol_that_never_goes_stale_is_never_flagged_unreliable():
    md = MarketData()
    md.on_tick("TCS", 100.0, _t(9, 20, 0), now=_t(9, 20, 0))
    md.on_tick("TCS", 101.0, _t(9, 25, 0), now=_t(9, 25, 0))

    assert md.is_orb_window_unreliable("TCS") is False
    assert md.get_orb_window_unreliable_count() == 0


# ==========================================================
# #2, 2026-07-24 (evening) -- console-noise controls: warm-up grace
# + systemic (fraction-based) stale alarm instead of per-symbol spam.
# ==========================================================

def test_systemic_stale_alarm_fires_when_a_large_fraction_is_stale_at_once():
    md = _past_warmup(MarketData())
    stale = _t(9, 40, 0)
    now = stale + timedelta(seconds=30)
    # Two symbols seen, both stale -> 2/2 = 100% >= 50% threshold.
    md.on_tick("AAA", 10.0, stale, now=now)
    md.on_tick("BBB", 20.0, stale, now=now)

    assert md._systemic_stale_active is True


def test_systemic_stale_alarm_clears_when_the_feed_recovers():
    md = _past_warmup(MarketData())
    stale = _t(9, 40, 0)
    now = stale + timedelta(seconds=30)
    md.on_tick("AAA", 10.0, stale, now=now)
    md.on_tick("BBB", 20.0, stale, now=now)
    assert md._systemic_stale_active is True

    # Both recover with fresh ticks -> 0% stale -> alarm clears.
    fresh = now
    md.on_tick("AAA", 10.5, fresh, now=fresh)
    md.on_tick("BBB", 20.5, fresh, now=fresh)

    assert md._systemic_stale_active is False


def test_a_few_quiet_stocks_do_not_trip_the_systemic_alarm():
    """The afternoon-lull case: a minority stale must stay quiet."""
    md = _past_warmup(MarketData())
    fresh = _t(9, 40, 0)
    # 8 symbols trading fine...
    for i in range(8):
        md.on_tick(f"OK{i}", 100.0, fresh, now=fresh)
    # ...2 go stale -> 2/10 = 20% < 50% threshold.
    stale = _t(9, 40, 0)
    now = stale + timedelta(seconds=30)
    md.on_tick("SLOW1", 50.0, stale, now=now)
    md.on_tick("SLOW2", 60.0, stale, now=now)

    assert md._systemic_stale_active is False


def test_warm_up_grace_keeps_the_console_quiet_during_the_connect_burst():
    """A fresh instance is inside the warm-up grace, so even a
    near-total stale burst (the 09:15/restart connect flood) does NOT
    raise the console alarm -- it's tracked silently and self-clears."""
    md = MarketData()  # NOT past warm-up
    stale = _t(9, 15, 30)
    now = stale + timedelta(seconds=6)
    md.on_tick("AAA", 10.0, stale, now=now)
    md.on_tick("BBB", 20.0, stale, now=now)

    # Flag reflects the reality (100% stale) but no console alarm was
    # raised during warm-up -- and it won't emit a spurious "cleared"
    # line either, since it was never announced.
    assert md._systemic_stale_active is True
