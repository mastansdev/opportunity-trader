"""
Tests for tools/structure_performance.py.

The one that matters is test_label_uses_only_bars_before_the_trade:
if the structure label can see the trade day's own bar, every result
this tool produces is lookahead-flattered and worthless.
"""

from datetime import datetime, timedelta

import pytest

from core.daily_store import DailyStore
from core.trade_memory import TradeMemory
from tools import structure_performance as sp


@pytest.fixture
def store(tmp_path):
    return DailyStore(url=f"sqlite:///{tmp_path}/daily.db")


@pytest.fixture
def memory(tmp_path):
    return TradeMemory(url=f"sqlite:///{tmp_path}/trades.db")


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(sp, "decision", lambda *a, **k: None)
    monkeypatch.setattr(sp, "warn", lambda *a, **k: None)


def bar(date, symbol, high, low, close=None):
    return dict(date=date, symbol=symbol, series="EQ", open=low,
                high=high, low=low, close=close if close is not None
                else (high + low) / 2, prev_close=None, volume=1000.0,
                turnover=None)


def staircase_up(symbol="PARAS", start_day=14, n=8):
    """Higher highs AND higher lows, every day."""
    return [bar(f"2026-07-{start_day + i:02d}", symbol,
                high=100 + i * 2, low=95 + i * 2)
            for i in range(n)]


def staircase_down(symbol="FALLER", start_day=14, n=8):
    return [bar(f"2026-07-{start_day + i:02d}", symbol,
                high=100 - i * 2, low=95 - i * 2)
            for i in range(n)]


# ----------------------------------------------------------
# the lookahead guard
# ----------------------------------------------------------

def test_previous_day_steps_back_one_calendar_day():
    assert sp.previous_day("2026-07-24") == "2026-07-23"
    assert sp.previous_day("2026-07-01") == "2026-06-30"


def test_previous_day_survives_garbage():
    assert sp.previous_day(None) is None
    assert sp.previous_day("not-a-date") is None


def test_label_uses_only_bars_before_the_trade(store):
    """THE test. A stock stepping up for 7 days that CRASHES on the
    trade day must still be labelled from the pre-trade bars -- the
    bot at 09:15 could not have known about the crash."""
    bars = staircase_up(n=7)                       # 07-14 .. 07-20
    bars.append(bar("2026-07-21", "PARAS", high=50, low=40))   # crash
    store.upsert_many(bars)

    result = sp.label_for(store, "PARAS", "2026-07-21")
    assert result["structure"] == "STRONG_UP"      # not RANGE
    assert result["broke_structure"] is None


def test_the_crash_day_does_change_the_label_for_the_NEXT_day(store):
    """Sanity check on the above: the same crash IS visible to a trade
    taken the following morning."""
    bars = staircase_up(n=7)
    bars.append(bar("2026-07-21", "PARAS", high=50, low=40))
    store.upsert_many(bars)
    result = sp.label_for(store, "PARAS", "2026-07-22")
    assert result["structure"] != "STRONG_UP"


def test_label_is_none_without_enough_history(store):
    store.upsert_many([bar("2026-07-20", "THIN", 100, 95)])
    assert sp.label_for(store, "THIN", "2026-07-21") is None


def test_label_is_none_for_an_unknown_symbol(store):
    store.upsert_many(staircase_up())
    assert sp.label_for(store, "NEVERHEARDOF", "2026-07-24") is None


# ----------------------------------------------------------
# alignment
# ----------------------------------------------------------

@pytest.mark.parametrize("direction,structure,expected", [
    ("LONG", "STRONG_UP", "WITH_TREND"),
    ("LONG", "UPTREND", "WITH_TREND"),
    ("SHORT", "STRONG_UP", "AGAINST_TREND"),
    ("SHORT", "DOWNTREND", "WITH_TREND"),
    ("SHORT", "STRONG_DOWN", "WITH_TREND"),
    ("LONG", "DOWNTREND", "AGAINST_TREND"),
    ("LONG", "RANGE", "RANGE"),
    ("SHORT", "RANGE", "RANGE"),
])
def test_alignment(direction, structure, expected):
    assert sp.alignment_of(direction, structure) == expected


# ----------------------------------------------------------
# bucketing
# ----------------------------------------------------------

def test_bucket_counts_wins_and_expectancy():
    trades = [dict(k="A", pnl=1000.0), dict(k="A", pnl=-500.0),
              dict(k="A", pnl=1000.0), dict(k="B", pnl=-200.0)]
    out = sp.bucket(trades, lambda t: t["k"])
    assert out["A"]["n"] == 3
    assert out["A"]["wins"] == 2
    assert out["A"]["win_rate"] == pytest.approx(66.67, abs=0.01)
    assert out["A"]["total_pnl"] == 1500.0
    assert out["B"]["n"] == 1


def test_bucket_skips_none_keys():
    out = sp.bucket([dict(k=None, pnl=1.0), dict(k="X", pnl=1.0)],
                    lambda t: t["k"])
    assert list(out) == ["X"]


def test_bucket_treats_a_missing_pnl_as_zero_not_a_win():
    out = sp.bucket([dict(k="X", pnl=None)], lambda t: t["k"])
    assert out["X"]["wins"] == 0
    assert out["X"]["total_pnl"] == 0.0


def test_avg_r_uses_the_configured_risk(monkeypatch):
    monkeypatch.setattr(sp, "RISK_PER_TRADE_RS", 800.0)
    out = sp.bucket([dict(k="X", pnl=400.0)], lambda t: t["k"])
    assert out["X"]["avg_r"] == pytest.approx(0.5)


# ----------------------------------------------------------
# end to end
# ----------------------------------------------------------

def record(memory, symbol, trade_date, direction, pnl):
    """TradeMemory derives trade_date from entry_time (see its
    record()), so the fixture has to supply a real datetime rather than
    a date string."""
    entry = datetime.fromisoformat(f"{trade_date}T10:05:00")
    memory.record(dict(
        symbol=symbol, direction=direction,
        entry_time=entry, exit_time=entry + timedelta(minutes=30),
        entry_price=100.0, exit_price=101.0, qty=10, pnl=pnl,
        exit_reason="TARGET" if pnl > 0 else "STOP",
        entry_reason="ORB", holding_seconds=1800, sector="IT",
        rel_strength=1.2, regime="LONG ONLY",
    ))


def test_run_labels_trades_and_reports(store, memory):
    store.upsert_many(staircase_up("PARAS"))
    store.upsert_many(staircase_down("FALLER"))
    record(memory, "PARAS", "2026-07-22", "LONG", 900.0)
    record(memory, "FALLER", "2026-07-22", "SHORT", 700.0)

    assert sp.run(min_trades=1, memory=memory, store=store) == 0


def test_run_is_an_error_with_no_trades(store, memory):
    store.upsert_many(staircase_up())
    assert sp.run(memory=memory, store=store) == 1


def test_run_is_an_error_without_daily_history(store, memory):
    record(memory, "PARAS", "2026-07-22", "LONG", 900.0)
    assert sp.run(memory=memory, store=store) == 1


def test_trades_with_no_prior_history_are_skipped_not_fatal(store, memory):
    store.upsert_many(staircase_up("PARAS"))
    record(memory, "PARAS", "2026-07-22", "LONG", 900.0)
    record(memory, "GHOST", "2026-07-22", "LONG", -400.0)
    assert sp.run(min_trades=1, memory=memory, store=store) == 0


def test_verdict_refuses_to_conclude_from_a_thin_sample(monkeypatch):
    warned = []
    monkeypatch.setattr(sp, "warn", warned.append)
    sp._verdict([dict(alignment="WITH_TREND", pnl=1000.0)] * 3
                + [dict(alignment="AGAINST_TREND", pnl=-100.0)] * 3, 1)
    assert any("NOT ENOUGH DATA" in w for w in warned)


def test_verdict_reports_mean_reversion_when_that_is_what_the_data_says(
        monkeypatch):
    said = []
    monkeypatch.setattr(sp, "decision", said.append)
    sp._verdict([dict(alignment="WITH_TREND", pnl=-800.0)] * 25
                + [dict(alignment="AGAINST_TREND", pnl=800.0)] * 25, 1)
    assert any("mean reversion" in s for s in said)


def test_verdict_reports_continuation_when_that_is_what_the_data_says(
        monkeypatch):
    said = []
    monkeypatch.setattr(sp, "decision", said.append)
    sp._verdict([dict(alignment="WITH_TREND", pnl=800.0)] * 25
                + [dict(alignment="AGAINST_TREND", pnl=-800.0)] * 25, 1)
    assert any("WITH the daily trend looks better" in s for s in said)


def test_verdict_calls_a_dead_heat_a_dead_heat(monkeypatch):
    said = []
    monkeypatch.setattr(sp, "decision", said.append)
    sp._verdict([dict(alignment="WITH_TREND", pnl=100.0)] * 25
                + [dict(alignment="AGAINST_TREND", pnl=110.0)] * 25, 1)
    assert any("not earning its place" in s for s in said)


# ----------------------------------------------------------
# TradeMemory.all_trades -- the accessor this tool needed
# ----------------------------------------------------------

def test_all_trades_returns_rows_oldest_first(memory):
    record(memory, "B", "2026-07-23", "LONG", 100.0)
    record(memory, "A", "2026-07-22", "LONG", 100.0)
    rows = memory.all_trades()
    assert [r["trade_date"] for r in rows] == ["2026-07-22", "2026-07-23"]


def test_all_trades_honours_since(memory):
    record(memory, "A", "2026-07-22", "LONG", 100.0)
    record(memory, "B", "2026-07-24", "LONG", 100.0)
    assert [r["symbol"] for r in memory.all_trades(since="2026-07-23")] \
        == ["B"]


def test_all_trades_is_empty_on_a_fresh_store(memory):
    assert memory.all_trades() == []
