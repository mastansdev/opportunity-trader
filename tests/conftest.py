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
import pathlib
import re

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
def _isolate_telegram_store(tmp_path, monkeypatch):
    """Tests must never write into data/telegram.db.

    ---- IT HAD NO FIXTURE, AND IT SHOWED. 6 September 2026. ----

    Same shape as the trade log and the fill log above, and it was the
    one store that never got one.

    tests/test_collector_stops.py builds a feed with
    TelegramFeed.__new__(), which skips __init__, so the object never
    learns a db_path and _note_attempt() falls back to this module
    global -- his real collected posts. Nine channels called c0..c8
    were bookmarked there on every full run, and the dashboard listed
    them beside the ten real ones. Proved by cleaning the store,
    running the suite, and watching them come back before it finished.

    A dozen other tests build a feed without a db_path and take the
    same default. Most only read, but "most" is not a guarantee, and
    finding out which by inspection is how the next one gets missed.
    One redirect closes every door, including the ones written next
    month.

    A test that genuinely wants a specific store still passes db_path
    and is unaffected -- this only changes what "no path given" means.
    """
    from core import telegram_feed
    monkeypatch.setattr(
        telegram_feed, "DB_PATH", os.path.join(str(tmp_path), "telegram.db"))


@pytest.fixture(autouse=True)
def _isolate_decision_log(tmp_path, monkeypatch):
    """Tests must never write into data/decisions.db.

    Caught by the same guard on the same day: a test that builds a
    feed also reaches the decision log, and the log is what answers
    "why was this stock not named" weeks later.
    """
    from core import decision_log
    monkeypatch.setattr(
        decision_log, "DB_PATH", os.path.join(str(tmp_path), "decisions.db"))


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
    # ---- PATCH THE DIAL, NOT A COPY OF IT. 3 September 2026. ----
    #
    # This set trading.execution.TRADING_MODE, a module-level binding
    # that no longer exists: that file now reads the value at call
    # time, because a binding cannot follow a dial that moves. Setting
    # config is what every reader sees, including the eight that were
    # already reading it live.
    import config as config_module

    monkeypatch.setattr(config_module, "TRADING_MODE", "PAPER")


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


@pytest.fixture(autouse=True)
def _never_touch_the_live_telegram_lock(tmp_path, monkeypatch):
    """No test may take the REAL Telegram reader lock.

    ---- CAUGHT BY THE LITTER GUARD. 18 August 2026. ----

    The full suite left data/telegram_reader.lock behind. That file is
    not litter: core/runlock.py uses it so only one reader talks to
    Telegram at a time, and tools/collector.py REFUSES TO START while
    another process holds it.

    So a test run could lock him out of his own collector -- the same
    shape as the bot lock on 16 August, which could lock him out of
    main.py. Both were written with a module-level default:

        def held_by_another(path=LOCK_PATH)

    and a default argument is bound once, at import, so patching the
    module attribute alone would change nothing. runlock is patched
    here AND its functions read the attribute per call.

    Third store this suite has had to be fenced away from, after
    data/dhan_token.json and data/main_bot.lock.
    """
    from core import runlock

    monkeypatch.setattr(runlock, "LOCK_PATH",
                        str(tmp_path / "telegram_reader.lock"))


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

    # ---- SQLITE'S OWN SIDECARS ARE NOT LITTER. 16 August 2026. ----
    #
    # Opening a WAL-mode database creates <name>.db-wal and -shm beside
    # it, and closing it cleanly removes them again. They appeared the
    # moment the dashboard started reading data/ai_spend.db and this
    # guard reported the whole run as an error for them.
    #
    # They are sqlite working files, not a test writing junk into his
    # data folder, and excluding them keeps the guard pointed at what
    # it was built for: a test that CREATES a store.
    #: Third-party cache files that land in data/ and are not the
    #: bot's memory. The `nse` package keeps its cookie jar in whatever
    #: download_folder it is given, and core/market_cap.py gives it
    #: "data" -- so a refresh, from the suite or from his own running
    #: collector, drops nse_cookies_requests.json there. Blaming a test
    #: for a library's cookie jar is how this guard gets switched off.
    _NOT_HIS_MEMORY = ("nse_cookies_requests.json", "nse_cookies.json")

    def _real(paths):
        return {p for p in paths
                if not p.endswith(("-wal", "-shm", "-journal"))
                and os.path.basename(p) not in _NOT_HIS_MEMORY}

    # ---- IT BLAMED THE SUITE FOR THE OPERATOR'S OWN BOT. 19 Aug ----
    #
    # A 13-minute run reported:
    #
    #     the test suite CREATED files in the live data folder:
    #     data	elegram_reader.lock
    #
    # It did not. The file read:
    #
    #     collector pid=17884 2026-08-19 07:19:33
    #
    # and pid 17884 was tools/collector.py, running on his machine the
    # whole time. The suite takes minutes; anything he starts during
    # one appears as "new" to a before/after snapshot.
    #
    # This nearly cost a real fix for a bug that was not there -- and
    # the more expensive damage is to the guard itself, because a
    # check that cries wolf is a check that gets skipped. So a new
    # file is excused ONLY when it is a lock naming a pid that is
    # ALIVE and is not this pytest process. A stale lock left behind
    # by a test still fails the run, which is the case it was built
    # for.
    # ---- THE NIGHTLY CHAIN DOWNLOADS WHILE THE SUITE RUNS ----
    #      20 August 2026.
    #
    # An 18-minute run reported:
    #
    #     the test suite CREATED files in the live data folder:
    #     data\BhavCopy_NSE_CM_0_0_0_20260819_F_0000.csv
    #
    # It did not. That is NSE's bhavcopy, fetched by his collector
    # during the run -- the same shape as the telegram lock on the
    # 19th. A suite that takes a quarter of an hour will keep meeting
    # files the live chain creates, and blaming the suite for them is
    # how a guard gets switched off.
    #
    # These are DATED, EXTERNALLY SOURCED files with a fixed naming
    # shape, so excusing them by name costs the guard nothing: a test
    # that writes data/whatever.db is still caught, which is the case
    # it exists for.
    # Files the LIVE after-close chain downloads from NSE. They appear
    # in data/ while the suite happens to be running and are not test
    # pollution.
    #
    # sec_list_ joined the list on 31 August 2026: the chain fetched
    # sec_list_28082026.csv (NSE's daily price bands, read by
    # core/headroom.py) one minute before a suite run, and the guard
    # reported the bot's own housekeeping as a test writing to data/.
    EXTERNAL = ("BhavCopy_", "sec_bhavdata", "MW-", "sec_list_")

    def _fetched_by_the_live_chain(path):
        name = os.path.basename(path)
        return name.startswith(EXTERNAL)

    def _written_by_a_live_process(path):
        if _fetched_by_the_live_chain(path):
            return True
        if not path.endswith(".lock"):
            return False
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8")
        except Exception:                                  # noqa: BLE001
            return False
        match = re.search(r"pid=(\d+)", text)
        if not match:
            return False
        pid = int(match.group(1))
        if pid == os.getpid():
            return False              # this suite wrote it -- not excused
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False

    before = _real(glob.glob(os.path.join("data", "*")))

    # ---- AND CHANGING ONE IS AS BAD AS MAKING ONE. 6 Sep 2026. ----
    #
    # This caught files being CREATED and said nothing about files
    # being CHANGED, so a test writing into a store that already
    # exists passed silently.
    #
    # tests/test_collector_stops.py built a feed with
    # TelegramFeed.__new__(), which skips __init__, so the object
    # never learned its db_path and _note_attempt() fell back to the
    # module default -- data/telegram.db, his real collected posts.
    # Nine channels called c0..c8 were bookmarked in it on every full
    # run, and his dashboard listed them beside the ten real ones.
    #
    # Proved by cleaning the store, running the suite, and watching
    # them come back before it finished.
    #
    # Only the stores are watched, not every file: several parts of
    # the bot legitimately refresh a cache under data/ when a test
    # imports them, and a rule that fires on those would be turned off
    # within a week.
    watched = {}
    for path in glob.glob(os.path.join("data", "*.db")):
        try:
            watched[path] = os.path.getmtime(path)
        except OSError:
            pass

    # Asked BEFORE as well as after. He stopped his collector in the
    # middle of a run on 6 September; every store it had already
    # touched then looked like test pollution, because the lock was
    # gone by the time the question was asked.
    def _collector_alive():
        try:
            from core import runlock
            return bool(runlock.held_by_another()[0])
        except Exception:                                  # noqa: BLE001
            return False

    was_collecting = _collector_alive()

    yield

    after = _real(glob.glob(os.path.join("data", "*")))
    new = sorted(n for n in (after - before)
                 if not _written_by_a_live_process(n))
    assert not new, (
        "the test suite CREATED files in the live data folder: "
        + ", ".join(new)
        + ". A test that needs a path which does not exist must use "
          "tmp_path -- data/ holds the bot's real memory.")

    # ---- HIS COLLECTOR IS ALLOWED TO BE RUNNING. 6 Sep 2026. ----
    #
    # He runs py tools/collector.py all day, and it writes telegram.db
    # every ninety seconds. Blaming a test for that would make the
    # suite unrunnable exactly when he is collecting, which is most of
    # the time -- and a guard that cannot be trusted gets switched off.
    #
    # core/runlock.py already answers "is a reader alive": the
    # collector holds data/telegram_reader.lock with its pid in it.
    # _written_by_a_live_process() above cannot see that, because it
    # reads the FILE for a pid marker and a sqlite store is binary.
    collecting = was_collecting or _collector_alive()
    #: What the collector legitimately writes while it runs.
    HIS = {"telegram.db", "stock_events.db", "decisions.db"}

    touched = []
    for path, was in watched.items():
        if _written_by_a_live_process(path):
            continue                  # a live process left its pid in it
        name = os.path.basename(path)
        if collecting and name in HIS:
            continue                  # his collector, not this suite
        try:
            if os.path.getmtime(path) != was:
                touched.append(name)
        except OSError:
            continue
    # ---- IT REPORTS. THE FIX IS THE ISOLATION. 6 Sep 2026. ----
    #
    # This was switched to a hard failure and blamed the wrong test
    # twice: a database flushes when it feels like it, so the mtime
    # change lands during the NEXT test, not the one that wrote. Run
    # alone every accused test passed.
    #
    # A guard that fails the suite for the wrong reason gets switched
    # off, so it says what it saw and lets the run pass.
    #
    # THE ACTUAL FIX IS ABOVE, and it is at the source:
    # _isolate_telegram_store and _isolate_decision_log now redirect
    # those module globals to tmp_path for every test, the way the
    # trade log and fill log have always been redirected. The telegram
    # store was the one that never had a fixture, which is how
    # tests/test_collector_stops.py came to bookmark nine channels
    # called c0..c8 in his real data on every run.
    #
    # And core/telegram_feed._note_attempt() was passing no path at
    # all, so it took core/feed_clock.py's default -- a feed pointed
    # at any other store wrote its MESSAGES there and its BOOKMARKS to
    # the live one. That was a production bug, not a test one.
    if touched:
        print("  [DATA] a live store changed during the suite: "
              + ", ".join(sorted(touched))
              + " -- if no collector was running, find what wrote it.")
