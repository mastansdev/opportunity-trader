"""liveness() asked for VWAP for weeks. Nothing ever supplied it.

    "do VWAP then remaining"          -- operator, 27 August 2026

core/ranker.py's liveness() decides alive-vs-fading from three
readings, one of them:

    "Below VWAP on a long means the average buyer today is under
     water. That is not a stock to be joining."

It reads row["vwap"]. No code anywhere wrote that key -- it appeared
ZERO times in the live snapshot -- so the guard `if vwap and ltp:`
skipped silently and that signal never fired once.

Same class as position.get("stop") printing None for three protected
positions, and dashboard_state.snapshot() failing 487 times: a field
read off a shape that does not carry it.
"""

import pytest

from core.candle_engine import CandleEngine


def _engine(candles):
    engine = CandleEngine.__new__(CandleEngine)
    engine._closed_candles = {"X": candles}
    return engine


def test_vwap_is_volume_weighted_not_a_plain_average():
    """The whole point of the V in VWAP."""
    engine = _engine([
        {"high": 102, "low": 98, "close": 100, "volume": 1000},
        {"high": 112, "low": 108, "close": 110, "volume": 3000},
    ])
    got = engine.vwap("X")
    assert got == pytest.approx((100 * 1000 + 110 * 3000) / 4000)
    assert got != pytest.approx(105.0), "that is the unweighted mean"


def test_the_typical_price_is_high_low_close_over_three():
    engine = _engine([{"high": 110, "low": 100, "close": 105,
                       "volume": 500}])
    assert engine.vwap("X") == pytest.approx((110 + 100 + 105) / 3)


def test_no_volume_is_None_not_a_plain_average():
    """A session with no volume has no volume-weighted price. Returning
    the mean would invent one."""
    assert _engine([{"high": 102, "low": 98, "close": 100,
                     "volume": 0}]).vwap("X") is None
    assert _engine([]).vwap("X") is None
    assert _engine([{"high": 1, "low": 1, "close": 1}]).vwap("X") is None


def test_an_unknown_symbol_is_silent():
    assert _engine([]).vwap("NOSUCH") is None


def test_a_candle_missing_a_price_is_skipped_not_guessed():
    engine = _engine([
        {"high": None, "low": 98, "close": 100, "volume": 1000},
        {"high": 112, "low": 108, "close": 110, "volume": 2000},
    ])
    assert engine.vwap("X") == pytest.approx((112 + 108 + 110) / 3)


def test_the_ranked_row_now_carries_it():
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState)
    assert 'row["vwap"] = self._vwap_for(' in src, \
        "the row must carry vwap or liveness() has nothing to read"


def test_liveness_uses_it_when_it_is_there():
    """A long trading BELOW its VWAP must read as fading."""
    from core.ranker import liveness
    # Held near its high and still moving, so off_high and recent_pct
    # BOTH read alive -- VWAP is the only thing that differs between
    # these two calls. The first fixture I wrote sat 9% off the high,
    # which trips the off-high rule on its own and proves nothing.
    row = {"day_high": 100.5, "ltp": 100.0, "change_pct": 5.0,
           "recent_pct": 1.0}

    row["vwap"] = 95.0          # buyers paying up -- average buyer ahead
    assert liveness(row)[0] == "alive"

    row["vwap"] = 105.0         # average buyer today is under water
    assert liveness(row)[0] == "fading",         "below VWAP on a long is not a stock to be joining"
