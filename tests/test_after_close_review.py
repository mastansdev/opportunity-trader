"""
The dashboard has to outlive the trading session.

    "but main.py will auto close after market timings right?"
                                    -- operator, 30 July 2026

It did. main.py's loop breaks on its FIRST pass the moment
`now >= MARKET_CLOSE_T`, which was correct for a bot and quietly wrong
for a dashboard: the POST-MARKET tab -- closed trades, performance, and
every reason the bot refused a signal -- could only be read while the
market was open, which is exactly when nobody wants to read it. The tab
was built for a screen that no longer existed by the time it mattered.

WHAT CHANGED, AND WHAT DID NOT
------------------------------
NOT changed: the trading day. The loop still breaks at 15:30, state is
still saved, the feed is still closed, the circuit poller and every
watcher still stop. No order path survives the close.

Changed: the process stays alive afterwards, serving the page read-only,
until Ctrl+C or 09:00 the next morning.

THE HAZARD THIS CREATES
-----------------------
A process left running overnight has a closed feed and yesterday's
opening ranges. Still serving at 09:15 it would look live and be dead --
the worst state this screen can be in, because every number on it is
plausible. The banner is a label; the 09:00 auto-exit is the safeguard.
A banner is a thing you have to notice.
"""

from datetime import time as dtime

import config
import main


def test_the_trading_day_still_ends_at_the_close():
    """The review hold must not have moved the close by a single minute."""
    assert config.MARKET_CLOSE == "15:30"
    assert main.MARKET_CLOSE_T == dtime(15, 30)


def test_the_flag_and_the_cutoff_exist_and_are_sane():
    assert config.KEEP_DASHBOARD_AFTER_CLOSE is True
    assert main.AFTER_CLOSE_EXIT_T == dtime(9, 0)
    assert main.AFTER_CLOSE_EXIT_T < main.MARKET_CLOSE_T, (
        "the review hold must end BEFORE the market opens, or a stale "
        "page outlives the start of a live session")


def _should_exit(now):
    """The hold's own condition, lifted verbatim from
    _hold_dashboard_for_review(). Kept here as one expression so the
    clock logic is testable without a 17-hour test."""
    return main.MARKET_CLOSE_T > now >= main.AFTER_CLOSE_EXIT_T


def test_the_hold_does_not_exit_the_moment_it_starts():
    """The trap in the obvious version. `now >= 09:00` alone is TRUE at
    15:30, so the hold would fire its own exit on the first pass and the
    review screen would last one loop iteration -- the exact bug it was
    written to fix, reintroduced."""
    assert not _should_exit(dtime(15, 30))
    assert not _should_exit(dtime(16, 0))


def test_the_hold_survives_the_evening_and_the_night():
    for moment in (dtime(16, 0), dtime(18, 45), dtime(21, 30),
                   dtime(23, 59), dtime(0, 1), dtime(3, 0), dtime(8, 59)):
        assert not _should_exit(moment), f"the hold quit at {moment}"


def test_the_hold_stops_itself_before_the_next_open():
    """09:00, a clear 15 minutes before the 09:15 open."""
    assert _should_exit(dtime(9, 0))
    assert _should_exit(dtime(9, 14))
    assert main.AFTER_CLOSE_EXIT_T < dtime(9, 15), (
        "it must stop BEFORE the open, not during it")


def test_ctrl_c_does_not_earn_a_review_hold():
    """A Ctrl+C means the operator wants the process gone. Holding it
    open would be arguing with him -- so the hold is gated on
    `closed_normally`, which only the market-close branch sets."""
    source = open("main.py", encoding="utf-8").read()
    assert "closed_normally = False" in source, "the gate is not initialised"
    assert source.count("closed_normally = True") == 1, (
        "exactly one place may set it -- the market-close branch")
    close_branch = source[source.find("if now >= MARKET_CLOSE_T:"):]
    assert "closed_normally = True" in close_branch[:700], (
        "the market-close branch must be the thing that sets the gate")
    assert "if KEEP_DASHBOARD_AFTER_CLOSE and closed_normally:" in source, (
        "the hold must be gated on BOTH the flag and a normal close")


def test_the_feed_closes_before_the_dashboard_is_held_open():
    """A live Dhan WebSocket held open all night to serve a read-only
    page is an unnecessary connection and an unnecessary risk."""
    source = open("main.py", encoding="utf-8").read()
    feed_close = source.find("_safe_close_feed(feed, timeout=5)")
    hold = source.find("_hold_dashboard_for_review(dashboard_state)")
    stop_dash = source.rfind("stop_dashboard(dashboard_server")
    assert -1 not in (feed_close, hold, stop_dash)
    assert feed_close < hold, "the feed must be closed before the hold"
    assert hold < stop_dash, (
        "stop_dashboard() must run AFTER the hold -- called before it, the "
        "page the hold exists to serve is already gone")


def test_state_is_saved_before_the_hold():
    """If the hold or the process dies during review, the session must
    already be on disk."""
    source = open("main.py", encoding="utf-8").read()
    assert source.find("state_store.save(") < source.find(
        "_hold_dashboard_for_review(dashboard_state)")


# ---------------------------------------------------------------
# THE BOT SCORES ITSELF. NO CLICKS.
# ---------------------------------------------------------------
#     "again why manual runs? why can't bot do itself."
#                                     -- operator, 4 August 2026
#
# I had him running build_daily_history.py and then verify_picks.py by
# hand after every close, in that order, or the second reports nothing.
# That is a sequence a machine should own -- and one he would forget on
# the day the answer mattered.
def _main_code():
    src = open("main.py", encoding="utf-8").read()
    return "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))


def test_the_close_runs_the_scorecard_itself():
    code = _main_code()
    assert "_score_the_day()" in code
    assert "def _score_the_day():" in code


def test_the_bars_are_built_before_the_picks_are_scored():
    """Reversed, verify_picks correctly refuses to report -- which is
    the right behaviour and a terrible thing to rediscover by hand."""
    code = _main_code()
    body = code[code.find("def _score_the_day():"):
                code.find("def _hold_dashboard_for_review")]
    assert body.find("build_bars()") < body.find("verify()")


def test_a_missing_bhavcopy_is_explained_not_shown_as_zero():
    """NSE publishes on its own schedule. Missing it at 15:35 is normal
    -- reporting a zero-trade day because of it is not."""
    body = open("main.py", encoding="utf-8").read()
    body = body[body.find("def _score_the_day():"):
                body.find("def _hold_dashboard_for_review")]
    assert "not available yet" in body
    assert body.count("except Exception") >= 3


def test_scoring_can_never_break_the_shutdown():
    """It runs after the feed is closed and every order path is dead.
    Nothing is left to protect except the shutdown itself."""
    code = _main_code()
    # The guard gained a second condition on 5 August: Ctrl+C after the
    # close must score too. "if closed_normally:" is no longer the
    # literal text -- see test_scorecard_runs.py for why.
    at = code.find("_score_the_day()")
    guard = code[code.rfind("if ", 0, at):at]
    assert "closed_normally" in guard
    assert "MARKET_CLOSE_T" in guard


def test_it_is_callable_with_no_arguments():
    """main.py calls both entry points bare. A signature change would
    otherwise only show up at 15:35 on a live day."""
    import inspect

    from tools.build_daily_history import main as build_bars
    from tools.verify_picks import main as verify
    assert not [p for p in inspect.signature(build_bars).parameters.values()
                if p.default is inspect.Parameter.empty]
    assert not [p for p in inspect.signature(verify).parameters.values()
                if p.default is inspect.Parameter.empty]


# ---------------------------------------------------------------
# THE AFTER-CLOSE CHAIN RUNS ITSELF TOO
# ---------------------------------------------------------------
#     "complete the wherever automation can be done. give me only
#      which cannot be automated."   -- operator, 4 August 2026
def test_the_nightly_chain_runs_at_the_close():
    code = _main_code()
    assert "_run_nightly()" in code
    assert "def _run_nightly():" in code


def test_telegram_is_excluded_from_the_automatic_chain():
    """tools/collector.py owns data/telegram.db and is the only process
    allowed to write it. Two writers on a Windows drive corrupted that
    store on 2 August, and nightly's telegram step is a second writer."""
    code = _main_code()
    body = code[code.find("def _run_nightly():"):]
    assert 'step[0] == "telegram"' in body
    assert "continue" in body


def test_one_failing_step_does_not_stop_the_rest():
    """'universe' runs LAST and reads everything above it. Losing
    'discover' should still leave tomorrow's list built from what we
    have -- degraded and said so, never absent."""
    body = _main_code()
    body = body[body.find("def _run_nightly():"):]
    assert "Continuing." in body


def test_the_steps_are_read_from_nightly_not_copied():
    """A second hard-coded list would drift the day a step is added."""
    body = _main_code()
    body = body[body.find("def _run_nightly():"):]
    assert "from tools.nightly import STEPS, run" in body


def test_nightly_still_exposes_what_main_calls():
    """A signature change would otherwise only surface at 15:35 live."""
    from tools.nightly import STEPS, run
    assert callable(run)
    assert STEPS and len(STEPS[0]) == 4
    assert any(s[0] == "telegram" for s in STEPS)
    assert any(s[0] == "universe" for s in STEPS)
