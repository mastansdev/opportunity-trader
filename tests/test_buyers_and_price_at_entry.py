"""---- WHO IS WINNING, AND WHAT THE CANDLES SAY. 15 September 2026. ----

    "i asked to check the strength on buying or selling side & price
     action stocks were made during the trades. not a fixed % to check
     the freshness. who asked u to do so?"          -- the operator

    "check the previous formed candles & volume, price action formed"
                                                    -- the operator, evening

The fixed 2% "freshness" gate is gone (it refused ZENSARTECH, 430 -> 479).
The one-tick "price fell 0.0% since ranked" check is gone (it refused FSL).
In their place: order flow, and price action read off 1-minute candles.
"""

from datetime import datetime

import pytest

import core.order_flow as order_flow
from core import auto_entry, price_action
from core.candle_engine import CandleEngine
from tests.test_a_broken_check_refuses_the_trade import _Engine

NOW = datetime(2026, 9, 15, 10, 0, 30)


@pytest.fixture(autouse=True)
def _checks_on(monkeypatch):
    import config
    monkeypatch.setattr(config, "ENTRY_NEEDS_BUYERS", True)
    monkeypatch.setattr(config, "ENTRY_NEEDS_PRICE_ACTION", True)


def _bar(minute, o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v,
            "time": datetime(2026, 9, 15, 9, minute, 30)}


RISING = [_bar(55, 100, 101, 99.5, 100.8, 3000),
          _bar(56, 100.8, 101.5, 100.4, 101.2, 2500),
          _bar(57, 101.2, 101.4, 100.6, 100.9, 800),
          _bar(58, 100.9, 102.0, 100.7, 101.8, 4000)]


def _row(**extra):
    row = {"symbol": "TESTCO", "action": "BUY", "ltp": 101.8,
           "ranked_ltp": 101.0,
           "plan": {"ok": True, "qty": 10, "stop": 95.0, "target": 110.0},
           "why": "a reason"}
    row.update(extra)
    return row


def _engine_with(bars):
    engine = _Engine()
    store = CandleEngine()
    store._closed_candles["TESTCO"] = list(bars)
    engine.candle_engine = store
    return engine


def _why(row, monkeypatch, flow=None, live=None, engine=None):
    monkeypatch.setattr(order_flow, "still_buying", lambda s, **k: flow)
    monkeypatch.setattr(order_flow, "pressure", lambda s: live)
    return auto_entry.refuse_reason(row, engine or _Engine(), now=NOW,
                                    held=set(), max_positions=10)


def test_the_fixed_percentage_is_gone():
    import config
    assert config.ENTRY_MAX_EXTENSION_PCT is None


# ---- price action ----

def test_rising_candles_with_buying_volume_pass():
    got = price_action.read(RISING, 101.8, ranked_price=101.0, vwap=100.9)
    assert got["ok"], got["why"]


def test_a_one_tick_dip_under_the_rank_is_not_a_refusal():
    """FSL, 15 Sep: refused for 'price fell 0.0% since ranked'. Just under
    the ranked price with a green candle and no new low is a pullback
    that held."""
    got = price_action.read(RISING, 100.99, ranked_price=101.0)
    assert got["ok"], got["why"]


def test_below_the_rank_and_still_falling_is_refused():
    """SUNTV: ranked 476.94, bought 471.64 while it was still falling."""
    bars = RISING[:3] + [_bar(58, 100.9, 101.0, 100.5, 100.6, 500)]
    got = price_action.read(bars, 100.6, ranked_price=101.0)
    assert not got["ok"] and "still falling" in got["why"]


def test_a_new_low_is_refused():
    bars = RISING[:3] + [_bar(58, 100.9, 101.6, 99.0, 101.5, 5000)]
    got = price_action.read(bars, 101.5)
    assert not got["ok"] and "new low" in got["why"]


def test_more_volume_on_falling_candles_is_refused():
    bars = [_bar(55, 100, 100.5, 99.8, 100.2, 500),
            _bar(56, 100.2, 100.3, 99.9, 100.0, 6000),
            _bar(57, 100.0, 100.6, 99.95, 100.4, 700)]
    got = price_action.read(bars, 100.4)
    assert not got["ok"] and "more volume on falling" in got["why"]


def test_below_vwap_is_refused():
    got = price_action.read(RISING, 101.8, vwap=102.5)
    assert not got["ok"] and "VWAP" in got["why"]


def test_before_three_candles_it_waits():
    got = price_action.read(RISING[:2], 101.2)
    assert not got["ok"] and "not formed yet" in got["why"]


def test_pre_open_and_yesterday_candles_do_not_count():
    bars = [dict(b, time=datetime(2026, 9, 15, 9, 5)) for b in RISING[:3]]
    bars.append(dict(RISING[3], time=datetime(2026, 9, 14, 15, 59, 50)))
    got = price_action.for_symbol(_engine_with(bars), "TESTCO", 101.8, now=NOW)
    assert not got["ok"] and "not formed yet" in got["why"]


def test_after_a_restart_vwap_is_not_asked():
    """Candles only from 11:00 (main.py restarted): a VWAP of the last
    hour is not today's average buyer, so that question is skipped."""
    late = [dict(b, time=datetime(2026, 9, 15, 11, i)) for i, b in enumerate(RISING)]
    engine = _engine_with(late)
    engine.candle_engine.vwap = lambda s: 150.0     # would refuse if asked
    got = price_action.for_symbol(engine, "TESTCO", 101.8,
                                  now=datetime(2026, 9, 15, 11, 5, 30))
    assert got["ok"], got["why"]


def test_from_the_open_vwap_is_asked():
    engine = _engine_with([_bar(15, 99, 100, 98.5, 99.5, 900)] + RISING)
    engine.candle_engine.vwap = lambda s: 150.0
    got = price_action.for_symbol(engine, "TESTCO", 101.8, now=NOW)
    assert not got["ok"] and "VWAP" in got["why"]


def test_the_gate_uses_the_engines_candles(monkeypatch):
    flow = {"still_buying": True, "positive": True, "delta": 9, "was": 1,
            "minutes": 15}
    assert _why(_row(), monkeypatch, flow=flow,
                engine=_engine_with(RISING)) is None
    falling = RISING[:3] + [_bar(58, 100.9, 101.0, 99.0, 99.2, 9000)]
    why = _why(_row(ltp=99.2), monkeypatch, flow=flow,
               engine=_engine_with(falling))
    assert why and "new low" in why


# ---- order flow ----

def test_sellers_ahead_is_refused(monkeypatch):
    flow = {"still_buying": False, "positive": False, "delta": -5000,
            "was": -2000, "minutes": 15}
    why = _why(_row(), monkeypatch, flow=flow)
    assert why and "sellers are ahead" in why


def test_buying_that_stopped_growing_is_refused(monkeypatch):
    flow = {"still_buying": False, "positive": True, "delta": 3000,
            "was": 9000, "minutes": 15}
    why = _why(_row(), monkeypatch, flow=flow)
    assert why and "stopped growing" in why


def test_early_in_the_day_the_running_total_decides(monkeypatch):
    why = _why(_row(), monkeypatch, flow=None, live={"delta": -10})
    assert why and "sellers are ahead" in why


def test_buyers_winning_and_price_holding_passes(monkeypatch):
    """ZENSARTECH's shape: far above its open, buyers still adding."""
    flow = {"still_buying": True, "positive": True, "delta": 90000,
            "was": 60000, "minutes": 15}
    assert _why(_row(extension_pct=10.7), monkeypatch, flow=flow,
                engine=_engine_with(RISING)) is None


def test_no_flow_reading_is_not_a_refusal(monkeypatch):
    assert _why(_row(), monkeypatch, flow=None, live=None) is None
