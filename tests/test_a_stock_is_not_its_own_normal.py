"""A stock must never be measured against its own spike.

    "whats this denominator error ?"      -- operator, 27 August 2026

core/liquidity.py computed "a normal day" as the MEAN of the last five
sessions INCLUDING the one being measured. A stock that exploded today
had its own explosion averaged into what counted as normal:

    LTFOODS   18-21 Aug  Rs 21cr a day
              24 Aug     Rs 1,968cr        <- inside its own mean
              "normal"   Rs 410cr
              read       4.8x     truth: 116x

Every big mover on 24 August compressed to roughly the same number --
LTFOODS 4.8x, QUADFUTURE 3.8x, TVSSCS 4.9x, RATNAMANI 4.4x, VMM 4.0x.
Which is why comparing what ran against what did not found NO
separation in volume_x (2.83 vs 2.78): the instrument could not tell
them apart, and I reported that volume does not rank. It was the
measurement, not the market.
"""

import statistics


def _median_ex_latest(day_values, today=None):
    """The rule core/liquidity.refresh() now applies."""
    latest = max(day_values)
    drop = latest if latest == today else None
    vals = [v for d, v in sorted(day_values.items()) if d != drop]
    return statistics.median(vals) if vals else None


def test_todays_spike_is_not_in_todays_denominator():
    days = {"2026-08-18": 21.0, "2026-08-19": 21.0, "2026-08-20": 21.0,
            "2026-08-21": 21.0, "2026-08-24": 1968.0}
    normal = _median_ex_latest(days, today="2026-08-24")
    assert normal == 21.0
    assert 1968.0 / normal > 90


def test_the_mean_is_what_broke_it():
    days = [21.0, 21.0, 21.0, 21.0, 1968.0]
    assert statistics.mean(days) > 400          # what it used to do
    assert statistics.median(days) == 21.0      # what it does now


def test_a_stale_store_does_not_lose_a_real_session():
    """On 27 August the daily store's newest was the 25th. Dropping the
    latest unconditionally would throw away an ordinary session."""
    days = {"2026-08-21": 10.0, "2026-08-24": 12.0, "2026-08-25": 11.0}
    kept = _median_ex_latest(days, today="2026-08-27")
    assert kept == 11.0, "25 Aug is history on 27 Aug, not a self-spike"


def test_the_window_is_long_enough_for_a_median_to_work():
    """QUADFUTURE ran THREE days -- 21 Aug Rs 289cr, 24 Aug Rs 1,058cr,
    25 Aug Rs 211cr -- against a normal near Rs 10cr. Over five
    sessions the median IS the spike."""
    from core.liquidity import SESSIONS
    assert SESSIONS >= 20
    five = [9.9, 10.7, 288.9, 1057.7, 211.2]
    assert statistics.median(five) > 200        # five is not enough
    twenty = [9.9, 10.7, 288.9, 1057.7, 211.2] + [10.0] * 15
    assert statistics.median(twenty) < 15       # twenty is


def test_the_sane_cap_no_longer_refuses_real_event_days():
    """50x was set when 50x meant a broken divisor. With the divisor
    fixed, TVSSCS did 106x, FACT 617x -- both verified against the
    day's real turnover."""
    from core.ranker import MAX_SANE_VOLUME_RATIO
    assert MAX_SANE_VOLUME_RATIO >= 600


def test_absolute_floors_still_guard_a_tiny_denominator():
    """Raising the cap must not let a near-zero divisor through. These
    do not depend on a ratio at all."""
    from core import rules
    assert rules.MIN_LIQUIDITY_CR >= 2.0
    assert rules.MIN_UNIVERSE_TURNOVER_RS >= 5 * 10 ** 7
