"""
Decision-correctness tests for core/momentum_universe.py --
TOP_N_MOMENTUM_MODE's top-25-gainers/top-25-losers shortlist
(config.py, 2026-07-24 experiment).
"""

import core.momentum_universe as momentum_module
from core.momentum_universe import MomentumUniverse


class _FakeMarketData:
    def __init__(self, day_opens, latest_prices):
        self.day_opens = day_opens
        self.latest_prices = latest_prices

    def get_day_open(self, symbol):
        return self.day_opens.get(symbol)

    def get_latest_price(self, symbol):
        return self.latest_prices.get(symbol)


class _FakeMasterLoader:
    def __init__(self, symbols):
        self.symbols = symbols

    def all_symbols(self):
        return self.symbols


def _universe(day_opens, latest_prices, symbols=None):
    symbols = symbols or list(day_opens.keys())
    market_data = _FakeMarketData(day_opens, latest_prices)
    loader = _FakeMasterLoader(symbols)
    return MomentumUniverse(market_data, loader)


def test_unlocked_universe_rejects_every_symbol_fail_closed():
    universe = _universe({}, {})
    assert not universe.is_locked()
    assert universe.is_eligible("TCS", "LONG") is False
    assert universe.is_eligible("TCS", "SHORT") is False


def test_lock_picks_top_gainers_and_top_losers_by_pct_change(monkeypatch):
    monkeypatch.setattr(momentum_module, "TOP_N_MOMENTUM_LIST_SIZE", 2)

    day_opens = {"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0, "E": 100.0}
    latest_prices = {
        "A": 110.0,  # +10% -- top gainer
        "B": 105.0,  # +5%  -- 2nd gainer
        "C": 100.0,  # 0%   -- middle, excluded from both
        "D": 95.0,   # -5%  -- 2nd loser
        "E": 90.0,   # -10% -- top loser
    }
    universe = _universe(day_opens, latest_prices)

    result = universe.lock()

    assert result["long"] == ["A", "B"]
    assert result["short"] == ["D", "E"]
    assert universe.is_locked()


def test_locked_eligibility_matches_the_locked_lists(monkeypatch):
    monkeypatch.setattr(momentum_module, "TOP_N_MOMENTUM_LIST_SIZE", 1)

    day_opens = {"A": 100.0, "B": 100.0}
    latest_prices = {"A": 120.0, "B": 80.0}
    universe = _universe(day_opens, latest_prices)
    universe.lock()

    assert universe.is_eligible("A", "LONG") is True
    assert universe.is_eligible("A", "SHORT") is False
    assert universe.is_eligible("B", "SHORT") is True
    assert universe.is_eligible("B", "LONG") is False
    # Never in either list.
    assert universe.is_eligible("ZZZZ", "LONG") is False
    assert universe.is_eligible("ZZZZ", "SHORT") is False


def test_symbols_with_no_price_data_are_excluded_from_ranking(monkeypatch):
    monkeypatch.setattr(momentum_module, "TOP_N_MOMENTUM_LIST_SIZE", 5)

    day_opens = {"A": 100.0, "B": None}
    latest_prices = {"A": 110.0}  # B has no latest price at all
    universe = _universe(day_opens, latest_prices, symbols=["A", "B"])

    result = universe.lock()

    assert "A" in result["long"]
    assert "B" not in result["long"]
    assert "B" not in result["short"]


def test_lock_is_a_snapshot_not_a_live_view(monkeypatch):
    """Locking twice would silently replace the day's shortlist --
    main.py's own guard (momentum_universe.is_locked()) prevents a
    second call in practice, but the object itself doesn't refuse a
    second lock() call; this test documents that a second lock CAN
    change the list if ever called twice, motivating why main.py's
    guard matters."""
    monkeypatch.setattr(momentum_module, "TOP_N_MOMENTUM_LIST_SIZE", 1)

    day_opens = {"A": 100.0, "B": 100.0}
    latest_prices = {"A": 120.0, "B": 80.0}
    universe = _universe(day_opens, latest_prices)

    first = universe.lock()
    assert first["long"] == ["A"]

    # Prices moved a lot; locking again WOULD give a different list.
    universe.market_data.latest_prices["A"] = 70.0
    second = universe.lock()
    assert second["long"] == ["B"]


def test_export_state_round_trips_through_load_state(monkeypatch):
    monkeypatch.setattr(momentum_module, "TOP_N_MOMENTUM_LIST_SIZE", 1)

    day_opens = {"A": 100.0, "B": 100.0}
    latest_prices = {"A": 120.0, "B": 80.0}
    universe = _universe(day_opens, latest_prices)
    universe.lock()
    exported = universe.export_state()

    restored = MomentumUniverse(market_data=None, master_loader=None)
    restored.load_state(exported)

    assert restored.is_locked()
    assert restored.is_eligible("A", "LONG")
    assert restored.is_eligible("B", "SHORT")


def test_export_state_before_locking_is_empty_lists():
    universe = _universe({}, {})
    assert universe.export_state() == {"long": [], "short": []}


def test_load_state_with_empty_dict_leaves_universe_unlocked():
    universe = MomentumUniverse(market_data=None, master_loader=None)
    universe.load_state({})
    assert not universe.is_locked()

    universe.load_state({"long": [], "short": []})
    assert not universe.is_locked()
