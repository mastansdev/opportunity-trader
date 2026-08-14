"""
==========================================================
One command, run at night, so the morning is short
==========================================================
    py tools/nightly.py            run everything
    py tools/nightly.py --dry      list the steps, run nothing
    py tools/nightly.py --only telegram,universe

    "every night we will complete the necessary works, & in morning
     only small pending can be completed by bot within 15-20 mins."
                                    -- operator, 2 August 2026

WHAT WAS WRONG WITH DOING IT IN THE MORNING
-------------------------------------------
Measured on the real store, the channels deliver about SEVEN messages
a minute of OCR work, and 34% of everything they send arrives outside
market hours. A weekend backlog is 250-400 posts -- forty to sixty
minutes. Started at 08:00 that is not "before the open", it is still
running at 09:15 while the chips fill in underneath him.

Everything below can be finished by 22:00 the night before. What is
left for the morning is the token, the route, and whatever the
channels posted between midnight and 09:00 -- minutes, not an hour.

THE ORDER IS NOT ARBITRARY
--------------------------
    telegram   the longest job, and everything after it wants the
               events it files
    history    today's bars, from today's bhavcopy, published ~18:00
    discover   names the channels used that we cannot identify --
               needs telegram to have run first
    classify   fills in what discover just added, so the universe
               step can consider them at all
    verify     Dhan's own security ids, before anything trades on them
    universe   LAST, because it decides YES/NO using everything above

WHAT IS DELIBERATELY NOT HERE
-----------------------------
    the access token   Dhan's lasts 24 hours. Generated at night it
                       dies mid-session. Morning, every morning.
    proxy_check        the static IP route has to be true AT the open,
                       not eight hours before it.
    premarket_brief    US close, Asia, crude. Meaningless at 22:00 IST
                       -- half of it has not happened yet.

Every step is a SUBPROCESS. One tool crashing must not take the rest
of the night with it, and a step that fails is reported and skipped
rather than stopping the run -- the whole point is to wake up to a
list of what did NOT happen, not to a run that stopped at step two.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.runlock import held_by_another                   # noqa: E402

PY = sys.executable or "python"

# (key, what it is, argv, why the morning would be worse without it)
STEPS = [
    ("telegram", "Read every channel message since the last run",
     ["tools/telegram_catchup.py", "--apply"],
     "the long one -- about 7 messages a minute of OCR. A weekend "
     "backlog is 40-60 minutes, and it is the reason the morning "
     "used to overrun."),

    ("history", "Store today's daily bars",
     ["tools/build_daily_history.py"],
     "the bot cannot see yesterday without these."),

    # ---- THE ONE HE ASKS FOR. 5 August 2026. ----
    #
    #     "CTRL+C main.py closed . no score card found ..."
    #
    # This chain built today's bars and then never looked at them. The
    # scorecard lived only inside main.py's shutdown, so the one
    # question Phase 1 exists to answer -- did the picks make money --
    # could only be reached down a single path, and that path turned
    # out to be the one he never takes.
    #
    # Straight after "history" because it reads what history writes. If
    # the bhavcopy is not out yet, verify_picks says so and this chain
    # carries on; nothing below depends on it.
    ("score", "Score today's picks against today's closes",
     ["tools/verify_picks.py"],
     "the whole point of Phase 1. Without it the bot records 27 picks "
     "a day and nobody ever finds out whether they were right."),

    ("liquidity", "Measure how much money trades in each stock",
     ["tools/measure_liquidity.py"],
     "decides which names lead a sector list before anything has "
     "ticked. Without it the first seconds of a shock offered 63MOONS "
     "for IT instead of TCS."),

    # ---- IT WAS BUILT AND NEVER SCHEDULED. 12 August 2026. ----
    #
    #     "DELIVER % - YES"                  -- operator, 8 August
    #
    # tools/fetch_delivery.py was written that day, backfilled a month,
    # and then nothing ever ran it again. On 12 August data/delivery.db
    # stopped at 7 August -- three sessions stale -- while the dashboard
    # went on printing "34% delivered, usual 48%" beside live prices as
    # if it were today's. Stale evidence presented as current is worse
    # than a blank panel, because it is believed.
    #
    # Delivery comes from NSE's sec_bhavdata_full, a different file from
    # the UDiFF bhavcopy "history" fetches above, so this cannot ride on
    # that step. Placed after it because both want the same archive host
    # and there is no reason to ask twice at once.
    #
    # Weekends and holidays have no file. fetch_delivery.py treats that
    # as normal and exits clean, so this never fails the chain.
    ("delivery", "Pull NSE's delivery percentages",
     ["tools/fetch_delivery.py"],
     "churn versus conviction. core/delivery.py needs about ten "
     "sessions before it will say anything at all, so a gap here is "
     "not visible for a fortnight -- which is how it went unnoticed "
     "for four days."),

    ("discover", "Find stocks the channels named that we cannot identify",
     ["tools/discover_stocks.py", "--apply"],
     "an unidentifiable stock has its results collected and attached "
     "to nothing."),

    ("classify", "Fill in the sector for anything discover just added",
     ["tools/complete_master.py", "--apply"],
     "a row with no SECTOR is blocked -- not by a market rule, by an "
     "empty cell."),

    ("verify", "Check every security id against Dhan's own master",
     ["tools/verify_master_database.py"],
     "on 31 July this found six wrong ids. One would have bought a "
     "different company."),

    ("universe", "Decide which stocks are tradeable tomorrow",
     ["tools/morning_universe.py"],
     "LAST, because it reads everything above. Run after 16:00 it "
     "builds the list for the NEXT session, ex-dates and all."),

    # ---- A SILENT OUTAGE RAN FOR A WEEK. 12 August 2026. ----
    #
    # config.AI_ENABLED went False on 10 August. From the 6th to the
    # 11th the bot stored 1,561 news stories and reasoned about NONE of
    # them -- every one a keyword link with direction UNKNOWN, which
    # core/ranker.py refuses by name. The ranked entry lane had no
    # reasons for a week and nothing said so; main.py's startup line
    # printed "reasoning ON" the whole time.
    #
    # Delivery data did the same thing four days earlier, for a
    # different reason: fetch_delivery.py existed and was never
    # scheduled, so data/delivery.db sat three sessions behind while the
    # dashboard printed it beside live prices.
    #
    # Both are the same failure: a store that keeps LOOKING healthy --
    # growing, fresh, no errors -- while the thing that gives it meaning
    # has stopped. No row count can catch that.
    #
    # This is a REPORT, not a step that changes anything. It exits
    # non-zero when a store is unreadable, has gone stale, or news is
    # arriving unreasoned, and run() above prints that in the summary
    # and MOVES ON -- so it can never stop the night, only make the
    # problem visible on the morning he reads it.
    ("health", "Is every store readable, fresh, and understood?",
     ["tools/knowledge_report.py"],
     "read-only. Exits non-zero on a silent data outage -- the failure "
     "mode where everything looks fine because the numbers keep "
     "growing."),
]

MORNING_ONLY = [
    ("the Dhan access token", "lasts 24 hours -- one generated tonight "
                              "dies part-way through tomorrow"),
    ("py tools/proxy_check.py", "the static IP route has to be true AT "
                                "the open, not eight hours before"),
    ("py tools/premarket_brief.py", "US close, Asia, crude -- half of it "
                                    "has not happened at 22:00 IST"),
    ("py tools/telegram_catchup.py --apply", "again, briefly, for whatever "
                                             "arrived overnight"),
]


def run(step, timeout=3600):
    key, what, argv, _ = step
    decision("-" * 68)
    decision(f"  {key.upper():<10} {what}")
    decision(f"             {PY} {' '.join(argv)}")
    started = time.time()
    try:
        proc = subprocess.run([PY] + argv, timeout=timeout)
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        warn(f"  {key}: still running after {timeout // 60} minutes -- "
             f"killed. Whatever it had already written is kept.")
        return key, False, time.time() - started, "timed out"
    except Exception as exc:                               # noqa: BLE001
        warn(f"  {key}: could not start ({exc}).")
        return key, False, time.time() - started, str(exc)
    took = time.time() - started
    if not ok:
        warn(f"  {key}: exited {proc.returncode} after {took / 60:.1f} min. "
             f"MOVING ON -- one failed tool does not stop the night.")
    return key, ok, took, "" if ok else f"exit {proc.returncode}"


#: Everything this script answers to. Anything else is a typo, and a
#: typo here is not harmless -- see _reject_unknown_flags().
KNOWN_FLAGS = ("--only", "--dry")


def _reject_unknown_flags(argv):
    """Refuse to run on a flag we do not recognise.

    ---- A TYPO STARTED A LIVE RUN. 12 August 2026. ----

    The dry-run switch is `--dry`. Someone typed the far more common
    `--dry-run`, and the old parsing was `dry = "--dry" in argv` -- an
    exact-match membership test, so `--dry-run` was not `--dry`, was
    not anything else either, and was silently discarded. dry stayed
    False and the FULL chain ran for real: telegram_catchup --apply
    walking every channel, then history, score, liquidity, discover,
    classify --apply, verify, universe.

    It had to be killed by hand three minutes in, and left a stale
    reader lock behind that core/runlock.py holds for two hours because
    it ages locks out rather than checking whether the pid is alive.

    Nothing in this file's own design was wrong. It simply assumed the
    person running it had typed what they meant. An unknown flag is
    now the one thing that stops the night before it starts.
    """
    unknown = [a for a in argv
               if a.startswith("-")
               and not any(a == f or a.startswith(f + "=")
                           for f in KNOWN_FLAGS)]
    if not unknown:
        return None
    warn("-" * 68)
    warn(f"  I do not know this: {' '.join(unknown)}")
    warn("")
    warn("  Nothing has been run. The flags are:")
    warn("")
    warn("      --dry                  list the steps, execute nothing")
    warn("      --only=a,b             run only those steps")
    warn("")
    warn(f"  Steps: {', '.join(s[0] for s in STEPS)}")
    warn("-" * 68)
    return 2


def main(argv):
    bad = _reject_unknown_flags(argv)
    if bad is not None:
        return bad

    only = None
    for arg in argv:
        if arg.startswith("--only"):
            value = arg.split("=", 1)[1] if "=" in arg else (
                argv[argv.index(arg) + 1] if argv.index(arg) + 1 < len(argv)
                else "")
            only = {s.strip().lower() for s in value.split(",") if s.strip()}
    dry = "--dry" in argv

    steps = [s for s in STEPS if only is None or s[0] in only]

    decision("=" * 68)
    decision(f"  NIGHTLY -- {datetime.now():%a %d %b %Y, %H:%M}")
    decision("=" * 68)

    # ---- IS A TELEGRAM READER ALREADY RUNNING? 2 August 2026 ----
    #
    #     "shall i run this py tools/nightly.py now? in one terminal
    #      py tools/telegram_catchup.py --apply is running right now"
    #
    # Told here rather than left for the telegram step to discover
    # twenty seconds in, because the answer changes what he does: the
    # OTHER five steps are perfectly safe to run alongside a catch-up,
    # and there is no reason to make him wait for all of them.
    busy, who = held_by_another()
    if busy and any(s[0] == "telegram" for s in steps):
        warn("-" * 68)
        warn(f"  A Telegram reader is ALREADY RUNNING: {who}")
        warn("  Two of them share one session and one store and both "
             "end up damaged.")
        warn("")
        warn("  Either wait for it to finish and re-run this, or run "
             "everything else now:")
        warn(f"      {PY} tools/nightly.py --only "
             + ",".join(s[0] for s in STEPS if s[0] != "telegram"))
        return 2
    if datetime.now().hour < 16:
        warn("  It is before 16:00. Today's bhavcopy is not published "
             "yet, so `universe` and `history` will use the LAST "
             "session's data. Run this after the close.")

    if dry:
        for key, what, cmd, why in steps:
            decision(f"  {key:<10} {what}")
            decision(f"             {' '.join(cmd)}")
            decision(f"             {why}")
        decision("-" * 68)
        decision("  DRY RUN -- nothing was executed.")
        return 0

    results = [run(step) for step in steps]

    decision("=" * 68)
    decision("  DONE")
    decision("=" * 68)
    total = sum(r[2] for r in results)
    for key, ok, took, note in results:
        mark = "ok " if ok else "FAILED"
        decision(f"  {mark:<7}{key:<11}{took / 60:>6.1f} min"
                 + (f"   {note}" if note else ""))
    decision(f"  {'':<7}{'total':<11}{total / 60:>6.1f} min")

    failed = [r[0] for r in results if not r[1]]
    if failed:
        warn("")
        warn(f"  {len(failed)} step(s) did NOT finish: {', '.join(failed)}")
        warn(f"  Re-run just those:  py tools/nightly.py --only "
             f"{','.join(failed)}")

    decision("")
    decision("  STILL YOURS IN THE MORNING -- none of these can be done "
             "tonight:")
    for what, why in MORNING_ONLY:
        decision(f"      {what}")
        decision(f"          {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
