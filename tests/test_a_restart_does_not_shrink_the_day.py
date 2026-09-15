"""---- A RESTART SHRANK THE DAY. 15 September 2026. ----

main.py restarted at 10:30. The ranker's day high/low came only from
ticks seen since then, so FSL (real low 250.15, high 291.95, trading
286-290) had a "day low" near 283 and was refused "faded to X% of its
day range -- the move is over" 1,050 times while at 88-96% of its real
range. RAYMOND 1,229 times. Both began the minute of the restart.
"""

from core import select
from dashboard.state import _day_range


def test_the_exchange_range_wins_over_a_post_restart_range():
    seen = {"high": 291.95, "low": 283.35}          # ticks since 10:30
    row = {"high": 291.95, "low": 250.15}           # Dhan's day quote
    assert _day_range(seen, row) == (291.95, 250.15)


def test_fsl_at_286_is_not_faded_on_the_real_range():
    high, low = _day_range({"high": 291.95, "low": 283.35},
                           {"high": 291.95, "low": 250.15})
    got = select.movement({"ltp": 286.85, "day_open": 250.25,
                           "day_high": high, "day_low": low,
                           "volume_ratio": 5.0})
    assert got["ok"], got["why"]
    # And it WAS refused on the shrunken range -- the bug, pinned.
    bad = select.movement({"ltp": 286.85, "day_open": 250.25,
                           "day_high": 291.95, "day_low": 283.35,
                           "volume_ratio": 5.0})
    assert not bad["ok"] and "faded" in bad["why"]


def test_ticks_wider_than_a_stale_quote_still_count():
    assert _day_range({"high": 300.0, "low": 240.0},
                      {"high": 292.0, "low": 250.0}) == (300.0, 240.0)


def test_no_quote_keeps_the_ticks():
    assert _day_range({"high": 10.0, "low": 9.0}, {}) == (10.0, 9.0)
