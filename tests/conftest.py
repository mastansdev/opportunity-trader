"""
==========================================================
Shared test fixtures
==========================================================

Discovered live, 2026-07-23: tests/test_engine.py drives a REAL
Engine -> Execution -> PaperExecution -> trading/trade_logger.py's
log_trade(), and nothing anywhere injected a path override for
it -- every pytest run was silently appending test-fixture trades
(TCS/INFY at recognizable test prices like 112.0, 225.0, 250.0)
into the SAME logs/trade_log.csv the live bot writes real trades
to. Harmless to correctness (tests never read that file back),
but it quietly corrupts the one file the operator trusts as their
actual trade history the moment a real session and a test run
overlap -- exactly the kind of silent, easy-to-miss bug this
whole project has tried hard to avoid.

This autouse fixture applies to EVERY test in this directory,
not just test_engine.py -- redirecting the module-level path once
here is far more reliable than remembering to do it per file (the
existing test_trade_logger.py already did its own per-test
monkeypatch, which still works fine layered on top of this).

Author : H&M Opportunity Trader
==========================================================
"""

import os

import pytest

from trading import trade_logger


@pytest.fixture(autouse=True)
def _isolate_trade_log(tmp_path, monkeypatch):
    monkeypatch.setattr(
        trade_logger, "TRADE_LOG_PATH", os.path.join(str(tmp_path), "trade_log.csv")
    )


# Mechanisms that config.py may switch OFF in production, but whose
# CODE still has to be tested.
#
# 2026-07-27: eight strategy gates were disabled in config.py at once
# (shorts, rotation, sector gate, still-trending, the early-momentum
# door, the no-progress timer, one-trade-per-symbol, reentry-block).
# Twenty-four tests went red -- not because anything broke, but
# because they assert what those mechanisms DO, and the mechanisms
# were now short-circuiting on a production flag.
#
# That coupling is the real bug: a test of "does the sector gate
# reject a weak sector" should never depend on whether we happen to
# be running the sector gate this week. Otherwise every strategy
# decision silently deletes test coverage, and the suite goes quiet
# exactly when it is most needed.
#
# So tests exercise every mechanism; config decides which ones the
# live bot actually uses. A test that wants a mechanism OFF still
# monkeypatches it off itself, and that still wins -- this fixture
# only sets the starting state.
_MECHANISMS_ON_FOR_TESTS = (
    "ENABLE_SHORT_TRADES",
    "ENABLE_SLOT_ROTATION",
    "ENABLE_SECTOR_STRENGTH_GATE",
    "ENABLE_STILL_TRENDING",
    "ENABLE_EARLY_MOMENTUM_ENTRY",
    "ENABLE_NO_PROGRESS_EXIT",
    "ONE_TRADE_PER_SYMBOL_PER_DAY",
    "BLOCK_REENTRY_AFTER_STOPOUT",
    "ENABLE_TREND_RANK_ENTRY",
)


@pytest.fixture(autouse=True)
def _mechanisms_enabled_for_tests(monkeypatch):
    import core.engine as engine_module

    for name in _MECHANISMS_ON_FOR_TESTS:
        if hasattr(engine_module, name):
            monkeypatch.setattr(engine_module, name, True)


@pytest.fixture(autouse=True)
def _no_wall_clock_dependence(monkeypatch):
    """The ORB exchange-reconcile is only allowed to run within a few
    minutes of 09:30 (see _reconcile_orb_once -- a restart at 10:36 was
    re-widening every range to the running day high). That guard reads
    the real clock, which would make every reconcile test pass or fail
    depending on the hour it was run.

    Tests exercise the MECHANISM; the deadline is pushed to end of day
    here so the suite gives the same answer at 09:00 and at 23:00. The
    guard itself has its own dedicated tests in
    tests/test_orb_reconcile_time_guard.py, which set the deadline
    explicitly."""
    import core.engine as engine_module
    from datetime import time as dtime

    monkeypatch.setattr(engine_module, "_ORB_RECONCILE_DEADLINE_T",
                        dtime(23, 59, 59))
