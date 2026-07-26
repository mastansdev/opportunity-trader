"""
Tests for the daily-candle history and the 7-day structure reader.

The operator's description, which these tests encode literally:

    "some stocks make higher highs on day to day basis. once that
     formation stopped and forms higher low then lower low formation
     causes the reversal / range boundness in stocks."
"""

import pytest

from core.daily_store import DailyStore, bars_from_bhavcopy
from core.trend_structure import (
    DOWNTREND, DOWN_LEG, INSIDE, OUTSIDE, RANGE, STRONG_DOWN, STRONG_UP,
    UNKNOWN, UPTREND, UP_LEG, analyse, describe, leg,
)


def bar(high, low, close=None):
    return dict(high=high, low=low, close=close if close is not None else high)


def staircase_up(n=8, step=10):
    """The PARAS / DATAPATTERNS shape: every day a higher high AND a
    higher low."""
    return [bar(100 + i * step, 90 + i * step, 98 + i * step)
            for i in range(n)]


def staircase_down(n=8, step=10):
    return [bar(200 - i * step, 190 - i * step, 192 - i * step)
            for i in range(n)]


# ---------------------------------------------------------------
# leg() -- one day against the day before
# ---------------------------------------------------------------

def test_leg_labels():
    assert leg(bar(100, 90), bar(110, 95)) == UP_LEG       # HH + HL
    assert leg(bar(100, 90), bar(95, 85)) == DOWN_LEG      # LH + LL
    assert leg(bar(100, 90), bar(110, 85)) == OUTSIDE      # HH + LL
    assert leg(bar(100, 90), bar(95, 95)) == INSIDE        # LH + HL


# ---------------------------------------------------------------
# analyse() -- the shape over a window
# ---------------------------------------------------------------

def test_needs_at_least_three_bars():
    result = analyse([bar(100, 90), bar(110, 95)])
    assert result["structure"] == UNKNOWN
    assert "not enough" in describe(result)


def test_a_clean_staircase_up_is_STRONG_UP():
    result = analyse(staircase_up())
    assert result["structure"] == STRONG_UP
    assert result["hh_streak"] == 7
    assert result["broke_structure"] is None
    assert set(result["legs"]) == {UP_LEG}
    assert "higher highs in a row" in describe(result)


def test_a_clean_staircase_down_is_STRONG_DOWN():
    result = analyse(staircase_down())
    assert result["structure"] == STRONG_DOWN
    assert result["ll_streak"] == 7


def test_the_operators_case_uptrend_that_stops_and_breaks_the_prior_low():
    """
    Five days stepping up, then a day that FAILS to make a higher high
    AND takes out the previous day's low. That is the character change
    -- the bot must stop calling this an uptrend.
    """
    bars = staircase_up(n=6)                       # highs 100..150
    bars.append(bar(148, 128, 130))                # lower high, lower low

    result = analyse(bars)
    assert result["broke_structure"] == "UP"
    assert result["structure"] == RANGE            # NOT UPTREND any more
    assert result["hh_streak"] == 0
    assert "JUST BROKE" in describe(result)


def test_a_single_pause_is_NOT_a_break():
    """One inside day is a pause, not a reversal. Only a failed high
    PLUS a broken low counts -- otherwise every consolidation day would
    fire a false alarm."""
    bars = staircase_up(n=6)                       # highs 100..150, lows 90..140
    bars.append(bar(148, 142, 145))                # lower high, but HIGHER low

    result = analyse(bars)
    assert result["broke_structure"] is None
    assert result["structure"] in (STRONG_UP, UPTREND)


def test_downtrend_breaking_upward_is_flagged_too():
    bars = staircase_down(n=6)
    bars.append(bar(160, 152, 158))                # higher high, higher low

    result = analyse(bars)
    assert result["broke_structure"] == "DOWN"
    assert result["structure"] == RANGE


def test_choppy_bars_are_RANGE():
    bars = [bar(100, 90), bar(105, 85), bar(98, 88),
            bar(103, 87), bar(99, 91)]
    assert analyse(bars)["structure"] == RANGE


def test_position_within_the_window_is_reported():
    bars = staircase_up(n=8)                       # high 170, low 90
    result = analyse(bars)
    assert result["days_since_high"] == 0          # made the high today
    assert result["pct_from_high"] == pytest.approx(
        (168 - 170) / 170 * 100, abs=0.01)
    assert result["pct_from_low"] > 0


def test_days_since_high_counts_back():
    bars = staircase_up(n=6)
    bars += [bar(140, 130, 135), bar(138, 128, 132)]
    assert analyse(bars)["days_since_high"] == 2


def test_bars_missing_prices_are_ignored_not_fatal():
    bars = staircase_up(n=5)
    bars.insert(2, dict(high=None, low=None, close=None))
    result = analyse(bars)
    assert result["structure"] != UNKNOWN
    assert result["bars"] == 5


def test_analyse_handles_none_and_empty():
    assert analyse(None)["structure"] == UNKNOWN
    assert analyse([])["structure"] == UNKNOWN


# ---------------------------------------------------------------
# bars_from_bhavcopy()
# ---------------------------------------------------------------

RAW = {
    "TckrSymb": "RELIANCE", "SctySrs": "EQ", "OpnPric": "1265.00",
    "HghPric": "1283.40", "LwPric": "1249.80", "ClsPric": "1278.00",
    "PrvsClsgPric": "1272.20", "TtlTradgVol": "9817000",
    "TtlTrfVal": "12509975780.10",
}


def test_bhavcopy_row_becomes_a_daily_bar():
    bars = bars_from_bhavcopy([RAW], "2026-07-24")
    assert len(bars) == 1
    b = bars[0]
    assert b["symbol"] == "RELIANCE"
    assert b["date"] == "2026-07-24"
    assert (b["open"], b["high"], b["low"], b["close"]) == (
        1265.0, 1283.4, 1249.8, 1278.0)
    assert b["prev_close"] == 1272.20
    assert b["turnover"] == pytest.approx(12509975780.10)


def test_non_eq_series_is_skipped():
    """A T2T bar is not a candle we ever want a trend from -- we cannot
    trade it and it prices under different rules."""
    rows = [dict(RAW, TckrSymb="STLTECH", SctySrs="BE")]
    assert bars_from_bhavcopy(rows, "2026-07-24") == []
    assert len(bars_from_bhavcopy(rows, "2026-07-24",
                                  tradeable_only=False)) == 1


def test_rows_without_a_usable_close_are_skipped():
    rows = [dict(RAW, ClsPric=""), dict(RAW, TckrSymb="OK")]
    assert [b["symbol"] for b in bars_from_bhavcopy(rows, "d")] == ["OK"]


def test_turnover_is_derived_when_absent():
    row = dict(RAW)
    row.pop("TtlTrfVal")
    assert bars_from_bhavcopy([row], "d")[0]["turnover"] == pytest.approx(
        1278.0 * 9817000)


# ---------------------------------------------------------------
# DailyStore
# ---------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return DailyStore(url=f"sqlite:///{tmp_path}/daily.db")


def test_store_roundtrip_oldest_first(store):
    store.upsert_many([
        dict(date="2026-07-24", symbol="X", high=110, low=100, close=105),
        dict(date="2026-07-22", symbol="X", high=90, low=80, close=85),
        dict(date="2026-07-23", symbol="X", high=100, low=90, close=95),
    ])
    got = store.history("X", days=7)
    assert [b["date"] for b in got] == [
        "2026-07-22", "2026-07-23", "2026-07-24"]


def test_duplicate_dates_are_ignored_not_duplicated(store):
    row = dict(date="2026-07-24", symbol="X", high=110, low=100, close=105)
    assert store.upsert_many([row]) == 1
    assert store.upsert_many([row]) == 0
    assert len(store.history("X")) == 1


def test_upto_excludes_the_future(store):
    """Without this an honest backtest is impossible -- replaying
    2026-07-24 must not be able to see 07-25."""
    store.upsert_many([
        dict(date="2026-07-24", symbol="X", high=110, low=100, close=105),
        dict(date="2026-07-25", symbol="X", high=120, low=110, close=115),
    ])
    assert len(store.history("X", upto="2026-07-24")) == 1
    assert len(store.history("X")) == 2


def test_history_respects_the_day_limit(store):
    store.upsert_many([
        dict(date=f"2026-07-{d:02d}", symbol="X", high=100 + d,
             low=90 + d, close=95 + d)
        for d in range(1, 20)
    ])
    assert len(store.history("X", days=7)) == 7
    # and it's the LAST 7, not the first
    assert store.history("X", days=7)[-1]["date"] == "2026-07-19"


def test_stats(store):
    store.upsert_many([
        dict(date="2026-07-23", symbol="A", high=1, low=1, close=1),
        dict(date="2026-07-24", symbol="A", high=1, low=1, close=1),
        dict(date="2026-07-24", symbol="B", high=1, low=1, close=1),
    ])
    s = store.stats()
    assert s == dict(bars=3, symbols=2, days=2, first="2026-07-23",
                     last="2026-07-24")


def test_end_to_end_store_then_analyse(store):
    """The real path: bhavcopy rows in, structure label out."""
    for i in range(8):
        rows = [dict(RAW, TckrSymb="PARAS",
                     OpnPric=str(100 + i * 5), HghPric=str(105 + i * 5),
                     LwPric=str(95 + i * 5), ClsPric=str(104 + i * 5))]
        store.upsert_many(bars_from_bhavcopy(rows, f"2026-07-{10 + i:02d}"))

    result = analyse(store.history("PARAS", days=8))
    assert result["structure"] == STRONG_UP
    assert result["hh_streak"] == 7
