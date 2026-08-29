"""If a single stop width is ever set, both paths must honour it.

    "do not fix the 2.5% for every stock"   -- operator, 18 Aug 2026

config.FIXED_STOP_PCT was set to 2.0 on 29 August and reverted the
same day. It was chosen on 18-27 August and measured on 18-27 August;
against 3-17 August, eleven sessions it had never seen, it came to
-Rs 48,722 where the ATR rule it replaced came to -Rs 28,623. The
whole advantage was fitted.

So the dial is None and the ATR rule is live. What this file guards
is the MECHANISM, because the dial is one line from being set again:
whenever a width is fixed, core/position_plan.py (the alert that
reaches his phone) and core/engine.py (the position that gets
managed) must both read the same one. Those two disagreeing is the
quiet failure -- an alert quoting one stop while the trade holds
another -- and it would not show up in any P&L.

Every test here sets the dial explicitly. None of them assumes what
the live value is.
"""

import pytest

from core import position_plan
from core.position_plan import plan
from core.rules import MAX_STOP_DISTANCE_PCT, MIN_STOP_DISTANCE_PCT

WIDTH = 2.0


@pytest.fixture(autouse=True)
def fixed(monkeypatch):
    """Set the dial for this file. The live value is not assumed."""
    from core import engine as engine_module
    monkeypatch.setattr(position_plan, "FIXED_STOP_PCT", WIDTH)
    monkeypatch.setattr(engine_module, "FIXED_STOP_PCT", WIDTH)


def _hard_stop_pct(symbol):
    """core/engine.py's own method, off an Engine that was never built.

    Constructing a real Engine opens the broker, the stores and the
    candle feed. The method reads config and the daily ATR store and
    nothing else, so it is called unbound on a stand-in.
    """
    from core import engine as engine_module

    class _Stub:
        portfolio = None
        open_positions = {}

    return engine_module.Engine._hard_stop_pct(_Stub(), symbol)


# ------------------------------------------------- the two paths agree

def test_the_alert_and_the_position_use_the_same_width():
    """The failure this file exists for."""
    got = plan(1963.4, "BUY", day_low=1955.0, day_high=2000.0,
               atr=58.0, symbol="TESTCO")
    assert got["ok"], got
    assert round(got["stop_pct"], 6) == WIDTH
    assert round(_hard_stop_pct("TESTCO") * 100.0, 6) == WIDTH


def test_the_width_does_not_vary_by_stock_when_one_is_set():
    """That is the whole point of the dial, and its whole cost."""
    widths = {_hard_stop_pct(s) for s in
              ("RELIANCE", "YASHO", "PARAS", "NOSUCHSTOCKANYWHERE")}
    assert widths == {WIDTH / 100.0}


def test_the_stop_price_matches_the_percent_it_reports():
    entry = 657.0
    got = plan(entry, "BUY", day_low=600.0, day_high=670.0,
               atr=20.0, symbol="TESTCO")
    assert got["ok"], got
    assert abs(got["stop"] - entry * (1 - got["stop_pct"] / 100.0)) < 0.01


def test_a_short_stops_above_entry():
    entry = 500.0
    got = plan(entry, "SELL", day_low=490.0, day_high=505.0,
               atr=15.0, symbol="TESTCO")
    if got.get("ok"):
        assert got["stop"] > entry


# ------------------------------------------------- sizing is unchanged

def test_quantity_is_still_risk_divided_by_the_distance():
    """The sizing rule does not change. Only the distance does."""
    from core.rules import RISK_PER_TRADE_RS

    entry = 1963.4
    got = plan(entry, "BUY", day_low=1955.0, day_high=2000.0,
               atr=58.0, symbol="TESTCO")
    assert got["ok"], got
    distance = entry - got["stop"]
    assert got["qty"] == int(RISK_PER_TRADE_RS // distance)


def test_a_tight_day_low_does_not_refuse_the_trade_under_a_fixed_width():
    """A fixed width has no level to sit too close to.

    This is the RAILTEL shape of 19 August -- a stock making highs on
    a real event, whose day low ends up a tenth of a percent away.
    Under the structural rule that decided whether it reached his
    phone; under a fixed width the question cannot arise.
    """
    got = plan(104.0, "BUY", day_low=103.9, day_high=104.2,
               atr=3.1, symbol="TESTCO")
    assert got["ok"], got
    assert round(got["stop_pct"], 6) == WIDTH


# ------------------------------------------------- the guards still run

def test_the_bounds_still_apply_to_a_badly_chosen_width(monkeypatch):
    """A fixed width is not exempt from the MIN/MAX guards."""
    monkeypatch.setattr(position_plan, "FIXED_STOP_PCT",
                        MAX_STOP_DISTANCE_PCT + 1.0)
    got = plan(500.0, "BUY", day_low=490.0, day_high=505.0,
               atr=15.0, symbol="TESTCO")
    assert not got["ok"]
    assert "too far" in got["why"]


def test_none_falls_back_to_the_structural_stop(monkeypatch):
    """This is the LIVE state, and it must stay one line away.

    With the dial off, the ATR-scaled rule and its refusal come
    straight back -- which is what the revert on 29 August relied on.
    """
    monkeypatch.setattr(position_plan, "FIXED_STOP_PCT", None)
    got = plan(500.0, "BUY", day_low=475.0, day_high=505.0,
               atr=15.0, symbol="TESTCO")
    assert got["ok"], got
    assert got["stop_pct"] > MIN_STOP_DISTANCE_PCT
    assert round(got["stop_pct"], 6) != WIDTH


def test_a_near_zero_atr_still_cannot_produce_a_hair_thin_stop():
    """The SWIGGY/ACUTAAS safety, under the fixed width.

    tests/test_no_trail_hard_stop.py proves it for the ATR rule.
    Whichever dial is live, a quiet candle window must never size a
    position off a 46-paise stop.
    """
    assert _hard_stop_pct("NOSUCHSTOCKANYWHERE") * 100.0 == WIDTH
