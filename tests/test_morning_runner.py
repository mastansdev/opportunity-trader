"""
==========================================================
Sequencing jobs is the machine's work
==========================================================

    "you know better than me in doing all this repeated tasks. why
     user needs to do ?"
                                    -- operator, 3 August 2026

He is right, and his first live morning is the evidence:

    06:19  nightly's telegram step ran, read nothing, reported "ok"
    06:29  telegram_catchup, refused: ALREADY RUNNING
    06:31  verify_master_database, failed on 3 stale security ids
    06:37  telegram_catchup again -- 45 minutes
    08:20  morning_universe, on data the telegram step never fetched
    08:51  main.py, blocked 24 minutes by its own catch-up

Six commands, an order he had to remember, and a collision he could not
have predicted because nightly.py's first step was the same tool he had
just run by hand. None of that was his mistake.

WHAT THIS RUNNER MUST NOT DO
----------------------------
Start main.py or the collector. Those two RUN rather than finish, and a
script that launches a trading engine as a side effect is a script that
can start one by accident. They stay in his hands, in their own
terminals.

Refuse, never queue. If a Telegram reader is already running it says so
and moves to the steps that do not need one -- it never waits and it
never kills anything.

Carry on after a failure. verify exits non-zero when the master is
dirty, which is CORRECT, and still leaves four other steps worth
running before the bell.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

SRC = open("tools/morning.py", encoding="utf-8").read()


def steps():
    """The step table, as names in declared order."""
    block = SRC[SRC.index("STEPS = ["):SRC.index("# preopen_gaps is NOT")]
    return re.findall(r'\("([a-z_]+)",', block)


# ---------------------------------------------------------------
# 1. THE ORDER
# ---------------------------------------------------------------
def test_every_morning_job_is_in_the_runner():
    assert set(steps()) == {"token", "telegram", "universe", "verify", "brief"}


def test_the_token_comes_first():
    """Nothing else can reach Dhan without it."""
    assert steps()[0] == "token"


def test_telegram_is_read_before_the_universe_is_built():
    """On 3 August the universe was rebuilt at 08:20 on data the
    telegram step had never fetched, so it stamped SUBSCRIBE on a
    master that had not seen the night's discoveries."""
    order = steps()
    assert order.index("telegram") < order.index("universe")


def test_verify_runs_after_the_universe_edits_the_master():
    """morning_universe writes SUBSCRIBE on every row. Checking the
    security ids before that is checking a file that is about to
    change."""
    order = steps()
    assert order.index("universe") < order.index("verify")


# ---------------------------------------------------------------
# 2. WHAT IT MUST NEVER START
# ---------------------------------------------------------------
@pytest.mark.parametrize("never", ["main.py", "collector.py"])
def test_it_does_not_launch_anything_that_keeps_running(never):
    """A script that starts a trading engine as a side effect is a
    script that can start one by accident.

    ---- IT READ THE COMMENTS TOO. 12 August 2026. ----
    This used to slice the raw source from "STEPS = [" to "def run(" and
    search the TEXT. A comment added to the token step explaining that
    main.py mints its own Dhan token (main.py:194) failed it -- prose
    about a file, not a launch of it.

    Reading the actual commands instead is both stricter and honest: it
    catches a launch however the line is written, and cannot be fooled
    or tripped by anything in a comment.
    """
    from tools.morning import STEPS
    for step in STEPS:
        argv = step[2]
        assert not any(never in str(arg) for arg in argv), (
            f"the '{step[0]}' step runs {argv} -- morning.py must never "
            f"start {never}, it only tells him to")


def test_it_tells_him_to_start_them_himself():
    assert "NOW START THE TWO THAT KEEP RUNNING" in SRC
    assert "main.py" in SRC and "collector.py" in SRC


def test_preopen_gaps_is_deliberately_excluded():
    """NSE fixes opening prices between 09:08 and 09:12. Running it at
    08:30 with everything else returns an empty table -- the mistake
    the first written schedule made."""
    assert "preopen_gaps is NOT here" in SRC
    assert "09:12" in SRC
    assert "preopen_gaps" not in SRC[SRC.index("STEPS = ["):
                                     SRC.index("# preopen_gaps is NOT")]


# ---------------------------------------------------------------
# 3. IT REFUSES, IT DOES NOT QUEUE OR KILL
# ---------------------------------------------------------------
def test_a_telegram_step_stands_aside_for_a_running_reader():
    """The collector may already own the session. Two readers corrupt
    one Telethon session -- see core/runlock.py."""
    block = SRC[SRC.index("def run("):SRC.index("def main(")]
    assert "held_by_another()" in block
    assert "SKIPPED" in block


def test_only_the_telegram_step_waits_on_that_lock():
    """morning_universe and verify touch NSE and Dhan, not Telegram.
    Blocking them on a chat reader would be a made-up dependency."""
    table = SRC[SRC.index("STEPS = ["):SRC.index("# preopen_gaps is NOT")]
    needs = re.findall(r'\("([a-z_]+)",[\s\S]*?(True|False)\),', table)
    flags = {name: flag for name, flag in needs}
    assert flags["telegram"] == "True"
    for name in ("token", "universe", "verify", "brief"):
        assert flags[name] == "False", name


def test_it_never_kills_a_running_process():
    """Match CODE, not the prose that promises it. The docstring says
    "never kills anything", which contains the word -- the same trap
    that tripped test_single_instance and test_one_book tonight."""
    code = SRC[SRC.index("def run("):]
    for bad in ("kill(", "terminate(", "taskkill", "SIGKILL", "pkill"):
        assert bad not in code, bad


# ---------------------------------------------------------------
# 4. A FAILURE MUST NOT END THE MORNING
# ---------------------------------------------------------------
def test_one_failed_step_does_not_stop_the_rest():
    """verify exits 1 when the master is dirty. That is correct, and
    it still leaves four steps worth running before the bell."""
    assert "MOVING ON -- one failed tool does not stop the morning" in SRC


def test_a_failure_is_reported_with_the_command_to_retry():
    assert "did not finish" in SRC
    assert "--only" in SRC


def test_a_step_that_cannot_even_start_is_caught():
    block = SRC[SRC.index("def run("):SRC.index("def main(")]
    assert "except Exception" in block


def test_the_summary_says_how_long_each_took():
    """"ok telegram 0.0 min" is how a step that read nothing passed for
    a successful one. The duration is the tell."""
    assert "min" in SRC[SRC.index("DONE"):]
