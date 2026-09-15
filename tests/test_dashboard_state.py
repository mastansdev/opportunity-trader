"""
Decision-correctness tests for dashboard/state.py. Uses fakes
for every input (engine, market_data, master_loader,
portfolio) so this stays fast and focused on the ASSEMBLY logic,
not re-testing what each real component already proves on its
own.
"""

from datetime import datetime

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


def test_gainers_losers_empty_when_no_circuit_monitor_and_no_stored_close(
        tmp_path):
    """---- THE CONTRACT CHANGED. 12 August 2026. ----

        "why dashboard is still showing empty ? it has todays complete
         data right?"

    It used to be "no circuit monitor -> empty table", full stop. After
    the close he restarted main.py, the REST poll stopped carrying a
    usable last price, and the board drew an empty table on top of a
    daily_candles.db holding today's complete session for 2,459
    symbols. So an empty live result now falls back to the stored
    close, labelled `at_close`.

    This test keeps the ORIGINAL guarantee for the case that is still
    genuinely empty: nothing live AND nothing stored. It points the
    fallback at a temp path -- the first run after the fallback shipped
    had this test reading the real database and getting 2,459 rows,
    which is how a unit test silently becomes a data test.
    """
    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.daily_candles_path = str(tmp_path / "no-such-store.db")
    state.refresh()

    gl = state.get_snapshot()["gainers_losers"]
    assert gl["gainers"] == []
    assert gl["losers"] == []
    assert gl.get("at_close") is False


def test_no_live_prices_falls_back_to_the_stored_close(tmp_path):
    """The other half of the same contract, and the thing he asked
    for: a complete session on disk must reach the screen."""
    import sqlite3

    db = tmp_path / "daily.db"
    conn = sqlite3.connect(str(db))
    conn.execute("create table daily_bars (id integer primary key, "
                 "date text, symbol text, open real, high real, low real, "
                 "close real, prev_close real, volume real)")
    conn.execute("insert into daily_bars (date, symbol, open, high, low, "
                 "close, prev_close, volume) values "
                 "('2026-08-12','TCS',100,127,99,126,100,5000)")
    conn.commit()
    conn.close()

    loader = _loader({"TCS": "IT"})
    state = DashboardState(_FakeEngine(), _FakeMarketData(), loader)
    state.daily_candles_path = str(db)
    state.refresh()

    gl = state.get_snapshot()["gainers_losers"]
    assert [r["symbol"] for r in gl["gainers"]] == ["TCS"]
    assert gl["at_close"] is True, (
        "the close is on screen without being labelled a close -- a "
        "stale price wearing a live one's clothes")
    assert gl["as_of"] == "2026-08-12"


class _FrozenClock:
    """The real `time` module with monotonic() standing still.

    ---- THE TEST RACED THE THING IT WAS TESTING. 21 Aug 2026 ----

    This failed two runs in three on the operator's machine. The
    throttle window is GAINERS_LOSERS_REFRESH_SECONDS = 30s, and a
    single DashboardState.refresh() takes 23-33s here -- it loads
    2,646 liquidity symbols and a 2,401-symbol shortlist reference.
    So on a loaded run the window expired BETWEEN the two refreshes
    and the rebuild it then did was correct behaviour.

    A test that fails because the machine is busy teaches the suite
    to be ignored, which is worse than the bug it was watching for.
    Nothing in the assertion ever needed real elapsed time: it is
    about the cache being reused INSIDE the window. So the window is
    now held open instead of raced.

    Everything except monotonic() is delegated, because state.py uses
    the module for other things and replacing it wholesale would
    break them silently.
    """

    def __init__(self, module, at):
        self._module = module
        self._at = at

    def __getattr__(self, name):
        return getattr(self._module, name)

    def monotonic(self):
        return self._at


def test_gainers_losers_throttled_not_rebuilt_every_refresh(monkeypatch):
    """Operator's own choice: 'for every 5 mins', not on every
    DashboardState.refresh() call -- config.GAINERS_LOSERS_REFRESH_SECONDS.
    A second refresh() immediately after the first must reuse the
    exact same cached result, even if the underlying snapshot data
    has since changed."""
    import time as _time

    import dashboard.state as _state
    monkeypatch.setattr(_state, "time",
                        _FrozenClock(_time, _time.monotonic()))

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


# ---------------------------------------------------------------
# ACTION LOG, server-side (2026-07-28).
#
# It lived in the browser first. The operator refreshed the page and the
# record vanished -- and he runs two or three screens, so a log only the
# clicking screen can see is not a record at all. He could click on one
# monitor, watch another, and never learn the click died.
# ---------------------------------------------------------------

def test_the_action_log_is_capped():
    """40 rows, so a long session cannot grow it without limit."""
    from trading.trade_controller import TradeController
    controller = TradeController()
    for i in range(200):
        controller.note_action(True, f"click {i}")
    assert len(controller.actions()) == TradeController.MAX_ACTIONS


def test_note_action_never_raises_on_junk():
    """Bookkeeping must not be able to break a trade request."""
    from trading.trade_controller import TradeController
    controller = TradeController()
    controller.note_action(None, None)
    controller.note_action(True, object())
    assert len(controller.actions()) == 2
