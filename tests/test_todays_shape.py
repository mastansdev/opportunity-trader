"""What is this stock doing TODAY, not over seven days.

    "stock displayed on dashboard is not showing its price action
     (uptrend , downtrend, sideways)"   -- operator, 30 August 2026

core/trend_structure.py has answered the SEVEN DAY question since it
was written, and it has been a chip on the board since 24 August. It
is a different question. A stock can be STRONG_UP on daily bars and
have gone sideways since 10:20 this morning, and the second fact is
the one that decides whether to hold it through lunch.

Same method, different clock: today's minutes are grouped into
fifteen-minute blocks and handed to the same higher-high / lower-low
test. So "climbing" means the same thing on both readings and they can
sit in one column without a translation. Nothing is averaged and no
two stocks ever meet.
"""

import pytest

from core import intraday_shape


def _series(prices, start_minutes=15):
    """prices, one per minute, from 09:15."""
    out = []
    for i, price in enumerate(prices):
        total = 9 * 60 + start_minutes + i
        out.append({"minute": "%02d:%02d" % (total // 60, total % 60),
                    "ltp": price})
    return out


def _climb(n=90, step=0.4, start=600.0):
    return _series([start + i * step for i in range(n)])


def _fall(n=90, step=0.4, start=600.0):
    return _series([start - i * step for i in range(n)])


def _flat(n=90, start=600.0):
    return _series([start + (0.05 if i % 2 else -0.05) for i in range(n)])


# --------------------------------------------------------------- blocks

def test_a_block_carries_the_highest_and_lowest_traded_in_it():
    """Not a mean of them. His rule, and the same one trend_structure
    follows on daily bars."""
    got = intraday_shape.blocks(_series([10.0, 12.0, 9.0, 11.0]))
    assert len(got) == 1
    assert got[0]["high"] == 12.0 and got[0]["low"] == 9.0
    assert got[0]["close"] == 11.0


def test_fifteen_minutes_to_a_block():
    got = intraday_shape.blocks(_series([600.0] * 45))
    assert len(got) == 3
    assert [b["at"] for b in got] == ["09:15", "09:30", "09:45"]


def test_a_minute_nothing_traded_in_is_absent_not_flat():
    rows = _series([600.0, 601.0, 602.0])
    rows[1]["ltp"] = None
    got = intraday_shape.blocks(rows)
    assert got[0]["high"] == 602.0 and got[0]["low"] == 600.0


# ------------------------------------------------------- saying nothing

def test_before_about_ten_it_says_nothing():
    """Three blocks is 45 minutes. Before that "sideways" would be a
    claim, not a reading."""
    assert intraday_shape.today(series=_climb(20)) is None


def test_an_empty_day_says_nothing():
    assert intraday_shape.today(series=[]) is None
    assert intraday_shape.today(series=None, symbol="NOSUCH") is None


# --------------------------------------------------------- the readings

def test_a_stock_climbing_all_morning_says_all_session():
    got = intraday_shape.today(series=_climb())
    assert got["structure"] in ("STRONG_UP", "UPTREND")
    assert got["text"] == "going up all session", got["text"]


def test_a_stock_falling_all_morning():
    got = intraday_shape.today(series=_fall())
    assert got["structure"] in ("STRONG_DOWN", "DOWNTREND")
    assert "down" in got["text"]


def test_flat_reads_sideways_and_names_when():
    got = intraday_shape.today(series=_flat())
    assert got["structure"] == "RANGE"
    assert got["text"].startswith("sideways since"), got["text"]


def test_a_climb_that_stalls_names_the_time_it_stalled():
    """The reading he actually needs: up, then nothing. The card must
    say WHEN, because that is what decides whether to stay in."""
    got = intraday_shape.today(series=_climb(60) + _flat(45, start=624.0))
    assert got is not None
    assert got["since"], "a stall with no time on it is not actionable"
    assert ":" in got["text"]


def test_the_words_are_the_ones_on_the_board():
    """Plain english, his instruction of 30 August. No structure name
    reaches the screen on its own."""
    for text in (intraday_shape.describe("STRONG_UP", None),
                 intraday_shape.describe("RANGE", "10:20"),
                 intraday_shape.describe("DOWNTREND", "11:05")):
        assert text
        assert "_" not in text
        assert text == text.lower()


def test_a_turn_is_called_a_turn():
    assert intraday_shape.describe("UPTREND", "14:05", broke="UP") == \
        "was going up, turned at 14:05"


# ----------------------------------------------- the same words as 7 days

def test_it_speaks_the_same_vocabulary_as_the_seven_day_read():
    """One column carries both. If these two ever named the same shape
    differently the column would be unreadable."""
    from core import trend_structure

    got = intraday_shape.today(series=_climb())
    assert got["structure"] in (trend_structure.STRONG_UP,
                                trend_structure.UPTREND,
                                trend_structure.RANGE,
                                trend_structure.DOWNTREND,
                                trend_structure.STRONG_DOWN)


# ------------------------------------- the bug this work found upstream

def test_an_unchanged_bar_is_not_a_down_bar():
    """core/trend_structure.leg() read "not a higher high AND not a
    higher low" as DOWN, which also catches the bar that is EXACTLY
    the one before it.

    Measured on data/daily_candles.db: 771 of 1,137,680 consecutive
    pairs are identical in both high and low -- 0.068%, rare enough to
    have gone unseen for weeks, and called DOWN in every one.

    It surfaced here because fifteen-minute blocks of a quiet stock
    repeat their high and low all morning, and the board would have
    printed "drifting down" for a share that had not moved.
    """
    from core.trend_structure import leg, INSIDE, DOWN_LEG

    same = {"high": 600.0, "low": 599.0, "close": 599.5}
    assert leg(same, dict(same)) == INSIDE

    lower = {"high": 599.0, "low": 598.0, "close": 598.5}
    assert leg(same, lower) == DOWN_LEG, "a real down bar still reads DOWN"


def test_a_stock_that_never_moves_is_not_called_a_faller():
    flat = intraday_shape.today(series=_series([600.0] * 90))
    assert flat is None or flat["structure"] == "RANGE", flat
