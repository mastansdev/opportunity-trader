"""---- WHO IS WINNING, AND IS THE PRICE FOLLOWING. 15 September 2026. ----

    "i asked to check the strength on buying or selling side & price
     action stocks were made during the trades. not a fixed % to check
     the freshness. who asked u to do so?"          -- the operator

The fixed 2% "freshness" gate is gone (it refused ZENSARTECH, 430 -> 479).
In its place, the two checks he asked for, direction only.
"""

import pytest

import core.order_flow as order_flow
from core import auto_entry
from tests.test_a_broken_check_refuses_the_trade import _Engine


@pytest.fixture(autouse=True)
def _checks_on(monkeypatch):
    import config
    monkeypatch.setattr(config, "ENTRY_NEEDS_BUYERS", True)
    monkeypatch.setattr(config, "ENTRY_NEEDS_PRICE_FOLLOWING", True)


def _row(**extra):
    row = {"symbol": "TESTCO", "action": "BUY", "ltp": 100.0,
           "plan": {"ok": True, "qty": 10, "stop": 95.0, "target": 110.0},
           "why": "a reason"}
    row.update(extra)
    return row


def _why(row, monkeypatch, flow=None, live=None):
    monkeypatch.setattr(order_flow, "still_buying", lambda s, **k: flow)
    monkeypatch.setattr(order_flow, "pressure", lambda s: live)
    return auto_entry.refuse_reason(row, _Engine(), held=set(),
                                    max_positions=10)


def test_the_fixed_percentage_is_gone():
    import config
    assert config.ENTRY_MAX_EXTENSION_PCT is None


def test_a_price_that_fell_since_the_rank_is_refused(monkeypatch):
    """SUNTV: ranked 476.94, bought 471.64."""
    why = _why(_row(drift_since_rank_pct=-1.11), monkeypatch)
    assert why and "not following" in why


def test_sellers_ahead_is_refused(monkeypatch):
    flow = {"still_buying": False, "positive": False, "delta": -5000,
            "was": -2000, "minutes": 15}
    why = _why(_row(drift_since_rank_pct=0.4), monkeypatch, flow=flow)
    assert why and "sellers are ahead" in why


def test_buying_that_stopped_growing_is_refused(monkeypatch):
    flow = {"still_buying": False, "positive": True, "delta": 3000,
            "was": 9000, "minutes": 15}
    why = _why(_row(drift_since_rank_pct=0.4), monkeypatch, flow=flow)
    assert why and "stopped growing" in why


def test_early_in_the_day_the_running_total_decides(monkeypatch):
    why = _why(_row(), monkeypatch, flow=None, live={"delta": -10})
    assert why and "sellers are ahead" in why


def test_buyers_winning_and_price_holding_passes(monkeypatch):
    """ZENSARTECH's shape: far above its open, buyers still adding."""
    flow = {"still_buying": True, "positive": True, "delta": 90000,
            "was": 60000, "minutes": 15}
    assert _why(_row(drift_since_rank_pct=0.2, extension_pct=10.7),
                monkeypatch, flow=flow) is None


def test_no_reading_is_not_a_refusal(monkeypatch):
    assert _why(_row(), monkeypatch, flow=None, live=None) is None
