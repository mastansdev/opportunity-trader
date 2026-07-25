"""
==========================================================
Tests -- Trade Memory (the learning loop)
==========================================================

Pins the two things that matter: the CONTEXT is captured (not just the
P&L, which trade_log.csv already has), and the same trade can never be
counted twice into the statistics.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime

from core.trade_memory import TradeMemory


def _mem(tmp_path):
    return TradeMemory(url="sqlite:///" + os.path.join(str(tmp_path), "t.db"))


def _trade(symbol="TCS", direction="LONG", pnl=500.0, sector="IT",
           hour=10, day=24, reason="STOP", rel=0.012):
    entry = datetime(2026, 7, day, hour, 34, 0)
    exit_ = datetime(2026, 7, day, hour + 1, 4, 0)
    return {
        "symbol": symbol, "direction": direction,
        "entry_time": entry, "exit_time": exit_,
        "entry_price": 100.0, "exit_price": 100.0 + pnl / 100,
        "qty": 100, "pnl": pnl, "exit_reason": reason,
        "entry_reason": "STRUCTURAL_LONG_BREAKOUT",
        "holding_seconds": 1800, "sector": sector,
        "rel_strength": rel, "regime": "BOTH",
    }


def test_records_a_trade_with_its_context(tmp_path):
    m = _mem(tmp_path)
    assert m.record(_trade()) is True
    rows = m.by_sector()
    assert rows[0]["key"] == "IT"
    assert rows[0]["trades"] == 1


def test_same_trade_is_never_counted_twice(tmp_path):
    """A restart or a re-run must not double-count into the stats."""
    m = _mem(tmp_path)
    assert m.record(_trade()) is True
    assert m.record(_trade()) is False
    assert m.count() == 1


def test_same_symbol_on_a_different_day_is_a_new_trade(tmp_path):
    m = _mem(tmp_path)
    m.record(_trade(day=24))
    m.record(_trade(day=25))
    assert m.count() == 2


def test_opposite_direction_same_day_is_a_separate_trade(tmp_path):
    m = _mem(tmp_path)
    m.record(_trade(direction="LONG"))
    m.record(_trade(direction="SHORT"))
    assert m.count() == 2


def test_overall_stats_are_right(tmp_path):
    m = _mem(tmp_path)
    m.record(_trade(symbol="A", pnl=1000.0))
    m.record(_trade(symbol="B", pnl=-400.0))
    m.record(_trade(symbol="C", pnl=-400.0))
    o = m.overall()
    assert o["trades"] == 3
    assert o["wins"] == 1
    assert round(o["win_rate"]) == 33
    assert o["total_pnl"] == 200.0
    assert o["avg_win"] == 1000.0
    assert o["avg_loss"] == -400.0
    assert o["sessions"] == 1


def test_buckets_split_by_the_condition(tmp_path):
    m = _mem(tmp_path)
    m.record(_trade(symbol="A", sector="IT", hour=9, pnl=500))
    m.record(_trade(symbol="B", sector="IT", hour=9, pnl=500))
    m.record(_trade(symbol="C", sector="PHARMA", hour=11, pnl=-800))
    sectors = {r["key"]: r for r in m.by_sector()}
    assert sectors["IT"]["trades"] == 2 and sectors["IT"]["win_rate"] == 100.0
    assert sectors["PHARMA"]["win_rate"] == 0.0
    hours = {r["key"]: r for r in m.by_hour()}
    assert hours["09"]["trades"] == 2
    assert hours["11"]["trades"] == 1


def test_min_trades_filters_thin_buckets(tmp_path):
    m = _mem(tmp_path)
    m.record(_trade(symbol="A", sector="IT"))
    m.record(_trade(symbol="B", sector="IT"))
    m.record(_trade(symbol="C", sector="PHARMA"))
    assert {r["key"] for r in m.by_sector(min_trades=2)} == {"IT"}


def test_bad_input_never_raises(tmp_path):
    m = _mem(tmp_path)
    assert m.record({}) is False
    assert m.record({"symbol": "X"}) is False
    assert m.record({"direction": "LONG"}) is False
    assert m.count() == 0


def test_empty_memory_reports_cleanly(tmp_path):
    m = _mem(tmp_path)
    o = m.overall()
    assert o["trades"] == 0 and o["win_rate"] == 0.0
    assert m.by_sector() == [] and m.by_hour() == []
