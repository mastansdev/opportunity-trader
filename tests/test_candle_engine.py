from datetime import datetime

from core.candle_engine import CandleEngine


def _t(hh, mm, ss):
    return datetime(2026, 7, 22, hh, mm, ss)


def test_candle_volume_is_the_cumulative_delta_over_the_candle():
    """Change 2: the feed sends DAY-cumulative volume; a candle's own
    volume is (last cumulative in the candle) - (first). Here the 9:31
    candle spans cumulative 1000 -> 1000 -> 1500, so its volume=500."""
    ce = CandleEngine()
    ce.update("TCS", 100.0, _t(9, 31, 0), cum_volume=1000)
    ce.update("TCS", 101.0, _t(9, 31, 20), cum_volume=1000)
    ce.update("TCS", 102.0, _t(9, 31, 40), cum_volume=1500)
    closed = ce.update("TCS", 103.0, _t(9, 32, 0), cum_volume=1500)
    assert closed["volume"] == 500


def test_candle_volume_is_none_when_the_feed_supplies_no_volume():
    """Ticker mode (no cum_volume) -> candle volume stays None, and
    the volume filter fails open on it."""
    ce = CandleEngine()
    ce.update("TCS", 100.0, _t(9, 31, 0))
    ce.update("TCS", 101.0, _t(9, 31, 30))
    closed = ce.update("TCS", 102.0, _t(9, 32, 0))
    assert closed["volume"] is None


def test_candle_closes_on_minute_boundary_with_correct_ohlc():
    ce = CandleEngine()

    assert ce.update("TCS", 100.0, _t(9, 31, 0)) is None
    assert ce.update("TCS", 105.0, _t(9, 31, 20)) is None
    assert ce.update("TCS", 98.0, _t(9, 31, 40)) is None

    # First tick of the NEXT minute closes the previous candle.
    closed = ce.update("TCS", 103.0, _t(9, 32, 0))

    assert closed is not None
    assert closed["open"] == 100.0
    assert closed["high"] == 105.0
    assert closed["low"] == 98.0
    assert closed["close"] == 98.0  # last tick before the new bucket


def test_last_closed_returns_none_until_a_candle_actually_closes():
    ce = CandleEngine()
    assert ce.last_closed("TCS") is None

    ce.update("TCS", 100.0, _t(9, 31, 0))
    assert ce.last_closed("TCS") is None  # still open

    ce.update("TCS", 101.0, _t(9, 32, 0))
    assert ce.last_closed("TCS") is not None


def test_last_n_closed_returns_empty_list_when_nothing_closed_yet():
    ce = CandleEngine()
    assert ce.last_n_closed("TCS", 5) == []

    ce.update("TCS", 100.0, _t(9, 31, 0))  # still open, not closed
    assert ce.last_n_closed("TCS", 5) == []


def test_last_n_closed_returns_fewer_than_n_without_padding():
    ce = CandleEngine()
    for minute in range(31, 34):  # closes 2 candles (31, 32), 33 stays open
        ce.update("TCS", 100.0, _t(9, minute, 0))

    result = ce.last_n_closed("TCS", 5)
    assert len(result) == 2


def test_last_n_closed_is_oldest_first_and_caps_at_n():
    ce = CandleEngine()
    closes = []
    for minute in range(31, 40):  # 9 closes ticks -> 8 closed candles
        closed = ce.update("TCS", float(minute), _t(9, minute, 0))
        if closed is not None:
            closes.append(closed)

    result = ce.last_n_closed("TCS", 3)
    assert len(result) == 3
    assert result == closes[-3:]
    assert result[0]["time"] < result[-1]["time"]
