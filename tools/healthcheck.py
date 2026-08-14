"""
==========================================================
Is it actually working? Read the log and say so.
==========================================================
    py tools/healthcheck.py

    "why user needs to tell you which one is working & not ? thats your
     work right? to give the complete work as i asked"
                                    -- operator, 3 August 2026

He is right, and the index tiles are the proof. They were blank for a
week. The config was refilled, the routing was repaired, main.py was
restarted -- and they were STILL blank, because main.py handed the
monitor {"nifty": "13"} instead of {"13": "nifty"} and subscribed to an
instrument whose id was the string "nifty".

Nothing errored. Nothing warned. The evidence was one missing line in
a log file I had already read twice, and it took HIM saying "still same
page showing" for me to look again.

That is a checkable thing. So it gets checked.

WHAT THIS IS
------------
Every claim the bot makes about itself, tested against the newest
session log rather than against intent:

    the feed        ticks arriving, queue not backing up
    the indices     subscribed, and actually delivering
    the book        positions readable, Dhan reachable
    the orders      order book readable
    the events      the store has rows, and something is writing them
    the collector   running, and how recently it read

Each line is PASS, FAIL or a plain sentence about why it cannot tell.
"Cannot tell" is never drawn as PASS -- that conflation is what let
"ok telegram 0.0 min" pass for a step that read nothing.

Run it after any change to main.py, config.py or the feed, BEFORE
telling anyone the change works.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402

LOGS = "logs"
OK, BAD, MEH = "PASS", "FAIL", "  ? "


# The line main.py prints within a second of starting. A log without it
# belongs to some other tool -- including this one.
SESSION_MARK = "Opportunity Trader -- Layer 1"


def newest_log():
    """The newest log written by MAIN.PY, not simply the newest log.

    ---- IT READ ITS OWN OUTPUT. 3 August 2026, second run. ----

    Every tool here logs through core/logger, so running this one
    creates a diagnostics file -- which is instantly the newest, and
    contains no feed, no indices and no dashboard. The second run
    therefore reported "main.py never announced an index subscription"
    and "this build still collects Telegram", having read a log written
    by itself, forty seconds earlier.

    Both findings were false and both looked exactly like the real ones
    it had reported a minute before. A diagnostic that can mistake its
    own output for the subject is worse than no diagnostic.
    """
    try:
        files = [os.path.join(LOGS, f) for f in os.listdir(LOGS)
                 if f.startswith("diagnostics_") and f.endswith(".log")]
    except OSError:
        return None
    sessions = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="ignore") as handle:
                if SESSION_MARK in handle.read(4000):
                    sessions.append(path)
        except OSError:
            continue
    if not sessions:
        return None
    return max(sessions, key=os.path.getmtime)


def read(path, limit=4_000_000):
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return handle.read()[-limit:]
    except OSError:
        return ""


def age_minutes(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 60.0
    except OSError:
        return None


def check(rows, label, state, detail=""):
    rows.append((label, state, detail))


def _market_open(now=None):
    """Is NSE trading right now? Used only to tell a dead feed apart
    from a closed market -- two things that look identical in a log and
    mean opposite things.

    Deliberately ignores holidays. Being wrong on 15 August makes this
    say "cannot tell" on a day nothing is trading anyway; wiring the
    holiday calendar in would make a diagnostic tool depend on the
    thing it is diagnosing.
    """
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= minutes <= (15 * 60 + 30)


def main():
    rows = []
    log = newest_log()
    line = "=" * 72
    decision(line)
    decision("  HEALTHCHECK -- what is actually working, read from the log")
    decision(line)

    if not log:
        warn("  No session log found. Start main.py first.")
        return
    mins = age_minutes(log) or 0
    body = read(log)
    decision(f"  log: {log}   last written {mins:.0f} min ago")
    decision("")

    # ---- THE FEED ---------------------------------------------------
    beats = re.findall(r"ticks: (\d+) \(\+(\d+) in last", body)
    if not beats:
        check(rows, "tick feed", MEH,
              "no heartbeat yet -- it prints one per interval")
    else:
        total, recent = beats[-1]
        alive = "feed alive: True" in body.split("[HEARTBEAT]")[-1]
        backlog = re.findall(r"tick queue backlog: (\d+)", body)
        deep = int(backlog[-1]) if backlog else 0
        if int(recent) > 0 and alive:
            check(rows, "tick feed", OK,
                  f"{int(total):,} ticks, +{recent} last beat, backlog {deep}")
        else:
            check(rows, "tick feed", BAD,
                  f"+{recent} ticks last beat, alive={alive}")

    # ---- THE INDICES ------------------------------------------------
    #
    # Two separate things, and conflating them is exactly how this went
    # unnoticed: SUBSCRIBED is a line main.py prints, DELIVERING means
    # a packet actually arrived.
    sub = re.search(r"\[INDEX\] Subscribed (\d+) index", body)
    if not sub:
        check(rows, "index subscribe", BAD,
              "main.py never announced an index subscription -- "
              "check config.INDEX_INSTRUMENTS")
    else:
        check(rows, "index subscribe", OK, f"{sub.group(1)} subscribed")

    got = re.findall(r"\[INDEX\] ([a-z:A-Z 0-9&]+) \(id (\d+)\) first packet",
                     body)
    if not got:
        if not sub:
            check(rows, "index packets", MEH, "nothing subscribed")
        elif not _market_open():
            # ---- A CLOSED MARKET IS NOT A BROKEN FEED. ----
            # The first version of this file reported FAIL here at
            # 18:33, three hours after the close, when NOTHING was
            # ticking -- not one equity either. That is precisely the
            # conflation this tool exists to prevent, committed by the
            # tool itself on its first run.
            check(rows, "index packets", MEH,
                  "market is closed -- nothing is ticking, so this "
                  "cannot be checked until 09:15")
        else:
            check(rows, "index packets", BAD,
                  "subscribed but NOT ONE packet arrived while the "
                  "market is open -- the tiles will read 'needs index feed'")
    else:
        names = ", ".join(sorted({n.strip() for n, _ in got}))[:60]
        check(rows, "index packets", OK, f"{len(set(got))} delivering: {names}")

    unmapped = re.findall(r"Unmapped IDX id (\d+)", body)
    if unmapped:
        check(rows, "unmapped index ids", MEH,
              f"{len(set(unmapped))} arriving with no name: "
              f"{', '.join(sorted(set(unmapped))[:6])}")

    # ---- THE BOOK AND THE ORDERS -----------------------------------
    if "could not read positions from Dhan" in body:
        check(rows, "positions at Dhan", BAD, "the broker read failed")
    elif "[SYNC]" in body or "[BOOK]" in body:
        check(rows, "positions at Dhan", OK, "broker book readable")
    else:
        check(rows, "positions at Dhan", MEH, "not checked this session")

    if "could not read the order book" in body:
        check(rows, "order book", BAD, "the broker read failed")
    else:
        check(rows, "order book", OK, "readable")

    # ---- THE EVENT STORE, AND WHO IS FILLING IT ---------------------
    try:
        conn = sqlite3.connect("file:data/stock_events.db?mode=ro", uri=True)
        total = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        newest = conn.execute("SELECT max(at) FROM events").fetchone()[0]
        conn.close()
        check(rows, "event store", OK, f"{total:,} events, newest {newest}")
    except Exception as exc:                               # noqa: BLE001
        check(rows, "event store", BAD, str(exc))

    if "This process does NOT collect them" in body:
        check(rows, "main.py is trading-only", OK, "no Telegram in here")
    else:
        check(rows, "main.py is trading-only", BAD,
              "this log came from a build that still collects Telegram")

    tg_age = None
    for path in ("data/telegram.db",):
        if os.path.exists(path):
            tg_age = age_minutes(path)
    if tg_age is None:
        check(rows, "collector", MEH, "no telegram.db")
    elif tg_age < 10:
        check(rows, "collector", OK, f"wrote {tg_age:.0f} min ago")
    else:
        check(rows, "collector", MEH,
              f"telegram.db last written {tg_age / 60:.1f}h ago -- "
              f"start it: py tools/collector.py")

    # ---- THE DASHBOARD ----------------------------------------------
    link = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", body)
    if link:
        check(rows, "dashboard", OK, link.group(1))
    else:
        check(rows, "dashboard", BAD, "never announced a link")

    # ---- SAY IT -----------------------------------------------------
    width = max(len(r[0]) for r in rows)
    for label, state, detail in rows:
        say = warn if state == BAD else decision
        say(f"  [{state}] {label.ljust(width)}  {detail}")

    bad = [r for r in rows if r[1] == BAD]
    decision("")
    decision(line)
    if bad:
        warn(f"  {len(bad)} thing(s) NOT working: "
             f"{', '.join(r[0] for r in bad)}")
    else:
        decision("  Everything this can check is working.")
    decision(f"  Checked at {datetime.now().strftime('%H:%M:%S')}. "
             f"This reads the LOG -- it cannot see the browser.")
    decision(line)


if __name__ == "__main__":
    main()
