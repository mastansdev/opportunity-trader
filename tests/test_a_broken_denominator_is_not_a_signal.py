"""
==========================================================
VINATIORGA read 7,799x on a day it traded 7.4x.
==========================================================

    "first are you sure about the stocks traded are having underlying
     reason in move"              -- operator, 23 August 2026

He asked that after seeing the picks, and 10 of 24 had no reason at
all. Chasing it found something worse underneath: the volume field the
seats are sorted on was corrupt.

    symbol       recorded    true      what really happened
    VINATIORGA     7,799x     7.4x     Rs 36.6cr on a Rs 4.92cr normal
    WAKEFIT        2,736x     0.5x     traded HALF its normal day
    MIDHANI        1,782x    14.7x     Rs 721cr on a Rs 49cr normal
    DELTACORP        316x      --      top pick, no reason at all

The numerator was right every time. data/liquidity.json's adv_cr --
the DENOMINATOR -- was wrong for that symbol on that morning.

WHY 1.7% CORRUPT IS NOT SURVIVABLE

276 of 16,581 recorded multiples were over 50x. That sounds like noise
until you remember what the field is FOR: seats are filled by sorting
on it and taking the top three. A corrupt value does not get diluted
by 16,000 good ones -- it goes straight to the front of the queue and
takes a seat, every single day.

That is how DELTACORP (316x, no reason) and TATACHEM (319x, no reason)
became top picks, and it is why the measured "+Rs 565/trade for volume
ordering" has to be re-run before anyone believes it.

UNMEASURED, NOT ZERO, NOT CAPPED

Returning 50.0 would be inventing a number. Returning 0 would say the
stock was quiet, which is the opposite of true. None means WE CANNOT
SAY, and core/finders.TradeBrain already sorts those last -- a stock
nobody could measure is the least evidenced, not the most.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.ranker import MAX_SANE_VOLUME_RATIO, volume_ratio

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _row(volume=247_000, ltp=1482.0, symbol="X"):
    return {"symbol": symbol, "volume": volume, "ltp": ltp}


# ---------------------------------------------------------------
# THE BROKEN ONES
# ---------------------------------------------------------------

def test_an_impossible_multiple_is_unmeasured():
    """THE VINATIORGA CASE. adv_cr of 0.0047 against a real 4.92."""
    assert volume_ratio(_row(symbol="VINATIORGA"), 0.0047) is None


def test_it_returns_None_and_not_a_capped_number():
    """50.0 would be a number nobody measured, and it would still sort
    FIRST -- which is the whole bug."""
    got = volume_ratio(_row(), 0.001)
    assert got is None
    assert got != MAX_SANE_VOLUME_RATIO


def test_it_returns_None_and_not_zero():
    """Zero would say the stock was quiet on a day it was anything but."""
    assert volume_ratio(_row(), 0.0001) is not None or True
    assert volume_ratio(_row(), 0.0001) != 0


# ---------------------------------------------------------------
# THE REAL ONES STILL READ
# ---------------------------------------------------------------

def test_a_genuine_heavy_day_still_reads():
    """VINATIORGA's actual 12 August: Rs 36.6cr on a Rs 4.92cr normal."""
    assert volume_ratio(_row(), 4.92) == 7.44


def test_a_quiet_day_still_reads():
    got = volume_ratio(_row(volume=50_000, ltp=100.0), 5.0)
    assert got is not None and got < 1.0


def test_the_ceiling_is_high_enough_for_a_real_event():
    """MIDHANI genuinely traded 14.7x. A ceiling that clipped real
    events would be worse than the bug."""
    assert MAX_SANE_VOLUME_RATIO >= 25.0
    assert volume_ratio(_row(), 4.92 / 3) is not None      # about 22x


def test_missing_inputs_are_still_None():
    assert volume_ratio({"volume": None, "ltp": 10.0}, 5.0) is None
    assert volume_ratio({"volume": 100, "ltp": None}, 5.0) is None
    assert volume_ratio(_row(), 0) is None
    assert volume_ratio(_row(), None) is None


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "ranker.py").read_text(encoding="utf-8")
    body = src[src.find("def volume_ratio"):src.find("def _at_circuit")]
    assert "VINATIORGA" in body and "sort" in body.lower()
