"""
Decision-correctness tests for state_store: does a restart
actually get back what was saved, and does it REFUSE to load
anything from a different day rather than silently carrying
stale ranges/positions/trailing-stops/portfolio/entry-blocks/
momentum-universe forward.
"""

import os

from core import state_store


def test_save_then_load_round_trips_exactly(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    orb_ranges = {"TCS": {"high": 105.0, "low": 100.0, "complete": True}}
    positions = {"TCS": {"security_id": "500", "qty": 1, "entry_price": 105.0, "direction": "LONG"}}
    trailing_stops = {"TCS": {"stop": 101.0, "recent": [100.0, 101.0], "direction": "LONG"}}
    portfolio = {"available_capital": 990000.0, "realized_pnl": 1500.0}
    entry_blocks = {"RELIANCE": {"LONG": "contradicting news -- bearish (90%) -- x."}}
    momentum_universe = {"long": ["TCS", "INFY"], "short": ["SBIN", "ITC"]}

    state_store.save(
        orb_ranges, positions, trailing_stops, portfolio, entry_blocks,
        momentum_universe, path=path,
    )
    (loaded_ranges, loaded_positions, loaded_stops, loaded_portfolio,
     loaded_blocks, loaded_momentum) = state_store.load(
        path=path, today=state_store.datetime.now().date().isoformat()
    )

    assert loaded_ranges == orb_ranges
    assert loaded_positions == positions
    assert loaded_stops == trailing_stops
    assert loaded_portfolio == portfolio
    assert loaded_blocks == entry_blocks
    assert loaded_momentum == momentum_universe


def test_optional_fields_default_to_empty_dict_when_not_passed(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    state_store.save({}, {}, path=path)  # everything else omitted

    (_, _, loaded_stops, loaded_portfolio, loaded_blocks,
     loaded_momentum) = state_store.load(
        path=path, today=state_store.datetime.now().date().isoformat()
    )

    assert loaded_stops == {}
    assert loaded_portfolio == {}
    assert loaded_blocks == {}
    assert loaded_momentum == {}


def test_missing_file_returns_all_none(tmp_path):
    path = os.path.join(str(tmp_path), "nope.json")
    ranges, positions, stops, portfolio, blocks, momentum = state_store.load(path=path)
    assert ranges is None
    assert positions is None
    assert stops is None
    assert portfolio is None
    assert blocks is None
    assert momentum is None


def test_state_from_a_different_day_is_never_loaded(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    state_store.save(
        {"TCS": {"high": 1, "low": 1, "complete": True}}, {}, path=path
    )

    ranges, positions, stops, portfolio, blocks, momentum = state_store.load(
        path=path, today="1999-01-01"
    )

    assert ranges is None
    assert positions is None
    assert stops is None
    assert portfolio is None
    assert blocks is None
    assert momentum is None


def test_corrupt_file_returns_all_none_not_a_crash(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    ranges, positions, stops, portfolio, blocks, momentum = state_store.load(path=path)

    assert ranges is None
    assert positions is None
    assert stops is None
    assert portfolio is None
    assert blocks is None
    assert momentum is None


def test_empty_snapshot_round_trips_to_empty_dicts(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    state_store.save({}, {}, path=path)

    ranges, positions, stops, portfolio, blocks, momentum = state_store.load(
        path=path, today=state_store.datetime.now().date().isoformat()
    )

    assert ranges == {}
    assert positions == {}
    assert stops == {}
    assert portfolio == {}
    assert blocks == {}
    assert momentum == {}


def test_a_saved_entry_block_survives_being_loaded_back_into_an_engine(tmp_path):
    """Integration-shaped check: the whole point of persisting
    entry_blocks is that Engine.load_entry_blocks() can consume
    exactly what comes back from here."""
    from core.engine import Engine

    path = os.path.join(str(tmp_path), "state.json")
    entry_blocks = {"RELIANCE": {"LONG": "contradicting news -- bearish (90%) -- x."}}
    state_store.save({}, {}, entry_blocks=entry_blocks, path=path)

    _, _, _, _, loaded_blocks, _ = state_store.load(
        path=path, today=state_store.datetime.now().date().isoformat()
    )

    engine = Engine()
    engine.load_entry_blocks(loaded_blocks)

    assert engine.entry_blocked == entry_blocks


def test_a_saved_momentum_universe_survives_being_loaded_back(tmp_path):
    """Integration-shaped check: the whole point of persisting the
    momentum universe lock is that MomentumUniverse.load_state() can
    consume exactly what comes back from here, after a restart past
    ORB_WINDOW_END."""
    from core.momentum_universe import MomentumUniverse

    path = os.path.join(str(tmp_path), "state.json")
    momentum_universe = {"long": ["TCS", "INFY"], "short": ["SBIN", "ITC"]}
    state_store.save({}, {}, momentum_universe=momentum_universe, path=path)

    _, _, _, _, _, loaded_momentum = state_store.load(
        path=path, today=state_store.datetime.now().date().isoformat()
    )

    universe = MomentumUniverse(market_data=None, master_loader=None)
    universe.load_state(loaded_momentum)

    assert universe.is_locked()
    assert universe.is_eligible("TCS", "LONG")
    assert not universe.is_eligible("TCS", "SHORT")
    assert universe.is_eligible("SBIN", "SHORT")
