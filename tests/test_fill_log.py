"""
Tests for core/fill_log.py.

    "another thing while buying & selling slippages too cost us.
     need to place as limit orders (need to discuss)"
                                    -- operator, 29 July 2026

trading/slippage.py's own docstring asks for exactly this store:

    "Every real fill should be compared against the price the bot
     wanted, and THAT difference should replace these constants."

Both executors already computed the miss on every fill and threw it
away. On 29 July that was 84 fills. The FIRST REAL ORDERS are placed
on 30 July and they happen once.

THE RULE: paper and live never share a number.
"""

import os

import pytest

from core.fill_log import FillLog


@pytest.fixture
def log(tmp_path):
    return FillLog(db_path=str(tmp_path / "fills.db"))


# ---------------------------------------------------------------
# the measurement
# ---------------------------------------------------------------

def test_a_buy_that_fills_high_is_a_cost(log):
    assert log.record("LIVE", "BUY", "KAYNES", "15083", 59, 3338.0, 3341.50)
    row = log.rows()[0]
    assert row["slip_rs"] == pytest.approx(206.5)      # 3.50 x 59
    assert row["slip_pct"] == pytest.approx(0.1048, abs=0.001)


def test_a_sell_that_fills_low_is_also_a_cost(log):
    """Both legs cost you. A sell hitting the bid is the mirror of a
    buy lifting the offer, and reporting only one would halve the
    measured cost of trading."""
    log.record("LIVE", "SELL", "KAYNES", "15083", 59, 3400.0, 3396.50)
    assert log.rows()[0]["slip_rs"] == pytest.approx(206.5)


def test_a_fill_better_than_asked_is_recorded_as_negative(log):
    """It happens, and hiding it would overstate the true cost --
    averaging only the bad fills is not an average."""
    log.record("LIVE", "BUY", "INFY", "1594", 100, 1150.0, 1148.0)
    row = log.rows()[0]
    assert row["slip_rs"] < 0
    assert log.stats("LIVE")["better_than_asked"] == 1


def test_the_intent_and_the_fill_are_both_kept(log):
    """The whole point. Storing only the difference would make it
    impossible to check the arithmetic later."""
    log.record("LIVE", "BUY", "KAYNES", "15083", 59, 3338.0, 3341.50)
    row = log.rows()[0]
    assert row["intent_price"] == 3338.0
    assert row["fill_price"] == 3341.50


# ---------------------------------------------------------------
# paper and live never share a number
# ---------------------------------------------------------------

def test_live_stats_ignore_paper_fills(log):
    """A modelled cost and a real one are different kinds of number.
    This project's one unbent rule."""
    log.record("PAPER", "BUY", "A", "1", 10, 100.0, 100.20)
    log.record("LIVE", "BUY", "B", "2", 10, 100.0, 100.05)
    assert log.stats("LIVE")["fills"] == 1
    assert log.stats("LIVE")["median_pct"] == pytest.approx(0.05, abs=0.001)
    assert log.stats("PAPER")["fills"] == 1


def test_stats_default_to_live_because_that_is_the_point(log):
    log.record("PAPER", "BUY", "A", "1", 10, 100.0, 100.20)
    assert log.stats()["mode"] == "LIVE"
    assert log.stats()["fills"] == 0


def test_it_suggests_the_number_that_should_replace_the_guess(log):
    """config.SLIPPAGE_BASE_PCT is a conventional retail figure. This
    is what the operator's own fills say instead."""
    for _ in range(4):
        log.record("LIVE", "BUY", "A", "1", 10, 100.0, 100.10)
    assert log.stats("LIVE")["suggested_pct"] == pytest.approx(0.001, abs=1e-5)


def test_rows_can_be_narrowed_to_one_day(log):
    from datetime import datetime
    log.record("LIVE", "BUY", "A", "1", 10, 100.0, 100.1,
               at=datetime(2026, 7, 30, 9, 20))
    log.record("LIVE", "BUY", "B", "2", 10, 100.0, 100.1,
               at=datetime(2026, 7, 31, 9, 20))
    assert len(log.rows(date="2026-07-30")) == 1


# ---------------------------------------------------------------
# it must never break an order
# ---------------------------------------------------------------

def test_junk_is_refused_rather_than_stored(log):
    assert log.record("LIVE", "BUY", "A", "1", 0, 100.0, 100.0) is False
    assert log.record("LIVE", "BUY", "A", "1", 10, 0, 100.0) is False
    assert log.record("LIVE", "BUY", "A", "1", 10, "x", 100.0) is False
    assert log.record("LIVE", "BUY", "A", "1", 10, None, None) is False
    assert log.rows() == []


def test_an_unwritable_store_does_not_raise(tmp_path):
    """A bookkeeping failure must not be able to break an order --
    but it must be LOUD, because these fills cannot be recreated."""
    bad = FillLog(db_path=os.path.join(str(tmp_path), "nope", "x", "f.db"))
    bad._ready = False
    assert bad.record("LIVE", "BUY", "A", "1", 10, 100.0, 100.1) is False
    assert bad.rows() == []
    assert bad.stats("LIVE")["fills"] == 0


def test_reading_an_empty_store_is_survivable(log):
    assert log.rows() == []
    assert log.stats("LIVE")["fills"] == 0
    assert "no fills" in log.stats("LIVE")["note"]


# ---------------------------------------------------------------
# the executors actually call it
# ---------------------------------------------------------------

def test_paper_execution_records_every_fill(tmp_path):
    from trading.paper_execution import PaperExecution
    log = FillLog(db_path=str(tmp_path / "f.db"))
    PaperExecution(fill_log=log).buy("15083", "KAYNES", 3338.0, 59,
                                     reason="STRUCTURAL_LONG_BREAKOUT")
    rows = log.rows()
    assert len(rows) == 1
    assert rows[0]["mode"] == "PAPER"
    assert rows[0]["symbol"] == "KAYNES"
    assert rows[0]["intent_price"] == 3338.0
    # The model always fills worse than intent.
    assert rows[0]["fill_price"] >= 3338.0


def test_the_path_is_read_at_construction_not_at_import(tmp_path,
                                                        monkeypatch):
    """`db_path=DB_PATH` as a default argument would bind the
    production path at import time, and tests/conftest.py's redirect
    would silently do nothing -- putting fixture fills into the real
    store."""
    from core import fill_log as module
    monkeypatch.setattr(module, "DB_PATH", str(tmp_path / "redirected.db"))
    assert module.FillLog().db_path == str(tmp_path / "redirected.db")
