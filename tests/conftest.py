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
