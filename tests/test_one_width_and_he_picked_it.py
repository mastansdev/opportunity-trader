"""The stop is one width now, and the alert and the position share it.

    "do not fix the 2.5% for every stock"   -- operator, 18 Aug 2026
    "Switch to 2.0% fixed"                  -- operator, 29 Aug 2026

Both are his. The second was chosen knowing the first, because the
scaling had stopped scaling: 2.0 x daily ATR, bounded [0.75%, 6.0%],
put 81 of 101 qualified event trades ON the 6% ceiling. These are
3.9%-ATR names by the nature of the setup, so twice the daily range
clears the cap almost every time. The live choice was never
scaled-vs-fixed, it was which fixed number -- and 6% had been chosen
by a ceiling rather than by measurement.

What this file guards is not the number. It is that ONE number
reaches both paths. core/position_plan.py sizes what reaches his
phone; core/engine.py sizes the position that gets managed. Those
two disagreeing is the quiet failure -- an alert that says one stop
and a trade that holds another.
"""

import config
from core import position_plan
from core.position_plan import plan
from core.rules import MAX_STOP_DISTANCE_PCT, MIN_STOP_DISTANCE_PCT


def _hard_stop_pct(symbol):
    """core/engine.py's own method, off an Engine that was never built.

    Constructing a real Engine opens the broker, the stores and the
    candle feed. The method reads nothing but config and the daily
    ATR store, so it is called unbound on a stand-in.
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
    assert round(got["stop_pct"], 6) == float(config.FIXED_STOP_PCT)
    assert round(_hard_stop_pct("TESTCO") * 100.0, 6) \
        == float(config.FIXED_STOP_PCT)


def test_the_width_does_not_vary_by_stock():
    """That is the whole point of the change, and its whole cost."""
    widths = {_hard_stop_pct(s) for s in
              ("RELIANCE", "YASHO", "PARAS", "NOSUCHSTOCKANYWHERE")}
    assert len(widths) == 1


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
    """The sizing rule did not change. Only the distance did."""
    from core.rules import RISK_PER_TRADE_RS

    entry = 1963.4
    got = plan(entry, "BUY", day_low=1955.0, day_high=2000.0,
               atr=58.0, symbol="TESTCO")
    assert got["ok"], got
    distance = entry - got["stop"]
    assert got["qty"] == int(RISK_PER_TRADE_RS // distance)


def test_a_tight_day_low_no_longer_refuses_the_trade():
    """The RAILTEL filter of 19 August, gone as a side effect.

    A stock making highs on a real event is exactly the shape whose
    day low ends up a tenth of a percent away. That used to decide
    whether it reached his phone. A fixed width has no level to be
    too close to.
    """
    got = plan(104.0, "BUY", day_low=103.9, day_high=104.2,
               atr=3.1, symbol="TESTCO")
    assert got["ok"], got
    assert round(got["stop_pct"], 6) == float(config.FIXED_STOP_PCT)


# ------------------------------------------------- the guards still run

def test_the_bounds_still_apply_to_a_badly_chosen_width(monkeypatch):
    """A fixed width is not exempt from the MIN/MAX guards.

    position_plan binds the name at import, so config alone is not
    enough to move it -- which is also why changing the dial needs a
    restart, same as every other config value here.
    """
    monkeypatch.setattr(position_plan, "FIXED_STOP_PCT",
                        MAX_STOP_DISTANCE_PCT + 1.0)
    got = plan(500.0, "BUY", day_low=490.0, day_high=505.0,
               atr=15.0, symbol="TESTCO")
    assert not got["ok"]
    assert "too far" in got["why"]


def test_none_falls_back_to_the_structural_stop(monkeypatch):
    """Set the dial to None and nothing else changes.

    The ATR-scaled rule and its refusal come straight back, so this
    is one line to reverse rather than a rewrite.
    """
    monkeypatch.setattr(position_plan, "FIXED_STOP_PCT", None)
    got = plan(500.0, "BUY", day_low=490.0, day_high=505.0,
               atr=15.0, symbol="TESTCO")
    assert got["ok"], got
    # 490 is the structural stop: 2% of 500 would be 490 too, so use
    # a low that cannot be confused with the fixed width.
    got = plan(500.0, "BUY", day_low=475.0, day_high=505.0,
               atr=15.0, symbol="TESTCO")
    assert got["ok"], got
    assert got["stop_pct"] > MIN_STOP_DISTANCE_PCT
    assert round(got["stop_pct"], 6) != float(config.FIXED_STOP_PCT)
