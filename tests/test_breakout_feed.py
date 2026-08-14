"""
Tests for core/breakout_feed.py -- the Fresh Breakouts panel.

Written alongside the module on 2026-07-28 after the operator's rule:
"today all error fixing each step by step ... errors are repeated" --
every fix gets a test that would have caught the original bug.

The bug this whole module exists for: on 2026-07-28 the engine fired
structural breakouts on TVSMOTOR, NTPCGREEN, KTKBANK and dozens more,
refused every one of them silently (SHORT_ONLY regime), and showed the
operator nothing. So the first test below is the one that matters --
a BLOCKED breakout must still appear.
"""

from datetime import datetime, timedelta

from core.breakout_feed import (
    BreakoutFeed, STATUS_ACTIVE, STATUS_FADED, LONG, SHORT,
    _age_label, _attempt_label,
)

T0 = datetime(2026, 7, 28, 10, 30, 0)


def _feed():
    return BreakoutFeed()


def test_a_blocked_breakout_still_shows_up():
    """THE point of the module. TVSMOTOR broke out, the regime filter
    refused it, and the operator never knew. It must appear anyway."""
    f = _feed()
    f.record("TVSMOTOR", LONG, 3991.0, 3985.0, 3940.0, tick_time=T0,
             taken=False, blocked_reason="SHORT_ONLY regime")
    rows = f.snapshot(now=T0)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "TVSMOTOR"
    assert rows[0]["taken"] is False
    assert rows[0]["blocked_reason"] == "SHORT_ONLY regime"
    assert rows[0]["actionable"] is True


def test_newest_breakout_comes_first():
    f = _feed()
    f.record("OLD", LONG, 100.0, 99.0, 95.0, tick_time=T0)
    f.record("NEW", LONG, 200.0, 199.0, 190.0,
             tick_time=T0 + timedelta(minutes=5))
    assert [r["symbol"] for r in f.snapshot(now=T0 + timedelta(minutes=6))] \
        == ["NEW", "OLD"]


def test_repeat_firing_is_one_event_not_forty():
    """The engine re-fires a breakout on every candle close while price
    stays beyond the range. That is ONE event -- forty rows for one
    stock would bury everything else."""
    f = _feed()
    for i in range(40):
        f.record("RVNL", LONG, 500.0, 499.0, 480.0,
                 tick_time=T0 + timedelta(seconds=i))
    rows = f.snapshot(now=T0)
    assert len(rows) == 1
    assert rows[0]["fired_count"] == 40


def test_age_counts_from_the_FIRST_break_not_the_latest():
    """If re-firing reset the clock, a stock that keeps triggering would
    look permanently fresh and always sit at the top."""
    f = _feed()
    f.record("RVNL", LONG, 500.0, 499.0, 480.0, tick_time=T0)
    f.record("RVNL", LONG, 502.0, 499.0, 480.0,
             tick_time=T0 + timedelta(minutes=9))
    rows = f.snapshot(now=T0 + timedelta(minutes=10))
    assert rows[0]["age_seconds"] == 600


def test_long_fades_when_price_falls_back_inside_the_range():
    f = _feed()
    f.record("KTKBANK", LONG, 213.7, 213.0, 208.0, tick_time=T0)
    assert f.snapshot(now=T0)[0]["status"] == STATUS_ACTIVE
    f.update_price("KTKBANK", 212.5)
    row = f.snapshot(now=T0)[0]
    assert row["status"] == STATUS_FADED
    assert row["actionable"] is False


def test_short_fades_when_price_rises_back_inside_the_range():
    f = _feed()
    f.record("VBL", SHORT, 426.0, 470.0, 427.0, tick_time=T0)
    f.update_price("VBL", 428.0)
    assert f.snapshot(now=T0)[0]["status"] == STATUS_FADED


def test_a_faded_breakout_is_kept_not_deleted():
    """A breakout that silently vanishes teaches nothing. One that
    visibly fails teaches how often they fail."""
    f = _feed()
    f.record("KTKBANK", LONG, 213.7, 213.0, 208.0, tick_time=T0)
    f.update_price("KTKBANK", 205.0)
    assert len(f.snapshot(now=T0)) == 1


def test_price_still_beyond_the_range_stays_active():
    f = _feed()
    f.record("NTPCGREEN", LONG, 118.4, 118.0, 114.0, tick_time=T0)
    f.update_price("NTPCGREEN", 121.0)
    assert f.snapshot(now=T0)[0]["status"] == STATUS_ACTIVE


def test_price_alone_never_revives_a_faded_row():
    """update_price() must not resurrect a failed breakout. Only a fresh
    SIGNAL from the engine counts as a new attempt."""
    f = _feed()
    f.record("KTKBANK", LONG, 213.7, 213.0, 208.0, tick_time=T0)
    f.update_price("KTKBANK", 210.0)
    f.update_price("KTKBANK", 215.0)
    assert f.snapshot(now=T0)[0]["status"] == STATUS_FADED


def test_breaking_out_again_after_a_fade_is_the_SECOND_attempt():
    """Operator, 2026-07-28: "some breakouts at 1st, 2nd & 3rd attempt
    right?" -- yes, and the panel has to be able to tell them apart."""
    f = _feed()
    f.record("KTKBANK", LONG, 213.7, 213.0, 208.0, tick_time=T0)
    assert f.snapshot(now=T0)[0]["attempt"] == 1
    f.update_price("KTKBANK", 210.0)
    f.record("KTKBANK", LONG, 214.2, 213.0, 208.0,
             tick_time=T0 + timedelta(minutes=20))
    row = f.snapshot(now=T0 + timedelta(minutes=20))[0]
    assert row["attempt"] == 2
    assert row["attempt_label"] == "2nd try"
    assert row["status"] == STATUS_ACTIVE


def test_a_third_attempt_counts_as_three():
    f = _feed()
    for i, price in enumerate((213.7, 214.2, 215.0)):
        f.record("KTKBANK", LONG, price, 213.0, 208.0,
                 tick_time=T0 + timedelta(minutes=10 * i))
        f.update_price("KTKBANK", 210.0)
    assert f.snapshot(now=T0)[0]["attempt"] == 3
    assert f.snapshot(now=T0)[0]["attempt_label"] == "3rd try"


def test_the_age_clock_restarts_on_a_new_attempt_but_first_ever_is_kept():
    """The panel needs BOTH: how fresh THIS attempt is, and when the
    stock first started testing the level."""
    f = _feed()
    f.record("KTKBANK", LONG, 213.7, 213.0, 208.0, tick_time=T0)
    f.update_price("KTKBANK", 210.0)
    f.record("KTKBANK", LONG, 214.2, 213.0, 208.0,
             tick_time=T0 + timedelta(minutes=30))
    row = f.snapshot(now=T0 + timedelta(minutes=31))[0]
    assert row["age_seconds"] == 60
    assert row["first_ever"] == "10:30:00"
    assert row["first_seen"] == "11:00:00"


def test_a_new_attempt_clears_the_previous_refusal():
    """A stale "refused" tag on a fresh attempt would be a lie."""
    f = _feed()
    f.record("TVSMOTOR", LONG, 3991.0, 3985.0, 3940.0, tick_time=T0)
    f.note_block("TVSMOTOR", LONG, "market regime is SHORT_ONLY")
    f.update_price("TVSMOTOR", 3980.0)
    f.record("TVSMOTOR", LONG, 3995.0, 3985.0, 3940.0,
             tick_time=T0 + timedelta(minutes=15))
    row = f.snapshot(now=T0)[0]
    assert row["blocked_reason"] is None
    assert row["attempt"] == 2


def test_attempt_labels_read_naturally():
    assert _attempt_label(1) == "1st try"
    assert _attempt_label(2) == "2nd try"
    assert _attempt_label(3) == "3rd try"
    assert _attempt_label(4) == "4th try"


def test_long_and_short_on_one_symbol_are_separate_rows():
    f = _feed()
    f.record("ITC", LONG, 400.0, 399.0, 390.0, tick_time=T0)
    f.record("ITC", SHORT, 389.0, 399.0, 390.0, tick_time=T0)
    assert len(f.snapshot(now=T0)) == 2


def test_taken_breakouts_are_not_actionable():
    """No BUY button on something already in the book -- the engine
    refuses pyramiding anyway, so offering it is a lie."""
    f = _feed()
    f.record("LODHA", LONG, 1287.0, 1280.0, 1250.0, tick_time=T0, taken=True)
    assert f.snapshot(now=T0)[0]["actionable"] is False


def test_volume_multiple_is_carried_through():
    """The 7.5-year study says 6x volume had NEGATIVE edge while quiet
    moves gained. The operator has to be able to SEE which this is."""
    f = _feed()
    f.record("HEG", LONG, 500.0, 499.0, 480.0, tick_time=T0, volume_mult=0.8)
    assert f.snapshot(now=T0)[0]["volume_mult"] == 0.8


def test_the_feed_is_capped_and_drops_the_oldest():
    f = BreakoutFeed(max_rows=5)
    for i in range(12):
        f.record(f"SYM{i}", LONG, 100.0, 99.0, 95.0,
                 tick_time=T0 + timedelta(seconds=i))
    rows = f.snapshot(now=T0)
    assert len(rows) == 5
    assert rows[0]["symbol"] == "SYM11"
    assert "SYM0" not in [r["symbol"] for r in rows]


def test_nothing_in_here_can_raise_into_the_tick_path():
    """A bookkeeping panel must never be able to break a trade."""
    f = _feed()
    f.record("BAD", LONG, None, None, None, tick_time=T0)
    f.update_price("BAD", None)
    f.snapshot(now=T0)


def test_update_price_on_an_unknown_symbol_is_harmless():
    f = _feed()
    f.update_price("NEVER_SEEN", 100.0)
    assert f.snapshot(now=T0) == []


def test_age_labels_read_naturally():
    assert _age_label(0) == "0s ago"
    assert _age_label(18) == "18s ago"
    assert _age_label(59) == "59s ago"
    assert _age_label(60) == "1m ago"
    assert _age_label(599) == "9m ago"
    assert _age_label(3600) == "1h 0m ago"
    assert _age_label(3700) == "1h 1m ago"
    assert _age_label(-5) == "0s ago"


def test_empty_feed_is_an_empty_list_not_a_crash():
    assert _feed().snapshot(now=T0) == []
    assert _feed().count() == 0


# ---------------------------------------------------------------
# TESTS OF THE LEVEL (not failed breakouts). Operator's RADICO chart,
# 2026-07-28: ORB high 4,182, pressed against for HOURS without ever
# closing through, then broke late and ran to 4,335.
# ---------------------------------------------------------------

def test_touching_the_orb_high_counts_as_one_test():
    f = _feed()
    f.note_touch("RADICO", 4180.0, 4182.0, 4118.3)
    assert f.test_count("RADICO", LONG) == 1


def test_hovering_at_the_level_is_still_ONE_test_not_hundreds():
    """Without hysteresis a stock sitting on its ORB high would clock up
    a test on every tick -- 9,000 a minute across the universe."""
    f = _feed()
    for _ in range(500):
        f.note_touch("RADICO", 4180.0, 4182.0, 4118.3)
    assert f.test_count("RADICO", LONG) == 1


def test_pulling_away_and_returning_is_a_SECOND_test():
    f = _feed()
    f.note_touch("RADICO", 4180.0, 4182.0, 4118.3)
    f.note_touch("RADICO", 4140.0, 4182.0, 4118.3)     # cleared away
    f.note_touch("RADICO", 4181.0, 4182.0, 4118.3)     # back at the level
    assert f.test_count("RADICO", LONG) == 2


def test_a_small_wobble_does_NOT_count_as_a_new_test():
    """Price must clear TEST_RESET_PCT away, not just dip a rupee."""
    f = _feed()
    f.note_touch("RADICO", 4180.0, 4182.0, 4118.3)
    f.note_touch("RADICO", 4176.0, 4182.0, 4118.3)     # only 0.15% off
    f.note_touch("RADICO", 4181.0, 4182.0, 4118.3)
    assert f.test_count("RADICO", LONG) == 1


def test_the_low_side_is_tested_independently():
    f = _feed()
    f.note_touch("RADICO", 4119.0, 4182.0, 4118.3)
    assert f.test_count("RADICO", SHORT) == 1
    assert f.test_count("RADICO", LONG) == 0


def test_test_count_reaches_the_panel_row():
    f = _feed()
    f.note_touch("RADICO", 4180.0, 4182.0, 4118.3)
    f.note_touch("RADICO", 4140.0, 4182.0, 4118.3)
    f.note_touch("RADICO", 4181.0, 4182.0, 4118.3)
    f.record("RADICO", LONG, 4190.0, 4182.0, 4118.3, tick_time=T0)
    assert f.snapshot(now=T0)[0]["tests"] == 2


def test_note_touch_with_no_range_yet_is_harmless():
    f = _feed()
    f.note_touch("RADICO", 4180.0, None, None)
    f.note_touch("RADICO", None, 4182.0, 4118.3)
    assert f.test_count("RADICO", LONG) == 0
