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
from trading.trade_controller import TradeController


@pytest.fixture(autouse=True)
def _isolate_trade_log(tmp_path, monkeypatch):
    monkeypatch.setattr(
        trade_logger, "TRADE_LOG_PATH", os.path.join(str(tmp_path), "trade_log.csv")
    )


@pytest.fixture(autouse=True)
def _isolate_fill_log(tmp_path, monkeypatch):
    """Tests must never write into data/fills.db.

    Same reasoning as the trade log above, and the same trap:
    tests/test_engine.py drives a real Engine -> PaperExecution, which
    now records every fill. Without this, a pytest run would append
    fixture fills (TCS at 112.0, the X / AAA symbols) into the store
    that exists to measure REAL slippage -- and those fixture prices
    would then drag the measured average toward a number nobody
    traded.

    core/fill_log.py reads this module global at construction time
    rather than binding it as a default argument, precisely so this
    redirect works.
    """
    from core import fill_log
    monkeypatch.setattr(
        fill_log, "DB_PATH", os.path.join(str(tmp_path), "fills.db"))


@pytest.fixture(autouse=True)
def _isolate_pause_flag(tmp_path, monkeypatch):
    """Tests must never touch the LIVE pause flag.

    Found 2026-07-28, during a live session: TradeController.
    PAUSE_FLAG_PATH is a plain relative path on the class, so a test
    that constructs a real TradeController writes data/entries_paused
    .flag -- the same file the running bot reads at startup to decide
    whether new entries are allowed.

    Running the suite that afternoon set it. The live process kept its
    own in-memory state so nothing stopped mid-session, but the NEXT
    restart would have come up with entries silently paused, on a day
    the bot had already been restarted three times.

    A test run must never be able to stop the bot trading.
    """
    monkeypatch.setattr(
        TradeController, "PAUSE_FLAG_PATH",
        os.path.join(str(tmp_path), "entries_paused.flag"),
    )


@pytest.fixture(autouse=True)
def _isolate_diagnostic_log(tmp_path, monkeypatch):
    """Tests must never write into the LIVE diagnostics log.

    Found 2026-07-28: 570 lines of that day's log carried pytest temp
    paths, and the suite emitted lines INDISTINGUISHABLE from real
    alarms --

        [DAILY HALT] Realized P&L -8500 <= -8000
        [BAD_TICK] TCS rejected 105.00 -- a 47.5% jump from 200.00

    None of it real. TCS never traded at 105. The operator cannot tell
    a test alarm from a live one, and neither could I -- I had to
    cross-check timestamps against my own pytest runs to be sure.

    Worse, the file is 369 MB with no rotation and is appended to by
    several processes at once, which had already corrupted 131,238
    lines by interleaving writes.

    Redirecting the handler here keeps the live log clean and readable,
    which is the only way a single unbroken session can ever be used as
    evidence.
    """
    import logging
    from core import logger as core_logger

    log = logging.getLogger("opportunity_trader")
    original = list(log.handlers)
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)
            h.close()
    handler = logging.FileHandler(
        os.path.join(str(tmp_path), "diagnostics.log"), encoding="utf-8"
    )
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    monkeypatch.setattr(
        core_logger, "DIAGNOSTIC_LOG_PATH",
        os.path.join(str(tmp_path), "diagnostics.log"), raising=False,
    )
    yield
    log.removeHandler(handler)
    handler.close()
    for h in original:
        if h not in log.handlers:
            log.addHandler(h)


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
def _tests_run_in_paper(monkeypatch):
    """A test must never depend on which mode the operator left set.

    31 July 2026. TRADING_MODE was changed to "LIVE" the night before a
    live trial. The next full run of this suite went from 1,637 passing
    to over 180 failures, all identical:

        RuntimeError: TRADING_MODE is LIVE but no Dhan client was
        provided.

    Nothing was broken. trading/execution.py reads TRADING_MODE at
    import, so every test that builds a bare Engine() -- which is most
    of them, because Engine's own behaviour has nothing to do with the
    broker -- inherited a production switch.

    THE CONSEQUENCE IS THE POINT. The suite is unusable in exactly the
    configuration where it matters most. Flip to LIVE and you lose the
    ability to check your work, on the one morning you most want it.
    Nobody would choose that; it happened because the coupling was
    invisible until the switch moved.

    Same argument as _mechanisms_enabled_for_tests above: tests
    exercise the MECHANISM, config decides what the live bot does. A
    test that wants LIVE sets it itself -- see tests/
    test_live_wiring.py, which patches this same name inside the test
    body and therefore wins over this fixture.
    """
    import trading.execution as execution_module

    monkeypatch.setattr(execution_module, "TRADING_MODE", "PAPER")


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


@pytest.fixture(autouse=True)
def _never_touch_the_live_dhan_token(tmp_path, monkeypatch):
    """No test may read or write the real Dhan access token.

    ---- IT HAPPENED. 13 August 2026. ----

    core/dhan_auth.py gained an on-disk token cache that morning, so a
    restart stops re-minting -- Dhan allows one token every two
    minutes and every `py main.py` was asking for a fresh one.

    tests/test_dhan_auth.py did not know about the new file. The first
    run wrote a ONE-CHARACTER token with a 2099 expiry into the real
    data/dhan_token.json, and main.py starting afterwards would have
    read that and failed to authenticate. A unit test would have taken
    the live session down.

    This is the structural answer rather than a fix in one file: for
    every test in this directory the cache points inside tmp_path. A
    test cannot reach the credential in either direction -- it cannot
    read one and it cannot leave one behind.

    Deliberately NOT limited to test_dhan_auth.py. Anything that ends
    up calling access_token() -- a preflight check, a dashboard build,
    a tool under test -- would write it too, and the next such caller
    is the one nobody thinks of.
    """
    from core import dhan_auth

    monkeypatch.setattr(dhan_auth, "TOKEN_CACHE",
                        str(tmp_path / "dhan_token.json"))


@pytest.fixture(autouse=True)
def _never_touch_the_live_bot_lock(tmp_path, monkeypatch):
    """No test may claim, read or release the real single-bot lock.

    ---- IT HAPPENED TOO. 16 August 2026. ----

    tests/test_single_instance.py patched a guard main.py had stopped
    calling the day before. The patch succeeded against the dead
    function, main() consulted the REAL guard, found no other bot and
    started one -- so pytest ran a live bot with a tick worker and the
    ranker for twenty minutes, and wrote its own pid into the lock:

        pid=7436 since=2026-08-14T07:39:03 argv=__main__.py

    Two separate harms, and the fixture in that file only covers one.
    A booted bot is the loud one. The quiet one is this file: while a
    suite runs, the lock names a LIVE pid, so `py main.py` in the
    other terminal would refuse to start and say another bot is
    already running. A test run must not be able to lock him out of
    his own session.

    Same shape as _never_touch_the_live_dhan_token above and for the
    same reason -- the next caller that ends up in claim() is the one
    nobody thinks of, so this is not limited to the tests that mean
    to exercise it.
    """
    from core import single_instance

    monkeypatch.setattr(single_instance, "LOCK_PATH",
                        str(tmp_path / "main_bot.lock"))


@pytest.fixture(scope="session", autouse=True)
def _no_test_may_litter_the_live_data_folder():
    """Nothing in this suite may CREATE a file in data/.

    ---- THREE OF THEM WERE ALREADY THERE. 16 August 2026. ----

    A store inventory found five empty databases in the folder that
    holds the bot's real memory:

        data/does-not-exist.db          tests/test_reporting_watchlist.py
        data/no-such-file-at-all.db     tests/test_discover_widens_safely.py
        data/there-is-no-such-file.db   tests/test_watchlist_shows_the_tier.py

    Each test was checking that a MISSING store fails softly, and each
    passed a fake name under data/. sqlite3.connect() creates the file
    it is handed, so "the database that does not exist" existed, empty,
    from the first run onwards.

    Empty files are harmless. The REACH is not: this is the same
    directory that took a one-character Dhan token from a unit test on
    13 August, and the same reach that let a test claim the live bot
    lock the next morning. Both were fixed one file at a time. This
    closes the direction.

    Session-scoped and observational -- it does not redirect anything,
    because tests legitimately READ the real stores. It fails the run
    if a file APPEARED, naming it, so the cause gets fixed rather than
    the litter swept up again later.
    """
    import glob

    before = set(glob.glob(os.path.join("data", "*")))
    yield
    after = set(glob.glob(os.path.join("data", "*")))
    new = sorted(n for n in (after - before))
    assert not new, (
        "the test suite CREATED files in the live data folder: "
        + ", ".join(new)
        + ". A test that needs a path which does not exist must use "
          "tmp_path -- data/ holds the bot's real memory.")
