"""
Two gaps the operator's own chart check found, 29 July 2026.

He compared the bot's recorded candles against Dhan and TradingView.
The prices matched exactly -- SMLMAH's circuit-locked minute came back
4,566.00 on both, all four values. What did not match was the EDGES of
the day:

    1. THE OPEN. INFY opened at 1,147.00 (NSE pre-open equilibrium,
       +3.74%). The bot's first tick said 1,145.00, +3.55%. Two
       seconds and two rupees late, because Dhan sends one snapshot
       per symbol roughly every 4.6 seconds and the opening print
       lands between packets. That 0.19% IS the "bot doesn't match
       NSE" complaint.

    2. THE CLOSE. Every one of 666 symbols stopped at 15:27 on a day
       the market traded to 15:30. A candle closes only when a tick
       from the NEXT minute arrives -- and at the end of the session
       there is no next tick, so whatever was open was discarded.
"""

from datetime import datetime

import pytest

from core.candle_engine import CandleEngine
from core.market_data import MarketData


def _t(hour, minute, second=0):
    return datetime(2026, 7, 29, hour, minute, second)


# ---------------------------------------------------------------
# 1. The opening print
# ---------------------------------------------------------------

def test_the_exchange_open_beats_our_first_tick():
    """INFY, 29 July, reproduced exactly."""
    data = MarketData()
    data.on_tick("INFY", 1145.00, _t(9, 15, 2))
    assert data.get_day_open("INFY") == 1145.00      # the late guess

    data.set_official_day_open("INFY", 1147.00)
    assert data.get_day_open("INFY") == 1147.00      # the real open


def test_without_an_official_open_the_first_tick_still_answers():
    """Never worse than before. A symbol Dhan gives no open for keeps
    the old behaviour rather than returning nothing."""
    data = MarketData()
    data.on_tick("INFY", 1145.00, _t(9, 15, 2))
    assert data.get_day_open("INFY") == 1145.00


def test_a_junk_or_zero_open_is_refused():
    """Zero would read as a real opening price and produce a
    nonsensical gap percentage."""
    data = MarketData()
    data.on_tick("INFY", 1145.00, _t(9, 15, 2))
    for bad in (0, -1, None, "", "junk"):
        data.set_official_day_open("INFY", bad)
        assert data.get_day_open("INFY") == 1145.00


def test_the_official_open_survives_a_symbol_with_no_ticks_at_all():
    data = MarketData()
    data.set_official_day_open("QUIET", 500.0)
    assert data.get_day_open("QUIET") == 500.0


def test_a_restart_reference_is_no_longer_the_first_tick_after_restart():
    """The old failure: restart at 11:00 and get_day_open() returned
    11:00's price as 'the open', making every gap and every
    advance/decline colour wrong for the rest of the day."""
    data = MarketData()
    data.on_tick("INFY", 1132.00, _t(11, 0))     # first tick post-restart
    assert data.get_day_open("INFY") == 1132.00

    data.set_official_day_open("INFY", 1147.00)
    assert data.get_day_open("INFY") == 1147.00


# ---------------------------------------------------------------
# 2. The last minutes of the day
# ---------------------------------------------------------------

def test_a_candle_still_open_at_shutdown_is_kept():
    """15:29's candle never closed because 15:30 never ticked."""
    engine = CandleEngine()
    engine.update("INFY", 1150.00, _t(15, 28, 10))
    engine.update("INFY", 1154.20, _t(15, 29, 5))     # closes 15:28
    engine.update("INFY", 1155.60, _t(15, 29, 50))    # still open

    assert engine.last_closed("INFY")["close"] == 1150.00

    finalised = engine.close_open_candles()

    assert [s for s, _ in finalised] == ["INFY"]
    last = engine.last_closed("INFY")
    assert last["close"] == 1155.60
    assert last["high"] == 1155.60


def test_every_symbol_is_finalised_not_just_one():
    """666 symbols lost their last minutes, not one."""
    engine = CandleEngine()
    for symbol in ("INFY", "COFORGE", "KAYNES"):
        engine.update(symbol, 100.0, _t(15, 29, 10))
    assert len(engine.close_open_candles()) == 3


def test_closing_twice_does_not_duplicate_anything():
    engine = CandleEngine()
    engine.update("INFY", 1155.60, _t(15, 29, 50))
    assert len(engine.close_open_candles()) == 1
    assert engine.close_open_candles() == []
    assert len(engine.last_n_closed("INFY", 10)) == 1


def test_volume_is_finalised_on_the_last_candle_too():
    """The closing minutes are often the heaviest of the day. A
    volume of None there would quietly weaken every turnover and
    liquidity reading built on the session."""
    engine = CandleEngine()
    engine.update("INFY", 1150.00, _t(15, 29, 5), cum_volume=1_000_000)
    engine.update("INFY", 1155.60, _t(15, 29, 50), cum_volume=1_250_000)
    engine.close_open_candles()
    assert engine.last_closed("INFY")["volume"] == 250_000


def test_nothing_open_means_nothing_to_close():
    assert CandleEngine().close_open_candles() == []
