"""
The reason columns in trade memory, 2026-07-28.

Before this, the learning loop recorded four things about every trade:
sector, hour, relative strength, regime. All four are PRICE context.

So after six months it could answer "do metals breakouts at 10am work"
-- the price-and-volume question the operator has already rejected --
and could never answer the one he cares about:

    "no info why gaining = no entry at all"

Do ORDER_WIN entries beat BROKER upgrades? Does a STRONG results grade
beat MIXED? Are entries WITH a reason better than entries without?
None of it was recorded, so none of it could be asked.
"""

from datetime import datetime

import pytest

from core.trade_memory import TradeMemory


@pytest.fixture
def memory(tmp_path):
    return TradeMemory(url=f"sqlite:///{tmp_path}/tm.db")


def _trade(symbol="CUB", **extra):
    base = dict(
        symbol=symbol, direction="LONG",
        entry_time=datetime(2026, 7, 28, 9, 45),
        exit_time=datetime(2026, 7, 28, 11, 30),
        entry_price=239.61, exit_price=260.0, qty=834, pnl=17005.0,
        exit_reason="TRAILING_STOP", entry_reason="MANUAL_BUY_DASHBOARD",
        holding_seconds=6300, sector="BANKING",
    )
    base.update(extra)
    return base


# ---------------------------------------------------------------
# The columns exist and round-trip
# ---------------------------------------------------------------

def test_the_reason_is_stored_and_can_be_read_back(memory):
    assert memory.record(_trade(
        news_kind="ORDER_WIN", filing_kind="RESULTS", results_grade="STRONG",
        days_since_results=0, had_reason=1,
        reason_summary="filed:RESULTS, results:STRONG",
    ))
    with memory.engine.begin() as conn:
        row = conn.execute(memory.trades.select()).mappings().first()
    assert row["news_kind"] == "ORDER_WIN"
    assert row["filing_kind"] == "RESULTS"
    assert row["results_grade"] == "STRONG"
    assert row["had_reason"] == 1
    assert row["reason_summary"] == "filed:RESULTS, results:STRONG"


def test_a_trade_with_no_reason_records_had_reason_zero(memory):
    """CMLL, 2026-07-28: up 6.8% with nothing behind it. The operator's
    rule refuses these -- but the bot must still be able to COUNT them,
    or "with reason beats without" can never be measured."""
    assert memory.record(_trade(symbol="CMLL"))
    with memory.engine.begin() as conn:
        row = conn.execute(memory.trades.select()).mappings().first()
    assert row["had_reason"] == 0
    assert row["news_kind"] is None
    assert row["reason_summary"] is None


def test_had_reason_is_never_left_null(memory):
    """It is the headline column -- the one that answers the question.
    A NULL would silently drop the trade out of both groups."""
    memory.record(_trade(symbol="A"))
    memory.record(_trade(symbol="B", had_reason=True))
    with memory.engine.begin() as conn:
        rows = conn.execute(memory.trades.select()).mappings().all()
    assert all(r["had_reason"] in (0, 1) for r in rows)


# ---------------------------------------------------------------
# Migration -- the live DB already has 28 rows and the OLD shape
# ---------------------------------------------------------------

def test_an_existing_old_table_gains_the_new_columns(tmp_path):
    """create_all() creates MISSING TABLES; it does not alter an
    existing one. Without the migration a live trade_memory.db keeps
    its old shape and every insert fails -- silently, because record()
    swallows exceptions by design. Nothing would be recorded again and
    nobody would notice."""
    import sqlite3
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE trade_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, direction TEXT NOT NULL,
            trade_date TEXT NOT NULL, entry_time TIMESTAMP,
            exit_time TIMESTAMP, entry_price FLOAT, exit_price FLOAT,
            qty INTEGER, pnl FLOAT, exit_reason TEXT, entry_reason TEXT,
            holding_minutes FLOAT, sector TEXT, entry_hour TEXT,
            rel_strength FLOAT, regime TEXT, recorded_at TIMESTAMP)
    """)
    con.execute("INSERT INTO trade_memory (symbol,direction,trade_date) "
                "VALUES ('OLDTRADE','LONG','2026-07-27')")
    con.commit(); con.close()

    mem = TradeMemory(url=f"sqlite:///{path}")
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(trade_memory)")}
    assert {"news_kind", "filing_kind", "results_grade",
            "days_since_results", "had_reason", "reason_summary"} <= cols
    # and the trade that was already there survives
    assert con.execute("select count(*) from trade_memory").fetchone()[0] == 1
    con.close()

    assert mem.record(_trade(symbol="NEWTRADE", had_reason=1))


def test_the_migration_is_safe_to_run_twice(tmp_path):
    url = f"sqlite:///{tmp_path}/twice.db"
    TradeMemory(url=url)
    mem = TradeMemory(url=url)
    assert mem.record(_trade(had_reason=1))


# ---------------------------------------------------------------
# It must never be able to break a trade
# ---------------------------------------------------------------

def test_recording_never_raises_on_junk(memory):
    assert memory.record({}) is False
    assert memory.record({"symbol": "X"}) is False
