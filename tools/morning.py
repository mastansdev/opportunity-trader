"""
==========================================================
One command. The whole morning.
==========================================================
    py tools/morning.py           everything, in order
    py tools/morning.py --skip telegram,brief
    py tools/morning.py --only universe

    "you know better than me in doing all this repeated tasks. why
     user needs to do ?"
                                    -- operator, 3 August 2026

He is right. On his first live morning he typed six commands, in an
order he had to remember, while a market opened -- and two of them
collided because he could not have known that nightly.py's first step
was the same tool he had just run by hand.

    06:19  nightly's telegram step, silent, read nothing
    06:29  telegram_catchup, refused: ALREADY RUNNING
    06:31  verify_master_database, failed on 3 stale security ids
    06:37  telegram_catchup again, 45 minutes
    08:20  morning_universe, on data the telegram step never fetched
    08:51  main.py, blocked 24 minutes by its own catch-up

None of that was his mistake. Sequencing jobs is the machine's work.

WHAT THIS DOES NOT DO
---------------------
It does not start main.py and it does not start the collector. Those
two RUN, they do not finish, and a script that launches a trading
engine as a side effect is a script that can start one by accident.
They stay his, in their own terminals, deliberately.

It also refuses rather than queues. If a Telegram reader is already
running it says so and moves on to the steps that do not need one --
never waits, never kills anything.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.runlock import held_by_another                   # noqa: E402

PY = sys.executable or "py"

# In order. `needs_telegram` marks the ones that cannot run while the
# collector or another reader holds the session.
STEPS = [
    # ---- THE LOGIN STEP RAN A TOOL THAT DOES NOT EXIST. ----
    #      12 August 2026.
    #
    # This called tools/dhan_login.py, which is not in the repository.
    # So the FIRST step of the morning failed every single day, printed
    # "could not start", and the run carried on -- which was correct
    # behaviour hiding a stale instruction. RUN_SCHEDULE.md still tells
    # him to type it by hand at 08:30 as well.
    #
    # It is obsolete rather than lost. core/dhan_auth.py (11 August)
    # mints a fresh 24-hour token over TOTP at startup:
    #
    #     main.py:194   dhan_token = dhan_auth.access_token() or ...
    #
    # so there is nothing for him to do in the morning, which was the
    # entire point of building it. DHAN_TOTP_SECRET, DHAN_CLIENT_ID and
    # DHAN_PIN are all set in .env and the fallback is the token
    # already there.
    #
    # Replaced with the CHECK, not removed. "The bot mints its own
    # token" is only comforting if somebody confirms it worked -- and a
    # dead token is the one failure that stops the whole session.
    ("token", "Check the Dhan access token is live "
              "(main.py mints its own -- this only confirms it)",
     ["tools/dhan_token_check.py"], False),
    ("telegram", "Read every channel message since the last run",
     ["tools/telegram_catchup.py", "--apply"], True),
    ("universe", "Decide which stocks are tradeable today",
     ["tools/morning_universe.py"], False),
    ("verify", "Check every security id against Dhan's own master",
     ["tools/verify_master_database.py"], False),
    ("brief", "The overnight picture",
     ["tools/premarket_brief.py"], False),
]

# preopen_gaps is NOT here. NSE fixes opening prices between 09:08 and
# 09:12, so running it with the rest at 08:30 returns an empty table --
# which is exactly the mistake the first written schedule made.
LATER = ("09:12", "py tools/preopen_gaps.py",
         "NSE fixes opening prices 09:08-09:12. Earlier returns nothing.")


def _line():
    decision("=" * 70)


def run(step):
    name, what, argv, needs_telegram = step
    if needs_telegram:
        busy, who = held_by_another()
        if busy:
            warn(f"  SKIPPED {name}: a Telegram reader is already running "
                 f"({who}). Nothing was read, nothing was harmed.")
            return name, "skipped", 0.0

    decision("")
    decision(f"  {name.upper():10} {what}")
    decision(f"             {PY} {' '.join(argv)}")
    started = time.time()
    try:
        code = subprocess.call([PY] + argv)
    except Exception as exc:                               # noqa: BLE001
        warn(f"  {name} could not start ({exc}).")
        return name, "error", time.time() - started
    took = time.time() - started
    if code == 0:
        return name, "ok", took
    # A failed step must never stop the morning. verify exits non-zero
    # when the master is dirty, which is CORRECT and still leaves four
    # other steps worth running.
    warn(f"  {name} exited {code} after {took / 60:.1f} min. "
         f"MOVING ON -- one failed tool does not stop the morning.")
    return name, f"exit {code}", took


def main(only=None, skip=None):
    _line()
    decision("  MORNING -- everything before the open, in order")
    decision(f"  pid {os.getpid()}. This does NOT start main.py or the "
             f"collector.")
    _line()

    chosen = [s for s in STEPS
              if (not only or s[0] in only) and s[0] not in (skip or set())]
    if not chosen:
        warn("  Nothing to run.")
        return

    results = []
    for step in chosen:
        results.append(run(step))

    decision("")
    _line()
    decision("  DONE")
    for name, how, took in results:
        decision(f"    {how:9} {name:10} {took / 60:5.1f} min")
    failed = [n for n, how, _ in results if how not in ("ok", "skipped")]
    _line()
    if failed:
        warn(f"  {len(failed)} step(s) did not finish: {', '.join(failed)}")
        warn(f"  Re-run just those:  {PY} tools/morning.py "
             f"--only {','.join(failed)}")
    decision("")
    decision("  NOW START THE TWO THAT KEEP RUNNING, one terminal each:")
    decision(f"      Terminal 1   {PY} main.py")
    decision(f"      Terminal 2   {PY} tools/collector.py")
    decision("")
    decision(f"  AND AT {LATER[0]}:  {LATER[1]}")
    decision(f"      {LATER[2]}")
    _line()


def _csv(flag):
    if flag not in sys.argv:
        return None
    at = sys.argv.index(flag)
    if at + 1 >= len(sys.argv):
        return None
    return {x.strip() for x in sys.argv[at + 1].split(",") if x.strip()}


if __name__ == "__main__":
    main(only=_csv("--only"), skip=_csv("--skip") or set())
