"""
Decision-correctness tests for the paper capital ledger.
"""

from trading.portfolio import Portfolio


def test_starting_state_has_full_capital_and_zero_pnl():
    p = Portfolio(starting_capital=1_000_000.0)
    assert p.available_capital == 1_000_000.0
    assert p.realized_pnl == 0.0


def test_buy_deducts_notional_from_available_capital():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_buy(price=250.0, qty=100)
    assert p.available_capital == 1_000_000.0 - 25_000.0


def test_sell_returns_notional_and_credits_profit():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_buy(price=250.0, qty=100)
    pnl = p.on_sell(entry_price=250.0, exit_price=260.0, qty=100)

    assert pnl == 1000.0
    assert p.realized_pnl == 1000.0
    # 1,000,000 - 25,000 (buy) + 26,000 (sell proceeds) = 1,001,000
    assert p.available_capital == 1_001_000.0


def test_sell_at_a_loss_debits_realized_pnl():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_buy(price=250.0, qty=100)
    pnl = p.on_sell(entry_price=250.0, exit_price=240.0, qty=100)

    assert pnl == -1000.0
    assert p.realized_pnl == -1000.0


def test_available_capital_can_go_negative_not_floored():
    p = Portfolio(starting_capital=1000.0)
    p.on_buy(price=500.0, qty=100)  # 50,000 notional against 1,000 capital
    assert p.available_capital < 0


def test_deployed_capital_marks_to_latest_price_with_entry_price_fallback():
    p = Portfolio()
    open_positions = {
        "TCS": {"entry_price": 100.0, "qty": 10},
        "INFY": {"entry_price": 200.0, "qty": 5},
    }
    prices = {"TCS": 110.0}  # INFY has no live price yet

    deployed = p.deployed_capital(open_positions, lambda s: prices.get(s))

    # TCS marked at 110 (live), INFY falls back to its entry price 200.
    assert deployed == 110.0 * 10 + 200.0 * 5


def test_snapshot_contains_all_expected_fields():
    # 20% default margin -> a 1000-notional position blocks 200 margin.
    p = Portfolio(starting_capital=1_000_000.0, default_margin_pct=0.20)
    p.on_buy(price=100.0, qty=10)

    snap = p.snapshot({"TCS": {"entry_price": 100.0, "qty": 10}}, lambda s: 105.0)

    assert snap["starting_capital"] == 1_000_000.0
    assert snap["available_capital"] == 1_000_000.0 - 1000.0
    assert snap["deployed_capital"] == 1050.0
    assert snap["realized_pnl"] == 0.0
    # buying power = capital / margin% = 1,000,000 / 0.20 = 5,000,000
    assert snap["buying_power"] == 5_000_000.0
    # real margin blocked = notional 1000 x 20% = 200
    assert snap["used_margin"] == 200.0
    assert snap["available_margin"] == 1_000_000.0 - 200.0


# -- MIS margin model (gates entries, see core/engine.py) --

def test_buying_power_is_capital_over_default_margin_pct():
    p = Portfolio(starting_capital=1_000_000.0, default_margin_pct=0.20)
    assert p.buying_power == 5_000_000.0


def test_used_margin_is_notional_times_margin_pct_long_and_short_alike():
    p = Portfolio(default_margin_pct=0.20)
    open_positions = {
        "TCS": {"entry_price": 100.0, "qty": 10, "direction": "LONG"},
        "INFY": {"entry_price": 200.0, "qty": 5, "direction": "SHORT"},
    }
    # (100*10 + 200*5) notional = 2000; x 20% margin = 400
    assert p.used_margin(open_positions) == 400.0


def test_per_stock_margin_override_is_applied():
    p = Portfolio(default_margin_pct=0.20, margin_overrides={"VOLATILE": 0.50})
    positions = {"VOLATILE": {"entry_price": 100.0, "qty": 10, "direction": "LONG"}}
    # notional 1000 x 50% = 500 (not the 200 the default would give)
    assert p.used_margin(positions) == 500.0


def test_available_margin_is_capital_minus_used_margin():
    p = Portfolio(starting_capital=1_000_000.0, default_margin_pct=0.20)
    open_positions = {"TCS": {"entry_price": 100.0, "qty": 1000, "direction": "LONG"}}
    # notional 100,000 x 20% = 20,000 margin used
    assert p.available_margin(open_positions) == 980_000.0


def test_has_buying_power_for_true_when_the_new_trade_fits():
    p = Portfolio(starting_capital=1_000_000.0, default_margin_pct=0.20)
    # 250*100 = 25,000 notional -> 5,000 margin <= 1,000,000 free
    assert p.has_buying_power_for({}, "TCS", price=250.0, qty=100) is True


def test_has_buying_power_for_false_once_margin_exhausted():
    p = Portfolio(starting_capital=1_000_000.0, default_margin_pct=0.20)
    # One position: notional 5,000,000 x 20% = 1,000,000 margin = all of it.
    open_positions = {
        "SYM": {"entry_price": 1000.0, "qty": 5000, "direction": "LONG"}
    }
    assert p.has_buying_power_for(open_positions, "TCS", price=100.0, qty=1) is False


def test_has_buying_power_for_is_exact_at_the_boundary():
    p = Portfolio(starting_capital=1_000_000.0, default_margin_pct=0.20)
    # notional 5,000,000 x 20% = exactly 1,000,000 margin.
    assert p.has_buying_power_for({}, "TCS", price=5000.0, qty=1000) is True
    assert p.has_buying_power_for({}, "TCS", price=5000.01, qty=1000) is False


def test_short_credits_proceeds_from_the_notional_sold():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_short(price=250.0, qty=100)
    assert p.available_capital == 1_000_000.0 + 25_000.0


def test_cover_at_a_profit_when_price_falls():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_short(price=250.0, qty=100)
    pnl = p.on_cover(entry_price=250.0, exit_price=240.0, qty=100)

    assert pnl == 1000.0  # sold high, bought back lower -- profit
    assert p.realized_pnl == 1000.0
    # 1,000,000 + 25,000 (short proceeds) - 24,000 (cover cost) = 1,001,000
    assert p.available_capital == 1_001_000.0


def test_cover_at_a_loss_when_price_rises():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_short(price=250.0, qty=100)
    pnl = p.on_cover(entry_price=250.0, exit_price=260.0, qty=100)

    assert pnl == -1000.0  # sold low, had to buy back higher -- loss
    assert p.realized_pnl == -1000.0


def test_export_state_then_load_state_round_trips():
    p = Portfolio(starting_capital=1_000_000.0)
    p.on_buy(price=100.0, qty=10)
    p.on_sell(entry_price=100.0, exit_price=110.0, qty=10)

    snapshot = p.export_state()

    restored = Portfolio(starting_capital=1_000_000.0)
    restored.load_state(snapshot)

    assert restored.available_capital == p.available_capital
    assert restored.realized_pnl == p.realized_pnl
