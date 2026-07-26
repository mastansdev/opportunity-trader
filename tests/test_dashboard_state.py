"""
Decision-correctness tests for dashboard/state.py. Uses fakes
for every input (engine, market_data, master_loader,
portfolio) so this stays fast and focused on the ASSEMBLY logic,
not re-testing what each real component already proves on its
own.
"""

from datetime import datetime

import pytest

from dashboard.state import DashboardState, _is_circuit_locked, _is_plausible_move


class _FakeOrbEngine:
    def __init__(self, ranges):
        self._ranges = ranges

    def export_state(self):
        return self._ranges


class _FakeTrailingStop:
    def __init__(self, stops=None):
        self._stops = stops or {}

    def get_stop(self, symbol):
        return self._stops.get(symbol)


class _FakeMomentumUniverse:
    def __init__(self, long_symbols=None, short_symbols=None, locked=True):
        self._long = long_symbols or []
        self._short = short_symbols or []
        self._locked = locked

    def is_locked(self):
        return self._locked

    def export_state(self):
        if not self._locked:
            return {"long": [], "short": []}
        return {"long": list(self._long), "short": list(self._short)}


class _FakeTradeController:
    """2026-07-24 -- EXIT ALL popup's "Stop New Entries + Exit All"
    option. Only is_new_entries_paused() is needed by
    dashboard/state.py's _build()."""
    def __init__(self, entries_paused=False):
        self._entries_paused = entries_paused

    def is_new_entries_paused(self):
        return self._entries_paused


class _FakeEngine:
    def __init__(self, orb_ranges=None, open_positions=None,
                 closed_positions=None, stops=None, entry_blocked=None,
                 momentum_universe=None, frozen_symbols=None,
                 circuit_flagged_symbols=None, circuit_snapshot=None,
                 entries_paused=False):
        self.orb_engine = _FakeOrbEngine(orb_ranges or {})
        self.open_positions = open_positions or {}
        self.closed_positions = closed_positions or []
        self.trailing_stop = _FakeTrailingStop(stops)
        self.entry_blocked = entry_blocked or {}
        self.momentum_universe = momentum_universe
        self._frozen_symbols = frozen_symbols or []
        self._circuit_flagged_symbols = circuit_flagged_symbols or []
        self._circuit_snapshot = circuit_snapshot or {}
        self.trade_controller = _FakeTradeController(entries_paused)

    def get_frozen_symbols(self):
        return list(self._frozen_symbols)

    def get_circuit_flagged_symbols(self):
        return list(self._circuit_flagged_symbols)

    def get_circuit_snapshot(self):
        return dict(self._circuit_snapshot)


class _FakeSectorMonitor:
    def __init__(self, panicking=None):
        self.panicking = panicking or set()

    def panicking_sectors(self):
        return set(self.panicking)


class _FakeMarketData:
    def __init__(self, day_opens=None, latest_prices=None, tick_count=0,
                 stale_warning_count=0):
        self.day_opens = day_opens or {}
        self.latest_prices = latest_prices or {}
        self.tick_count = tick_count
        self.stale_warning_count = stale_warning_count

    def get_day_open(self, symbol):
        return self.day_opens.get(symbol)

    def get_latest_price(self, symbol):
        return self.latest_prices.get(symbol)

    def get_tick_count(self):
        return self.tick_count

    def get_stale_warning_count(self):
        return self.stale_warning_count


class _FakeMasterLoader:
    def __init__(self, records):
        self.records = records  # symbol -> {"SECTOR": ...}

    def all_symbols(self):
        return list(self.records.keys())

    def get_by_symbol(self, symbol):
        return self.records.get(symbol)


class _FakePortfolio:
    def snapshot(self, open_positions, get_price):
        return {"available_capital": 999.0}


def _loader(symbols_sectors):
    return _FakeMasterLoader({s: {"SECTOR": sec} for s, sec in symbols_sectors.items()})


def _quote(last_price, open_=None, high=None, low=None, prev_close=None, volume=None,
           upper_limit=None, lower_limit=None):
    return {
        "last_price": last_price, "open": open_, "high": high, "low": low,
        "prev_close": prev_close, "volume": volume,
        "upper_circuit_limit": upper_limit, "lower_circuit_limit": lower_limit,
    }


# --------------------------------------------------
# _is_plausible_move / _is_circuit_locked (pure logic, direct)
# --------------------------------------------------


def test_is_plausible_move_true_when_circuit_limits_unavailable():
    # Fail-open -- absence of circuit data is not evidence of a problem.
    assert _is_plausible_move(-80.0, 100.0, None, None) is True
    assert _is_plausible_move(-80.0, 100.0, 0, 0) is True


def test_is_plausible_move_false_beyond_band_times_multiple():
    # Band is 20% (80-120 around prev_close=100); 1.5x -> 30% ceiling.
    assert _is_plausible_move(-80.0, 100.0, 120.0, 80.0) is False
    assert _is_plausible_move(29.0, 100.0, 120.0, 80.0) is True
    assert _is_plausible_move(31.0, 100.0, 120.0, 80.0) is False


def test_is_circuit_locked_true_only_at_the_exact_limit():
    assert _is_circuit_locked(95.0, upper_limit=105.0, lower_limit=95.0) is True
    assert _is_circuit_locked(105.0, upper_limit=105.0, lower_limit=95.0) is True
    assert _is_circuit_locked(100.0, upper_limit=105.0, lower_limit=95.0) is False


def test_is_circuit_locked_false_when_limits_unavailable():
    assert _is_circuit_locked(95.0, upper_limit=None, lower_limit=None) is False


def test_advances_declines_unchanged_counts_vs_prev_close():
    """2026-07-24: breadth switched from day-open to prev-close --
    see dashboard/state.py's module docstring "SWITCHED 2026-07-24"
    section. prev_close comes from engine.get_circuit_snapshot();
    last_price prefers market_data's live tick, falls back to the
    snapshot's own LTP when no tick has arrived yet."""
    loader = _loader({"TCS": "IT", "INFY": "IT", "SBIN": "BANK", "ITC": "FMCG"})
    market_data = _FakeMarketData(
        latest_prices={"TCS": 105.0, "INFY": 195.0, "SBIN": 300.0},  # ITC never ticked
    )
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(last_price=105.0, prev_close=100.0),
        "INFY": _quote(last_price=195.0, prev_close=200.0),
        "SBIN": _quote(last_price=300.0, prev_close=300.0),
        "ITC": _quote(last_price=400.0, prev_close=400.0),  # ITC never ticked, uses snapshot LTP
    })
    state = DashboardState(engine, market_data, loader)

    state.refresh()
    snap = state.get_snapshot()

    assert snap["advances"] == 1     # TCS
    assert snap["declines"] == 1     # INFY
    assert snap["unchanged"] == 2    # SBIN (flat) + ITC (flat, via snapshot fallback)
    assert snap["universe_size"] == 4


def test_advances_declines_unchanged_when_snapshot_missing_a_symbol():
    """A symbol circuit_monitor's REST poll hasn't reached yet (or
    whose prev_close was unusable) is counted unchanged, never
    guessed -- same convention the old day-open version used for a
    symbol with no ticks yet."""
    loader = _loader({"TCS": "IT", "INFY": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 105.0, "INFY": 195.0})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(last_price=105.0, prev_close=100.0),
        # INFY absent from the snapshot entirely
    })
    state = DashboardState(engine, market_data, loader)

    state.refresh()
    snap = state.get_snapshot()

    assert snap["advances"] == 1     # TCS
    assert snap["unchanged"] == 1    # INFY, no snapshot data


def test_breadth_treats_a_split_artifact_as_unchanged_not_a_real_decline():
    """2026-07-24: JLHL did a 2:10 split; our stored prev_close
    wasn't adjusted, producing a fake ~-80% "decline". The exchange's
    own circuit band (here 80-120, a 20% band around prev_close=100)
    says an 80% move is impossible -- treated as unusable data, same
    "unchanged" bucket as a missing prev_close, never counted as a
    real decline."""
    loader = _loader({"JLHL": "TEXTILES", "TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"JLHL": 20.0, "TCS": 105.0})
    engine = _FakeEngine(circuit_snapshot={
        "JLHL": _quote(last_price=20.0, prev_close=100.0,
                        upper_limit=120.0, lower_limit=80.0),
        "TCS": _quote(last_price=105.0, prev_close=100.0,
                       upper_limit=120.0, lower_limit=80.0),
    })
    state = DashboardState(engine, market_data, loader)

    state.refresh()
    snap = state.get_snapshot()

    assert snap["advances"] == 1     # TCS
    assert snap["declines"] == 0     # JLHL must NOT count as a real decline
    assert snap["unchanged"] == 1    # JLHL, split artifact
    assert snap["universe_size"] == 2


def test_breadth_still_counts_a_genuine_large_move_within_the_circuit_band():
    """A real, big move that stays WITHIN today's circuit band (even
    a wide 20% one) must still count normally -- the sanity filter
    only catches moves that are mathematically impossible, not just
    large."""
    loader = _loader({"TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 118.0})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(last_price=118.0, prev_close=100.0,
                       upper_limit=120.0, lower_limit=80.0),  # +18%, inside the 20% band
    })
    state = DashboardState(engine, market_data, loader)

    state.refresh()
    snap = state.get_snapshot()

    assert snap["advances"] == 1
    assert snap["declines"] == 0
    assert snap["unchanged"] == 0


def test_book_analytics_exposure_and_long_short_from_open_positions():
    """2026-07-24: the redundant green/red 'Sectors' panel was
    replaced by 'My Book' -- open exposure by sector + long/short
    scoreboard. Two IT longs + one BANK short."""
    loader = _loader({"TCS": "IT", "INFY": "IT", "SBIN": "BANK"})
    engine = _FakeEngine(open_positions={
        "TCS": {"entry_price": 100.0, "qty": 10, "direction": "LONG",
                "entry_reason": "STRUCTURAL_LONG_BREAKOUT"},
        "INFY": {"entry_price": 200.0, "qty": 5, "direction": "LONG",
                 "entry_reason": "STRUCTURAL_LONG_BREAKOUT"},
        "SBIN": {"entry_price": 300.0, "qty": 4, "direction": "SHORT",
                 "entry_reason": "STRUCTURAL_SHORT_BREAKDOWN"},
    })
    state = DashboardState(engine, _FakeMarketData(), loader)
    state.refresh()
    book = state.get_snapshot()["book_analytics"]

    assert book["long_open"] == 2
    assert book["short_open"] == 1
    sectors = {r["sector"]: r for r in book["exposure"]}
    assert sectors["IT"]["long"] == 2 and sectors["IT"]["short"] == 0
    assert sectors["IT"]["notional"] == 100 * 10 + 200 * 5
    assert sectors["BANK"]["short"] == 1


def test_gainers_losers_ranked_by_change_pct_vs_prev_close():
    """Replaces the old ORB Bullish/Bearish watchlist (2026-07-23,
    operator instruction) -- ranked by %-change vs PREVIOUS DAY
    close (from circuit_monitor's REST snapshot), not day-open."""
    loader = _loader({"TCS": "IT", "INFY": "IT", "SBIN": "BANK"})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(115.0, 111.0, 116.0, 110.0, 100.0, 50000),   # +15%
        "INFY": _quote(90.0, 95.0, 96.0, 89.0, 100.0, 60000),      # -10%
        "SBIN": _quote(102.0, 100.0, 103.0, 99.0, 100.0, 70000),   # +2%
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    assert [r["symbol"] for r in gl["gainers"]] == ["TCS", "SBIN", "INFY"]
    assert [r["symbol"] for r in gl["losers"]] == ["INFY", "SBIN", "TCS"]
    tcs = gl["gainers"][0]
    assert tcs["sector"] == "IT"
    assert tcs["s_no"] == 1
    assert tcs["open"] == 111.0
    assert tcs["high"] == 116.0
    assert tcs["low"] == 110.0
    assert tcs["prev_close"] == 100.0
    assert tcs["ltp"] == 115.0
    assert tcs["change"] == 15.0
    assert tcs["change_pct"] == 15.0
    assert tcs["volume"] == 50000


def test_gainers_losers_capped_at_configured_count():
    loader = _loader({f"SYM{i}": "IT" for i in range(60)})
    snapshot = {
        f"SYM{i}": _quote(100.0 + i, 100.0, 100.0 + i, 99.0, 100.0, 1000)
        for i in range(60)
    }
    engine = _FakeEngine(circuit_snapshot=snapshot)
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    # config.GAINERS_LOSERS_COUNT is 50 -- 60 candidates must be
    # capped, not all dumped into the table.
    assert len(gl["gainers"]) == 50
    assert len(gl["losers"]) == 50


def test_gainers_losers_skips_symbols_missing_a_usable_prev_close():
    """circuit_monitor's own snapshot already filters these out (see
    core/circuit_monitor.py's _snapshot_row()), but the builder must
    not crash or fabricate a change% if one somehow got through."""
    loader = _loader({"TCS": "IT", "NEWCO": "IT"})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(115.0, 111.0, 116.0, 110.0, 100.0, 50000),
        "NEWCO": _quote(50.0, 50.0, 51.0, 49.0, 0, 1000),  # no prev_close
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    symbols = {r["symbol"] for r in gl["gainers"]} | {r["symbol"] for r in gl["losers"]}
    assert "NEWCO" not in symbols
    assert "TCS" in symbols


def test_gainers_losers_excludes_a_split_artifact_row_entirely():
    """Same JLHL 2:10-split scenario as the breadth test -- must not
    appear in Top Losers at all (no "unchanged" bucket in a ranked
    table, an untrustworthy row simply doesn't compete for a rank)."""
    loader = _loader({"JLHL": "TEXTILES", "TCS": "IT"})
    engine = _FakeEngine(circuit_snapshot={
        "JLHL": _quote(20.0, prev_close=100.0, upper_limit=120.0, lower_limit=80.0),
        "TCS": _quote(105.0, prev_close=100.0, upper_limit=120.0, lower_limit=80.0),
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    symbols = {r["symbol"] for r in gl["gainers"]} | {r["symbol"] for r in gl["losers"]}
    assert "JLHL" not in symbols
    assert "TCS" in symbols


def test_gainers_losers_excludes_a_stock_locked_at_its_circuit_limit():
    """CEMPRO, locked at its 5% lower circuit -- zero real order
    flow, must not rank in Top Losers alongside genuinely liquid,
    tradeable movers."""
    loader = _loader({"CEMPRO": "CEMENT", "TCS": "IT"})
    engine = _FakeEngine(circuit_snapshot={
        # last_price sitting exactly AT lower_circuit_limit -> locked.
        "CEMPRO": _quote(95.0, prev_close=100.0, upper_limit=105.0, lower_limit=95.0),
        "TCS": _quote(90.0, prev_close=100.0, upper_limit=120.0, lower_limit=80.0),
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    symbols = {r["symbol"] for r in gl["gainers"]} | {r["symbol"] for r in gl["losers"]}
    assert "CEMPRO" not in symbols
    assert "TCS" in symbols


def test_gainers_losers_keeps_a_stock_merely_near_but_not_at_its_circuit():
    """Proximity (a few % away) is a different, separate concern
    (core/circuit_monitor.py's CIRCUIT_PROXIMITY_PCT) -- only a
    stock actually AT its limit is excluded here."""
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(circuit_snapshot={
        # 90 is close to the 80 lower limit (12.5% away) but not AT it.
        "TCS": _quote(90.0, prev_close=100.0, upper_limit=120.0, lower_limit=80.0),
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    symbols = {r["symbol"] for r in gl["gainers"]} | {r["symbol"] for r in gl["losers"]}
    assert "TCS" in symbols


def test_gainers_losers_empty_when_no_circuit_monitor_wired_in():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.refresh()

    gl = state.get_snapshot()["gainers_losers"]
    assert gl["gainers"] == []
    assert gl["losers"] == []


def test_gainers_losers_throttled_not_rebuilt_every_refresh():
    """Operator's own choice: 'for every 5 mins', not on every
    DashboardState.refresh() call -- config.GAINERS_LOSERS_REFRESH_SECONDS.
    A second refresh() immediately after the first must reuse the
    exact same cached result, even if the underlying snapshot data
    has since changed."""
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(115.0, 111.0, 116.0, 110.0, 100.0, 50000),
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    first = state.get_snapshot()["gainers_losers"]

    # Underlying data changes, but not enough wall-clock time has
    # passed for a rebuild.
    engine._circuit_snapshot["TCS"] = _quote(999.0, 111.0, 999.0, 110.0, 100.0, 50000)
    state.refresh()
    second = state.get_snapshot()["gainers_losers"]

    assert second["gainers"][0]["ltp"] == first["gainers"][0]["ltp"] == 115.0


def test_open_positions_include_live_pnl_and_sector():
    loader = _loader({"TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 120.0})
    engine = _FakeEngine(
        open_positions={
            "TCS": {
                "entry_price": 100.0, "qty": 10,
                "entry_time": datetime(2026, 7, 23, 9, 31, 30),
                "entry_reason": "STRUCTURAL_LONG_BREAKOUT",
            }
        },
        stops={"TCS": 95.0},
    )
    state = DashboardState(engine, market_data, loader)

    state.refresh()
    rows = state.get_snapshot()["open_positions"]

    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "TCS"
    assert row["direction"] == "LONG"
    assert row["sector"] == "IT"
    assert row["pnl"] == (120.0 - 100.0) * 10
    assert row["stop"] == 95.0
    assert row["entry_time"] == "09:31:30"


def test_open_short_position_pnl_is_the_mirror_of_a_long():
    loader = _loader({"TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 90.0})  # price fell
    engine = _FakeEngine(
        open_positions={
            "TCS": {
                "entry_price": 100.0, "qty": 10, "direction": "SHORT",
                "entry_time": datetime(2026, 7, 23, 9, 31, 30),
                "entry_reason": "STRUCTURAL_SHORT_BREAKDOWN",
            }
        },
        stops={"TCS": 105.0},
    )
    state = DashboardState(engine, market_data, loader)

    state.refresh()
    row = state.get_snapshot()["open_positions"][0]

    assert row["direction"] == "SHORT"
    # Short profits when price FALLS: (entry - last) * qty.
    assert row["pnl"] == (100.0 - 90.0) * 10


def test_closed_positions_use_recorded_pnl_when_present():
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(closed_positions=[{
        "symbol": "TCS", "qty": 10, "entry_price": 100.0, "exit_price": 110.0,
        "entry_time": datetime(2026, 7, 23, 9, 31, 0),
        "exit_time": datetime(2026, 7, 23, 9, 45, 0),
        "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "exit_reason": "MANUAL_EXIT",
        "holding_seconds": 840.0, "pnl": 100.0,
    }])
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    rows = state.get_snapshot()["closed_positions"]

    assert len(rows) == 1
    assert rows[0]["pnl"] == 100.0
    assert rows[0]["holding_seconds"] == 840.0


def test_closed_positions_fall_back_to_computed_pnl_when_missing():
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(closed_positions=[{
        "symbol": "TCS", "qty": 10, "entry_price": 100.0, "exit_price": 90.0,
        "entry_time": None, "exit_time": None,
        "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "exit_reason": "TRAILING_STOP",
        "holding_seconds": None, "pnl": None,  # no portfolio was wired in
    }])
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    rows = state.get_snapshot()["closed_positions"]

    assert rows[0]["direction"] == "LONG"  # default when missing
    assert rows[0]["pnl"] == (90.0 - 100.0) * 10


def test_closed_short_position_fallback_pnl_is_the_mirror_of_a_long():
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(closed_positions=[{
        "symbol": "TCS", "qty": 10, "entry_price": 100.0, "exit_price": 90.0,
        "direction": "SHORT",
        "entry_time": None, "exit_time": None,
        "entry_reason": "STRUCTURAL_SHORT_BREAKDOWN", "exit_reason": "TRAILING_STOP",
        "holding_seconds": None, "pnl": None,
    }])
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    rows = state.get_snapshot()["closed_positions"]

    assert rows[0]["direction"] == "SHORT"
    assert rows[0]["pnl"] == (100.0 - 90.0) * 10  # profit -- price fell


def test_risk_filters_empty_when_nothing_blocked_and_no_sector_monitor():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.refresh()

    filters = state.get_snapshot()["risk_filters"]
    assert filters == {
        "panic_sectors": [], "blocked_symbols": [], "frozen_symbols": [],
        "circuit_flagged_symbols": [],
    }


def test_risk_filters_list_blocked_symbols_and_panic_sectors():
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(entry_blocked={
        "RELIANCE": {"LONG": "contradicting news -- bearish (90%) -- x."},
        "SUNPHARMA": {"LONG": "sector 'PHARMA' is panic-flagged today -- ..."},
    })
    sector_monitor = _FakeSectorMonitor(panicking={"PHARMA"})
    state = DashboardState(
        engine, _FakeMarketData(), loader, sector_monitor=sector_monitor
    )

    state.refresh()
    filters = state.get_snapshot()["risk_filters"]

    assert filters["panic_sectors"] == ["PHARMA"]
    assert filters["blocked_symbols"] == [
        {"symbol": "RELIANCE", "direction": "LONG",
         "reason": "contradicting news -- bearish (90%) -- x."},
        {"symbol": "SUNPHARMA", "direction": "LONG",
         "reason": "sector 'PHARMA' is panic-flagged today -- ..."},
    ]
    assert filters["frozen_symbols"] == []


def test_risk_filters_surfaces_frozen_feed_symbols():
    """New 2026-07-23, alongside core/engine.py's frozen-price
    detection (HFCL) -- the dashboard must show a frozen symbol the
    same way it already shows a news/sector block, so the operator
    can see WHY a dead-looking symbol stopped trading."""
    loader = _loader({"HFCL": "TELECOM"})
    engine = _FakeEngine(frozen_symbols=["HFCL"])
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    filters = state.get_snapshot()["risk_filters"]

    assert filters["frozen_symbols"] == ["HFCL"]


def test_risk_filters_surfaces_circuit_flagged_symbols():
    """New 2026-07-23 evening, alongside core/circuit_monitor.py --
    the PROACTIVE follow-up to the frozen-feed test above: the
    dashboard must show a symbol the bot is currently avoiding/
    exiting because it's approaching a circuit limit, same visibility
    pattern as every other risk-filter reason."""
    loader = _loader({"HFCL": "TELECOM"})
    engine = _FakeEngine(circuit_flagged_symbols=[
        {"symbol": "HFCL", "side": "LOWER", "gap_pct": 1.23},
    ])
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    filters = state.get_snapshot()["risk_filters"]

    assert filters["circuit_flagged_symbols"] == [
        {"symbol": "HFCL", "side": "LOWER", "gap_pct": 1.23},
    ]


def test_capital_is_none_without_a_portfolio():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.refresh()
    assert state.get_snapshot()["capital"] is None


def test_capital_present_when_portfolio_wired_in():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(
        _FakeEngine(), _FakeMarketData(), loader, portfolio=_FakePortfolio()
    )
    state.refresh()
    assert state.get_snapshot()["capital"] == {"available_capital": 999.0}


def test_snapshot_is_not_ready_before_the_first_refresh():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    assert state.get_snapshot() == {"ready": False}


# -- V2 additions: RR, performance, sector heatmap, news feed,
#    system health, opportunity queue --

def test_rr_computed_from_initial_stop_on_an_open_long():
    loader = _loader({"TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 110.0})
    engine = _FakeEngine(open_positions={
        "TCS": {
            "entry_price": 100.0, "qty": 10, "initial_stop": 95.0,
            "entry_time": datetime(2026, 7, 23, 9, 31, 30),
            "entry_reason": "STRUCTURAL_LONG_BREAKOUT",
        }
    })
    state = DashboardState(engine, market_data, loader)
    state.refresh()
    row = state.get_snapshot()["open_positions"][0]

    # risk = 100-95 = 5, reward = 110-100 = 10 -> RR = 2.0
    assert row["initial_stop"] == 95.0
    assert row["rr"] == 2.0


def test_rr_computed_from_initial_stop_on_an_open_short():
    loader = _loader({"TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 90.0})
    engine = _FakeEngine(open_positions={
        "TCS": {
            "entry_price": 100.0, "qty": 10, "direction": "SHORT",
            "initial_stop": 105.0,
            "entry_time": datetime(2026, 7, 23, 9, 31, 30),
            "entry_reason": "STRUCTURAL_SHORT_BREAKDOWN",
        }
    })
    state = DashboardState(engine, market_data, loader)
    state.refresh()
    row = state.get_snapshot()["open_positions"][0]

    # risk = 105-100 = 5, reward = 100-90 = 10 -> RR = 2.0
    assert row["rr"] == 2.0


def test_rr_is_none_when_initial_stop_is_missing():
    """Positions restored from a pre-RR-tracking snapshot -- must
    never guess a risk figure that was never actually recorded."""
    loader = _loader({"TCS": "IT"})
    market_data = _FakeMarketData(latest_prices={"TCS": 110.0})
    engine = _FakeEngine(open_positions={
        "TCS": {
            "entry_price": 100.0, "qty": 10,
            "entry_time": datetime(2026, 7, 23, 9, 31, 30),
            "entry_reason": "STRUCTURAL_LONG_BREAKOUT",
        }
    })
    state = DashboardState(engine, market_data, loader)
    state.refresh()
    row = state.get_snapshot()["open_positions"][0]

    assert row["initial_stop"] is None
    assert row["rr"] is None


def test_rr_on_a_closed_trade_uses_exit_price_not_last_price():
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(closed_positions=[{
        "symbol": "TCS", "qty": 10, "entry_price": 100.0, "exit_price": 115.0,
        "initial_stop": 90.0, "direction": "LONG",
        "entry_time": None, "exit_time": None,
        "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "exit_reason": "TRAILING_STOP",
        "holding_seconds": None, "pnl": 150.0,
    }])
    state = DashboardState(engine, _FakeMarketData(), loader)
    state.refresh()
    row = state.get_snapshot()["closed_positions"][0]

    # risk = 100-90 = 10, reward = 115-100 = 15 -> RR = 1.5
    assert row["rr"] == 1.5


def test_performance_is_all_zero_none_with_no_closed_trades():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.refresh()
    perf = state.get_snapshot()["performance"]

    assert perf["total_trades"] == 0
    assert perf["win_rate_pct"] is None
    assert perf["profit_factor"] is None
    assert perf["max_drawdown"] == 0.0


def _closed(pnl, symbol="TCS"):
    return {
        "symbol": symbol, "qty": 10, "entry_price": 100.0, "exit_price": 100.0,
        "direction": "LONG", "entry_time": None, "exit_time": None,
        "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "exit_reason": "TRAILING_STOP",
        "holding_seconds": None, "pnl": pnl,
    }


def test_performance_win_rate_profit_factor_and_averages():
    loader = _loader({"TCS": "IT"})
    engine = _FakeEngine(closed_positions=[
        _closed(100.0), _closed(-50.0), _closed(30.0),
    ])
    state = DashboardState(engine, _FakeMarketData(), loader)
    state.refresh()
    perf = state.get_snapshot()["performance"]

    assert perf["total_trades"] == 3
    assert perf["wins"] == 2
    assert perf["losses"] == 1
    assert perf["win_rate_pct"] == round(2 / 3 * 100, 1)
    assert perf["gross_profit"] == 130.0
    assert perf["gross_loss"] == 50.0
    assert perf["profit_factor"] == round(130.0 / 50.0, 2)
    assert perf["avg_win"] == 65.0
    assert perf["avg_loss"] == 50.0
    assert perf["net_pnl"] == 80.0


def test_performance_max_drawdown_from_the_realized_equity_sequence():
    loader = _loader({"TCS": "IT"})
    # Sequence: +100 (peak 100) -> -50 (drawdown 50) -> +30 (still down 20)
    engine = _FakeEngine(closed_positions=[
        _closed(100.0), _closed(-50.0), _closed(30.0),
    ])
    state = DashboardState(engine, _FakeMarketData(), loader)
    state.refresh()
    perf = state.get_snapshot()["performance"]

    assert perf["max_drawdown"] == 50.0


def test_sector_gainers_losers_ranked_by_avg_change_pct_vs_prev_close():
    """Replaces the old day-open-based sectors.heatmap (2026-07-23
    evening, operator: "instead of deleting the sector heatmap, make
    it use like same top 50 gainers & losers... top gaining sectors
    / top loosing sectors") -- same PREV-CLOSE basis as the stock
    table, aggregated by SECTOR from the same snapshot rows."""
    loader = _loader({"TCS": "IT", "INFY": "IT", "WIPRO": "IT", "SBIN": "BANK", "HDFC": "BANK", "ICICI": "BANK"})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(110.0, 100.0, 111.0, 99.0, 100.0, 1000),    # +10%
        "INFY": _quote(105.0, 100.0, 106.0, 99.0, 100.0, 1000),   # +5%
        "WIPRO": _quote(103.0, 100.0, 104.0, 99.0, 100.0, 1000),  # +3% -> IT avg = 6.0
        "SBIN": _quote(95.0, 100.0, 96.0, 94.0, 100.0, 1000),     # -5%
        "HDFC": _quote(90.0, 100.0, 91.0, 89.0, 100.0, 1000),     # -10%
        "ICICI": _quote(97.0, 100.0, 98.0, 96.0, 100.0, 1000),    # -3% -> BANK avg = -6.0
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    assert [r["sector"] for r in gl["sector_gainers"]] == ["IT"]
    assert gl["sector_gainers"][0]["avg_change_pct"] == 6.0
    assert gl["sector_gainers"][0]["symbol_count"] == 3
    assert gl["sector_gainers"][0]["s_no"] == 1
    assert [r["sector"] for r in gl["sector_losers"]] == ["BANK"]
    assert gl["sector_losers"][0]["avg_change_pct"] == -6.0


def test_sector_heatmap_caps_at_top_10_each_side():
    """2026-07-24 revamp: only the top 10 gaining + top 10 losing
    sectors are shown (config.SECTOR_HEATMAP_TOP_N), not all ~29.
    Build 13 gaining + 13 losing sectors (3 stocks each) and assert
    each side is capped at 10."""
    loader_map = {}
    quotes = {}
    # 13 gaining sectors G0..G12, each 3 stocks, +1..+13 %
    for i in range(13):
        pct = i + 1
        ltp = 100.0 + pct
        for j in range(3):
            sym = f"G{i}_{j}"
            loader_map[sym] = f"GSEC{i}"
            quotes[sym] = _quote(ltp, 100.0, ltp + 1, 99.0, 100.0, 1000)
    # 13 losing sectors L0..L12, each 3 stocks, -1..-13 %
    for i in range(13):
        pct = i + 1
        ltp = 100.0 - pct
        for j in range(3):
            sym = f"L{i}_{j}"
            loader_map[sym] = f"LSEC{i}"
            quotes[sym] = _quote(ltp, 100.0, ltp + 0.5, ltp - 0.5, 100.0, 1000)

    loader = _loader(loader_map)
    engine = _FakeEngine(circuit_snapshot=quotes)
    state = DashboardState(engine, _FakeMarketData(), loader)
    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    assert len(gl["sector_gainers"]) == 10
    assert len(gl["sector_losers"]) == 10
    # top gainer is the strongest sector (+13%), ranked s_no 1
    assert gl["sector_gainers"][0]["avg_change_pct"] == 13.0
    assert gl["sector_gainers"][0]["s_no"] == 1


def test_sector_gainers_losers_drops_sectors_below_min_symbols():
    """Below config.SECTOR_GAINERS_LOSERS_MIN_SYMBOLS (3) -- dropped
    as too sparse to mean anything, same reasoning as the old
    INDUSTRY_HEATMAP_MIN_SYMBOLS this replaces."""
    loader = _loader({"TCS": "IT", "INFY": "IT", "SBIN": "BANK"})
    engine = _FakeEngine(circuit_snapshot={
        "TCS": _quote(110.0, 100.0, 111.0, 99.0, 100.0, 1000),
        "INFY": _quote(105.0, 100.0, 106.0, 99.0, 100.0, 1000),
        "SBIN": _quote(95.0, 100.0, 96.0, 94.0, 100.0, 1000),  # only 1 BANK symbol
    })
    state = DashboardState(engine, _FakeMarketData(), loader)

    state.refresh()
    gl = state.get_snapshot()["gainers_losers"]

    sectors_seen = {r["sector"] for r in gl["sector_gainers"]} | {r["sector"] for r in gl["sector_losers"]}
    assert "BANK" not in sectors_seen
    assert "IT" not in sectors_seen  # only 2 IT symbols too, also below threshold


# (Momentum Universe dashboard panel removed 2026-07-24 evening -- the
# frozen 9:30 shortlist is gone from the engine, so the dashboard no
# longer surfaces it. Its three panel tests were removed with it.)


def test_open_position_carries_fixed_target_when_present():
    loader = _loader({"TCS": "IT"})
    open_positions = {
        "TCS": {
            "security_id": "1", "qty": 100, "entry_price": 100.0,
            "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "entry_time": None,
            "direction": "LONG", "initial_stop": 90.0, "fixed_target": 125.0,
        }
    }
    market_data = _FakeMarketData(latest_prices={"TCS": 110.0})
    state = DashboardState(_FakeEngine(open_positions=open_positions), market_data, loader)
    state.refresh()
    row = state.get_snapshot()["open_positions"][0]
    assert row["fixed_target"] == 125.0
    # Fixed-bracket trade -- "stop" mirrors the unchanging initial_stop,
    # not a live trailing_stop.get_stop() lookup (which would be None
    # here since trailing_stop.start() is never called for these).
    assert row["stop"] == 90.0


def test_open_position_without_fixed_target_still_uses_live_trailing_stop():
    loader = _loader({"TCS": "IT"})
    open_positions = {
        "TCS": {
            "security_id": "1", "qty": 100, "entry_price": 100.0,
            "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "entry_time": None,
            "direction": "LONG", "initial_stop": 90.0, "fixed_target": None,
        }
    }
    market_data = _FakeMarketData(latest_prices={"TCS": 110.0})
    state = DashboardState(
        _FakeEngine(open_positions=open_positions, stops={"TCS": 95.0}),
        market_data, loader,
    )
    state.refresh()
    row = state.get_snapshot()["open_positions"][0]
    assert row["fixed_target"] is None
    assert row["stop"] == 95.0  # live trailing stop, not initial_stop


def test_open_position_with_atr_trailing_uses_its_own_live_stop_field():
    """2026-07-24 ATR redesign: an ATR_TRAILING position has
    fixed_target=None (same as a swing-trailing position) but is
    NEVER registered with the swing engine's trailing_stop -- its
    live stop lives on the position dict itself ("atr_stop"). Must
    NOT fall through to trailing_stop.get_stop() (which would
    silently return None/stale for these)."""
    loader = _loader({"TCS": "IT"})
    open_positions = {
        "TCS": {
            "security_id": "1", "qty": 121, "entry_price": 112.0,
            "entry_reason": "STRUCTURAL_LONG_BREAKOUT", "entry_time": None,
            "direction": "LONG", "initial_stop": 103.75, "fixed_target": None,
            "stop_mode": "ATR_TRAILING", "atr_stop": 106.5, "atr_extreme": 115.0,
        }
    }
    market_data = _FakeMarketData(latest_prices={"TCS": 114.0})
    state = DashboardState(
        # No "TCS" entry in stops -- proves the swing engine is
        # never consulted for this position.
        _FakeEngine(open_positions=open_positions, stops={}),
        market_data, loader,
    )
    state.refresh()
    row = state.get_snapshot()["open_positions"][0]
    assert row["fixed_target"] is None
    assert row["stop"] == 106.5


def test_system_health_reports_tick_count_staleness_and_universe_size():
    loader = _loader({"TCS": "IT", "INFY": "IT"})
    market_data = _FakeMarketData(tick_count=12345, stale_warning_count=3)
    state = DashboardState(_FakeEngine(), market_data, loader)
    state.refresh()
    health = state.get_snapshot()["system_health"]

    assert health["tick_count"] == 12345
    assert health["stale_symbols_flagged"] == 3
    assert health["universe_size"] == 2


def test_system_health_feed_alive_from_the_wired_callable():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(
        _FakeEngine(), _FakeMarketData(), loader, get_feed_alive=lambda: True
    )
    state.refresh()
    assert state.get_snapshot()["system_health"]["feed_alive"] is True


def test_system_health_feed_alive_is_none_when_not_wired():
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.refresh()
    assert state.get_snapshot()["system_health"]["feed_alive"] is None


# Opportunity Queue removed 2026-07-23 evening (operator: "DELETE -
# Opportunity Queue — approaching ORB boundary") -- its two tests
# (proximity ranking, excludes symbols with an open position) went
# with it, along with dashboard/state.py's _build_opportunity_queue().


# ==================================================
# DAILY TREND PANEL  (2026-07-26)
# ==================================================
# Read-only panel over core/daily_store.py + core/trend_structure.py.
# The tests that matter are the fail-open ones: the daily store is
# OPTIONAL, and a machine that never ran build_daily_history.py must
# still trade.

def _daily_state(tmp_path, symbols, bars, open_positions=None):
    """A DashboardState wired to a real (temp) DailyStore."""
    from core.daily_store import DailyStore
    store = DailyStore(url=f"sqlite:///{tmp_path}/daily.db")
    store.upsert_many(bars)
    loader = _loader({s: "IT" for s in symbols})
    engine = _FakeEngine(open_positions=open_positions or {})
    state = DashboardState(engine, _FakeMarketData(), loader)
    state._daily_store = store
    return state


def _daily_bar(date, symbol, high, low):
    return dict(date=date, symbol=symbol, series="EQ", open=low, high=high,
                low=low, close=(high + low) / 2, prev_close=None,
                volume=1000.0, turnover=None)


def _up_bars(symbol="PARAS", n=8):
    return [_daily_bar(f"2026-07-{14 + i:02d}", symbol, 100 + i * 2,
                       95 + i * 2) for i in range(n)]


def _down_bars(symbol="FALLER", n=8):
    return [_daily_bar(f"2026-07-{14 + i:02d}", symbol, 100 - i * 2,
                       95 - i * 2) for i in range(n)]


def _position(direction="LONG"):
    return {"direction": direction, "entry_price": 100.0, "qty": 10,
            "entry_time": datetime(2026, 7, 24, 10, 5),
            "initial_stop": 98.0}


def test_daily_trend_counts_the_universe_by_structure(tmp_path):
    state = _daily_state(tmp_path, ["PARAS", "FALLER"],
                         _up_bars() + _down_bars())
    dt = state._build_daily_trend({})
    assert dt["available"] is True
    assert dt["counts"]["STRONG_UP"] == 1
    assert dt["counts"]["STRONG_DOWN"] == 1
    assert dt["as_of"] == "2026-07-21"


def test_daily_trend_marks_a_long_in_an_uptrend_as_agreeing(tmp_path):
    state = _daily_state(tmp_path, ["PARAS"], _up_bars(),
                         open_positions={"PARAS": _position("LONG")})
    row = state._build_daily_trend(
        {"PARAS": _position("LONG")})["positions"][0]
    assert row["symbol"] == "PARAS"
    assert row["structure"] == "STRONG_UP"
    assert row["alignment"] == "AGREES"


def test_daily_trend_marks_a_long_in_a_downtrend_as_against(tmp_path):
    """AGAINST is a LABEL, not a verdict -- an ORB long out of a broken
    downtrend is exactly the reversal setup the operator wants."""
    state = _daily_state(tmp_path, ["FALLER"], _down_bars())
    row = state._build_daily_trend(
        {"FALLER": _position("LONG")})["positions"][0]
    assert row["alignment"] == "AGAINST"


def test_daily_trend_marks_a_short_in_a_downtrend_as_agreeing(tmp_path):
    state = _daily_state(tmp_path, ["FALLER"], _down_bars())
    row = state._build_daily_trend(
        {"FALLER": _position("SHORT")})["positions"][0]
    assert row["alignment"] == "AGREES"


def test_daily_trend_puts_against_trend_positions_first(tmp_path):
    state = _daily_state(tmp_path, ["PARAS", "FALLER"],
                         _up_bars() + _down_bars())
    rows = state._build_daily_trend({
        "PARAS": _position("LONG"),        # agrees
        "FALLER": _position("LONG"),       # against
    })["positions"]
    assert rows[0]["symbol"] == "FALLER"


def test_daily_trend_handles_a_position_with_no_history(tmp_path):
    state = _daily_state(tmp_path, ["PARAS"], _up_bars())
    rows = state._build_daily_trend(
        {"GHOST": _position("LONG")})["positions"]
    assert rows[0]["structure"] == "UNKNOWN"
    assert rows[0]["alignment"] is None


def test_daily_trend_lists_broken_structures(tmp_path):
    """The operator's own case: stops making higher highs, then takes
    out the previous day's low."""
    bars = _up_bars("PARAS", n=7)
    bars.append(_daily_bar("2026-07-21", "PARAS", high=105, low=80))
    state = _daily_state(tmp_path, ["PARAS"], bars)
    dt = state._build_daily_trend({})
    assert dt["broke_total"] == 1
    assert dt["broke"][0]["symbol"] == "PARAS"
    assert dt["broke"][0]["broke"] == "UP"


def test_daily_trend_is_absent_without_a_store(tmp_path):
    """No daily_candles.db must cost the PANEL, not the session."""
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state._daily_store = False           # simulates a failed open
    dt = state._build_daily_trend({})
    assert dt["available"] is False
    assert "build_daily_history" in dt["reason"]


def test_daily_trend_is_absent_with_too_little_history(tmp_path):
    state = _daily_state(tmp_path, ["PARAS"],
                         [_daily_bar("2026-07-20", "PARAS", 100, 95)])
    dt = state._build_daily_trend({})
    assert dt["available"] is False
    assert "history" in dt["reason"]


def test_daily_trend_survives_a_broken_store(tmp_path):
    class _Boom:
        def stats(self):
            raise RuntimeError("db is corrupt")

    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state._daily_store = _Boom()
    dt = state._build_daily_trend({})
    assert dt["available"] is False


def test_daily_trend_is_cached_but_positions_stay_live(tmp_path):
    """The structure can't change until tomorrow's bhavcopy, but the
    open book changes all session -- so the cache must not freeze it."""
    state = _daily_state(tmp_path, ["PARAS"], _up_bars())
    first = state._build_daily_trend({})
    assert first["positions"] == []

    state._daily_store = None            # any recompute would now fail
    second = state._build_daily_trend({"PARAS": _position("LONG")})
    assert second["available"] is True                    # served cached
    assert second["positions"][0]["symbol"] == "PARAS"    # but re-mapped


def test_daily_trend_appears_in_the_snapshot(tmp_path):
    state = _daily_state(tmp_path, ["PARAS"], _up_bars())
    state.refresh()
    assert "daily_trend" in state.get_snapshot()


def test_daily_trend_can_be_switched_off(tmp_path, monkeypatch):
    import dashboard.state as state_module
    monkeypatch.setattr(state_module, "DAILY_TREND_PANEL_ENABLED", False)
    state = _daily_state(tmp_path, ["PARAS"], _up_bars())
    dt = state._build_daily_trend({})
    assert dt["available"] is False
    assert dt["reason"] == "disabled in config"


def test_daily_trend_never_gates_anything(tmp_path):
    """The panel is observation only. If this ever fails, someone wired
    the structure into a trading decision -- read
    core/trend_structure.py's 'WHY THIS IS NOT WIRED AS AN ENTRY GATE'
    before deciding that was right."""
    import inspect
    import core.engine as engine_module
    source = inspect.getsource(engine_module)
    assert "trend_structure" not in source
    assert "daily_trend" not in source


# -- inline trend badge next to every stock name (2026-07-26) --
# Operator: "i asked to display the trend of the stock (upward, down,
# neutral) next to stock name". The browser needs a label for ANY
# symbol it prints -- open positions, top 50 gainers/losers, closed
# trades, blocked names -- so the snapshot carries a compact map.

def test_snapshot_carries_a_compact_label_map_for_every_symbol(tmp_path):
    state = _daily_state(tmp_path, ["PARAS", "FALLER"],
                         _up_bars() + _down_bars())
    dt = state._build_daily_trend({})
    assert dt["labels"] == {"PARAS": "STRONG_UP", "FALLER": "STRONG_DOWN"}


def test_the_full_records_are_not_sent_over_the_wire(tmp_path):
    """544 full records every second is ~10x the bytes for information
    the browser only uses to pick an arrow."""
    state = _daily_state(tmp_path, ["PARAS"], _up_bars())
    assert "by_symbol" not in state._build_daily_trend({})


def test_broke_map_only_carries_names_that_actually_broke(tmp_path):
    bars = _up_bars("PARAS", n=7)
    bars.append(_daily_bar("2026-07-21", "PARAS", high=105, low=80))
    state = _daily_state(tmp_path, ["PARAS", "FALLER"],
                         bars + _down_bars())
    dt = state._build_daily_trend({})
    assert dt["broke_map"] == {"PARAS": "UP"}


def test_label_map_survives_the_cache(tmp_path):
    """The badge must keep working on cached refreshes -- i.e. all but
    one refresh in every 15 minutes."""
    state = _daily_state(tmp_path, ["PARAS"], _up_bars())
    state._build_daily_trend({})
    state._daily_store = None            # any recompute would fail
    assert state._build_daily_trend({})["labels"] == {"PARAS": "STRONG_UP"}


def test_no_label_map_when_the_panel_is_unavailable(tmp_path):
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state._daily_store = False
    dt = state._build_daily_trend({})
    assert "labels" not in dt          # JS falls back to no badge


# ==================================================
# SEATS / RS / ORB / ROTATION  (2026-07-26)
# ==================================================
# POST_MONDAY_TODO F asked for peak concurrency and could not answer
# it. All four of these surface data the engine already computes and
# discards -- none of it is new instrumentation, and none of it gates.

from dashboard.state import _is_rotation, _orb_fields, _peak_concurrency


def _ctrade(symbol, entry_h, entry_m, exit_h, exit_m, reason="TARGET",
            rel_strength=None):
    return {"symbol": symbol, "direction": "LONG", "qty": 10,
            "entry_price": 100.0, "exit_price": 101.0,
            "entry_time": datetime(2026, 7, 27, entry_h, entry_m),
            "exit_time": datetime(2026, 7, 27, exit_h, exit_m),
            "exit_reason": reason, "entry_reason": "ORB",
            "initial_stop": 98.0, "pnl": 10.0,
            "rel_strength": rel_strength}


# -- peak concurrency: an interval sweep, not a running counter -----

def test_peak_concurrency_finds_the_true_overlap():
    """Three trades that overlap two-at-a-time must report 2, not 3."""
    closed = [_ctrade("A", 9, 30, 10, 0),
              _ctrade("B", 9, 45, 10, 30),     # overlaps A
              _ctrade("C", 11, 0, 11, 30)]     # alone
    peak, at, _when = _peak_concurrency({}, closed)
    assert peak == 2
    assert at == "09:45:00"


def test_peak_concurrency_counts_still_open_positions():
    closed = [_ctrade("A", 9, 30, 15, 0)]
    open_pos = {"B": {"entry_time": datetime(2026, 7, 27, 10, 0)},
                "C": {"entry_time": datetime(2026, 7, 27, 10, 5)}}
    peak, _, _when = _peak_concurrency(open_pos, closed)
    assert peak == 3


def test_a_seat_freed_and_refilled_in_the_same_second_is_not_doubled():
    """Exits are applied before entries at the same instant."""
    same = datetime(2026, 7, 27, 10, 0)
    closed = [{"entry_time": datetime(2026, 7, 27, 9, 30), "exit_time": same},
              {"entry_time": same, "exit_time": datetime(2026, 7, 27, 11, 0)}]
    peak, _, _when = _peak_concurrency({}, closed)
    assert peak == 1


def test_peak_concurrency_without_timestamps_is_none_not_a_guess():
    assert _peak_concurrency({}, []) == (None, None, None)


def test_peak_concurrency_ignores_unusable_timestamps():
    closed = [{"entry_time": "not a datetime", "exit_time": None}]
    peak, _, _when = _peak_concurrency({}, closed)
    assert peak in (None, 0)


# -- the seats panel -------------------------------------------------

def test_seats_reports_holding_cap_and_peak():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine(open_positions={"A": _position()})
    engine.enable_staged_entry = True
    engine._staged_position_cap = lambda when: 6
    state = DashboardState(engine, _FakeMarketData(), loader)
    seats = state._build_seats({"A": _position()},
                               [_ctrade("B", 9, 30, 9, 45)])
    assert seats["holding"] == 1
    assert seats["cap"] == 6
    assert seats["max_seats"] == 10
    assert seats["peak_today"] == 2


def test_seats_says_the_cap_is_binding_when_the_book_filled():
    """The whole question: is the staged cap what stopped the next
    entry, or the gates upstream?"""
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine._staged_position_cap = lambda when: 3
    state = DashboardState(engine, _FakeMarketData(), loader)
    closed = [_ctrade("A", 9, 30, 11, 0), _ctrade("B", 9, 31, 11, 0),
              _ctrade("C", 9, 32, 11, 0)]
    assert state._build_seats({}, closed)["cap_is_binding"] is True


def test_seats_says_the_gates_are_the_limit_when_it_never_filled():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine._staged_position_cap = lambda when: 10
    state = DashboardState(engine, _FakeMarketData(), loader)
    seats = state._build_seats({}, [_ctrade("A", 9, 30, 11, 0)])
    assert seats["cap_is_binding"] is False


def test_seats_fails_open_when_the_cap_cannot_be_read():
    """A missing engine internal must cost a field, not the session."""
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine._staged_position_cap = lambda when: 1 / 0
    state = DashboardState(engine, _FakeMarketData(), loader)
    seats = state._build_seats({}, [])
    assert seats["cap"] is None
    assert seats["cap_is_binding"] is False


def test_seats_counts_rotations(tmp_path):
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine._staged_position_cap = lambda when: 10
    state = DashboardState(engine, _FakeMarketData(), loader)
    closed = [_ctrade("A", 9, 30, 10, 0, reason="ROTATED_OUT"),
              _ctrade("B", 9, 31, 10, 1, reason="TARGET")]
    assert state._build_seats({}, closed)["rotations_today"] == 1


def test_seats_appears_in_the_snapshot():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine._staged_position_cap = lambda when: 10
    state = DashboardState(engine, _FakeMarketData(), loader)
    state.refresh()
    assert "seats" in state.get_snapshot()


# -- rotation detection ----------------------------------------------

def test_rotation_is_matched_loosely():
    """The exact string has changed once already."""
    assert _is_rotation("ROTATED_OUT") is True
    assert _is_rotation("rotation") is True
    assert _is_rotation("ROTATE") is True
    assert _is_rotation("TARGET") is False
    assert _is_rotation(None) is False


# -- ORB fields ------------------------------------------------------

def test_orb_fields_measure_the_breakout_for_a_long():
    out = _orb_fields((110.0, 100.0), entry_price=111.0, direction="LONG")
    assert out["orb_high"] == 110.0
    assert out["orb_low"] == 100.0
    assert out["orb_width_pct"] == 10.0
    assert out["breakout_pct"] == pytest.approx(0.91, abs=0.01)


def test_orb_fields_measure_the_breakout_for_a_short():
    """A short breaks the range LOW, so the margin is measured there."""
    out = _orb_fields((110.0, 100.0), entry_price=99.0, direction="SHORT")
    assert out["breakout_pct"] == pytest.approx(1.0, abs=0.01)


def test_orb_fields_flag_a_paper_thin_breakout():
    """SONACOMS cleared a Rs 734 high by Rs 1.50 on 2026-07-24."""
    out = _orb_fields((734.0, 720.0), entry_price=735.5, direction="LONG")
    assert out["breakout_pct"] == pytest.approx(0.20, abs=0.01)


def test_orb_fields_are_all_none_without_a_range():
    out = _orb_fields(None, 100.0, "LONG")
    assert set(out.values()) == {None}


def test_orb_range_reads_the_engines_own_state():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine(orb_ranges={"A": {"high": 110.0, "low": 100.0}})
    state = DashboardState(engine, _FakeMarketData(), loader)
    assert state._orb_range("A") == (110.0, 100.0)


def test_orb_range_is_none_for_an_incomplete_range():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine(orb_ranges={"A": {"high": 110.0}})
    state = DashboardState(engine, _FakeMarketData(), loader)
    assert state._orb_range("A") is None


def test_orb_range_fails_open_on_a_broken_engine():
    class _Boom:
        def export_state(self):
            raise RuntimeError("nope")
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine.orb_engine = _Boom()
    state = DashboardState(engine, _FakeMarketData(), loader)
    assert state._orb_range("A") is None


# -- relative strength reaches the tables ----------------------------

def test_rel_strength_is_carried_on_open_positions():
    """The ONE input with measured evidence -- 14.5% -> 39% win rate
    across its quintiles -- and it was displayed nowhere until now."""
    loader = _loader({"A": "IT"})
    pos = dict(_position(), rel_strength=1.234)
    engine = _FakeEngine(open_positions={"A": pos},
                         orb_ranges={"A": {"high": 110.0, "low": 100.0}})
    state = DashboardState(engine, _FakeMarketData(latest_prices={"A": 111.0}),
                           loader)
    row = state._build_open_positions({"A": pos})[0]
    assert row["rel_strength"] == 1.23
    assert row["orb_high"] == 110.0
    assert row["breakout_pct"] is not None


def test_rel_strength_is_none_on_a_position_that_predates_the_field():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine(open_positions={"A": _position()})
    state = DashboardState(engine, _FakeMarketData(), loader)
    assert state._build_open_positions({"A": _position()})[0]["rel_strength"] \
        is None


def test_closed_trades_carry_rel_strength_and_the_rotation_flag():
    loader = _loader({"A": "IT", "B": "IT"})
    closed = [_ctrade("A", 9, 30, 10, 0, reason="ROTATED_OUT",
                      rel_strength=2.5),
              _ctrade("B", 9, 31, 10, 1, reason="TARGET")]
    engine = _FakeEngine(closed_positions=closed)
    state = DashboardState(engine, _FakeMarketData(), loader)
    rows = {r["symbol"]: r for r in state._build_closed_positions(closed)}
    assert rows["A"]["rel_strength"] == 2.5
    assert rows["A"]["rotated_out"] is True
    assert rows["B"]["rotated_out"] is False


# ==================================================
# GATE FUNNEL PANEL  (2026-07-26)
# ==================================================
# Pure passthrough of core/gate_log.py. It is a diagnostic, so the
# tests that matter are the ones proving it cannot take the dashboard
# down with it.

def _gate_snapshot(**over):
    base = {
        "day": "2026-07-27",
        "summary": {"candidates": 10, "entries": 2, "rejected": 8,
                    "biggest_filter": "RS_BAND", "biggest_filter_died": 5},
        "funnel": [
            {"gate": "REGIME", "help": "market regime forbids this",
             "died": 0, "survived": 10, "events": 0},
            {"gate": "RS_BAND", "help": "relative strength outside band",
             "died": 5, "survived": 5, "events": 300},
            {"gate": "SECTOR", "help": "sector not leading",
             "died": 3, "survived": 2, "events": 12},
        ],
        "near_misses": [{"symbol": "PARAS", "direction": "LONG",
                         "gate": "VOLUME", "detail": "0.6x average",
                         "at": "10:02:00"}],
    }
    base.update(over)
    return base


def _funnel_state(snapshot):
    loader = _loader({"PARAS": "IT"})
    engine = _FakeEngine()
    engine.get_gate_log = lambda: snapshot
    return DashboardState(engine, _FakeMarketData(), loader)


def test_gate_funnel_passes_the_engine_log_through():
    gf = _funnel_state(_gate_snapshot())._build_gate_funnel()
    assert gf["available"] is True
    assert gf["summary"]["candidates"] == 10
    assert gf["near_misses"][0]["symbol"] == "PARAS"


def test_gates_that_never_fired_are_not_shown():
    """Seventeen rows of zeroes is noise, not information."""
    gf = _funnel_state(_gate_snapshot())._build_gate_funnel()
    assert [r["gate"] for r in gf["funnel"]] == ["RS_BAND", "SECTOR"]


def test_died_pct_is_relative_to_all_candidates():
    gf = _funnel_state(_gate_snapshot())._build_gate_funnel()
    rows = {r["gate"]: r for r in gf["funnel"]}
    assert rows["RS_BAND"]["died_pct"] == 50.0
    assert rows["SECTOR"]["died_pct"] == 30.0


def test_died_pct_does_not_divide_by_zero():
    snap = _gate_snapshot(summary={"candidates": 0, "entries": 0,
                                   "rejected": 0, "biggest_filter": None,
                                   "biggest_filter_died": 0})
    gf = _funnel_state(snap)._build_gate_funnel()
    assert all(r["died_pct"] == 0.0 for r in gf["funnel"])


def test_gate_funnel_is_unavailable_before_anything_happens():
    gf = _funnel_state({"day": None, "summary": {}, "funnel": [],
                        "near_misses": []})._build_gate_funnel()
    assert gf["available"] is False


def test_gate_funnel_survives_an_engine_without_the_method():
    """An engine restored from an older build has no get_gate_log."""
    loader = _loader({"A": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    assert state._build_gate_funnel()["available"] is False


def test_gate_funnel_survives_a_raising_engine():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()

    def boom():
        raise RuntimeError("nope")
    engine.get_gate_log = boom
    state = DashboardState(engine, _FakeMarketData(), loader)
    assert state._build_gate_funnel()["available"] is False


def test_gate_funnel_states_what_a_candidate_means():
    """The top-of-funnel number is the easy one to misread: 40
    candidates out of 545 names does NOT mean 505 were rejected."""
    gf = _funnel_state(_gate_snapshot())._build_gate_funnel()
    assert "fresh ORB cross" in gf["note"]


def test_gate_funnel_appears_in_the_snapshot():
    state = _funnel_state(_gate_snapshot())
    state.refresh()
    assert "gate_funnel" in state.get_snapshot()


def test_binding_is_measured_against_the_cap_AT_THE_PEAK():
    """Caught while previewing this panel. The staged cap ramps
    3 -> 6 -> 10 through the morning and drops to 0 after 15:00, so
    measuring a 09:40 peak of 3 against the CURRENT cap reported 'not
    binding' every single afternoon -- the exact opposite of the
    truth."""
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()

    def cap_at(when):
        return 3 if when.hour < 10 else 0        # 0 = past no-entry time
    engine._staged_position_cap = cap_at

    state = DashboardState(engine, _FakeMarketData(), loader)
    state._clock = lambda: datetime(2026, 7, 27, 16, 0)   # evening
    closed = [_ctrade("A", 9, 30, 11, 0), _ctrade("B", 9, 31, 11, 0),
              _ctrade("C", 9, 32, 11, 0)]
    seats = state._build_seats({}, closed)
    assert seats["peak_today"] == 3
    assert seats["cap"] == 0                     # correct for right now
    assert seats["cap_is_binding"] is True       # correct for the peak


def test_binding_is_false_when_the_book_never_filled_its_cap():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    engine._staged_position_cap = lambda when: 10
    state = DashboardState(engine, _FakeMarketData(), loader)
    seats = state._build_seats({}, [_ctrade("A", 9, 30, 11, 0)])
    assert seats["cap_is_binding"] is False


def test_the_clock_is_injectable_for_the_demo_preview():
    loader = _loader({"A": "IT"})
    engine = _FakeEngine()
    seen = []
    engine._staged_position_cap = lambda when: seen.append(when) or 6
    state = DashboardState(engine, _FakeMarketData(), loader)
    state._clock = lambda: datetime(2026, 7, 27, 10, 30)
    state._build_seats({}, [])
    assert seen[0] == datetime(2026, 7, 27, 10, 30)


def test_demo_flag_reaches_the_snapshot():
    loader = _loader({"A": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader,
                           demo=True)
    state.refresh()
    assert state.get_snapshot()["demo"] is True


def test_demo_is_off_by_default():
    loader = _loader({"A": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.refresh()
    assert state.get_snapshot()["demo"] is False
