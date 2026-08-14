"""
==========================================================
Is the bot actually ready to trade this morning?
==========================================================

    "i'll start that by 7:30 daily is that good enough to catchup &
     build watchlist by bot?"
                                -- operator, 6 August 2026

WHY THIS EXISTS
---------------
Measured on 6 August, against the real store:

    pre-open gapper card posted    09:08 IST
    seen by the bot                09:45 IST
    late by                        37 minutes
    market opened                  09:15

That card is what fills Row 1 of his watchlist -- the Excellent and
Great results. It arrived half an hour after the open. And at 09:11,
four minutes before the bell, the collector was still pulling posts
from 1 AUGUST, five days old: the catch-up ran 08:07 to 11:29, three
hours and twenty minutes, straight through the first two hours of
trading.

Nothing said so. The screen looked the same as a morning where
everything had arrived. An empty Row 1 is indistinguishable from a
morning with no good results, and he would have had no way to tell
which he was looking at.

He asked whether starting at 07:30 is early enough. The honest answer
is that it depends on the size of the backlog, which varies -- so the
answer should not be a guess he has to make daily. The bot knows
whether its own inputs arrived. It should say so.

WHAT IT CHECKS
--------------
    1. Is the feed alive at all -- anything stored recently?
    2. Has the catch-up FINISHED -- is it still storing old posts?
    3. Is today's pre-open gapper card in the store?
    4. Is the results calendar refreshed for today?

WHAT IT DOES WITH THE ANSWER
----------------------------
Nothing, on its own. It returns the state and the reasons. The
dashboard prints it; the arming switch refuses while it is not ready.
Both of those are decisions for the caller, and both are visible to
him -- a bot that silently declines to trade is as bad as one that
silently trades on nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3
from datetime import datetime, timedelta

TELEGRAM_DB = "data/telegram.db"
RESULTS_DB = "data/results_calendar.db"

# A message stored more recently than this means the poll is running.
FEED_ALIVE_MINUTES = 20

# If the newest thing being STORED was POSTED more than this long ago,
# the collector is still walking backwards through history rather than
# keeping up with the present.
CATCH_UP_STILL_RUNNING_HOURS = 6.0

# The gapper card lands about 09:08. Before that its absence is not a
# fault, so the check reports "not published yet" rather than failing.
# ---- IT LANDS 09:08-09:09, NOT 09:05. 7 August 2026. ----
#     "it will updated by 09:09 not 09:05"        -- operator
# At 09:05 this flipped to BLOCKING while the card was still on its
# way, and the bot would have refused to arm for three or four minutes
# every single morning for no reason at all. 09:12 leaves the card its
# normal arrival window plus a few minutes, and still catches a card
# that genuinely never came before the operator needs it.
GAPPER_DUE_AFTER = "09:12"


def _rows(db_path, sql, args=()):
    try:
        con = sqlite3.connect(db_path)
        got = con.execute(sql, args).fetchall()
        con.close()
        return got
    except Exception:                                      # noqa: BLE001
        return []


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("+00:00", ""))
    except Exception:                                      # noqa: BLE001
        return None


def check(now=None, telegram_db=TELEGRAM_DB, results_db=RESULTS_DB):
    """{"ready", "checks": [...], "blocking": [...]}.

    `ready` is True only when nothing is blocking. Every check carries
    its own sentence, because "not ready" without a reason is just a
    different kind of silence.
    """
    now = now or datetime.now()
    today = now.date().isoformat()
    checks = []

    def add(name, ok, detail, blocks=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail,
                       "blocks": bool(blocks and not ok)})

    # ---- 1. IS THE FEED ALIVE ----
    # ---- TIME-BOUNDED, SO IT CAN BE REPLAYED HONESTLY ----
    # The first version read the whole table. Replayed at 09:10 on
    # 6 August it reported "last message stored -523 min ago" and a
    # cheerful READY, because it was reading messages stored later
    # that afternoon. A check that cannot be tested against a past
    # morning is a check nobody can trust.
    cutoff = now.isoformat()
    got = _rows(telegram_db,
                "select max(seen_at) from messages where seen_at <= ?",
                (cutoff,))
    newest = _parse(got[0][0]) if got and got[0] else None
    if newest is None:
        add("feed alive", False,
            "nothing has ever been stored -- is tools/collector.py "
            "running?")
    else:
        quiet = (now - newest).total_seconds() / 60.0
        add("feed alive", quiet <= FEED_ALIVE_MINUTES,
            (f"last message stored {quiet:.0f} min ago"
             if quiet <= FEED_ALIVE_MINUTES else
             f"nothing stored for {quiet:.0f} min -- the collector is "
             f"not running, or it has stalled"))

    # ---- 2. HAS THE CATCH-UP FINISHED ----
    #
    # The tell is the POSTED time of what is being STORED right now.
    # While the walk is running the bot stores old material; once it
    # overlaps with what it already had, it stores only fresh posts.
    got = _rows(telegram_db,
                "select at from messages where seen_at <= ? "
                "order by seen_at desc limit 25", (cutoff,))
    ages = []
    for (at,) in got:
        posted = _parse(at)
        if posted is not None:
            ages.append((now - posted).total_seconds() / 3600.0)
    if not ages:
        add("catch-up finished", False, "no messages to judge from")
    else:
        # ---- THE MEDIAN, NOT THE MAX. 7 August 2026. ----
        # max() made ONE straggler from a quiet channel look like a
        # running catch-up: at 07:55 everything stored in the last
        # twenty minutes was current, and this said "104h old posts".
        # A real catch-up has MOST of its recent writes old, not one.
        ages.sort()
        oldest = ages[len(ages) // 2]
        still = oldest > CATCH_UP_STILL_RUNNING_HOURS
        add("catch-up finished", not still,
            (f"storing current material (newest batch is "
             f"{min(ages):.1f}h old)" if not still else
             f"STILL RECOVERING history -- it is storing posts up to "
             f"{oldest:.0f}h old. On 6 August this ran until 11:29."))

    # ---- 3. TODAY'S PRE-OPEN GAPPER CARD ----
    got = _rows(telegram_db,
                "select seen_at from messages where date(seen_at) = ? "
                "and (ocr_text like '%Gapping Up%' "
                "or ocr_text like '%Pre-Open Earnings Gapper%') "
                "and seen_at <= ? "
                "order by seen_at limit 1", (today, cutoff))
    if got:
        seen = _parse(got[0][0])
        add("pre-open gapper card", True,
            f"in the store, seen {seen.strftime('%H:%M') if seen else '?'}")
    elif now.strftime("%H:%M") < GAPPER_DUE_AFTER:
        # Not late, just not published yet. Not a fault, and not ready.
        add("pre-open gapper card", False,
            f"not published yet -- it lands about {GAPPER_DUE_AFTER}",
            blocks=False)
    else:
        add("pre-open gapper card", False,
            "NOT in the store. Row 1 of the watchlist -- the Excellent "
            "and Great results -- will be empty, and that will look "
            "exactly like a morning with no good results.")

    # ---- 4. RESULTS CALENDAR ----
    got = _rows(results_db,
                "select value from results_meta where key = 'last_refresh'")
    stamp = str(got[0][0]) if got and got[0] else None
    add("results calendar", stamp == today,
        (f"refreshed today" if stamp == today else
         f"last refreshed {stamp or 'never'} -- the bot will not know "
         f"which stocks report today"))

    blocking = [c for c in checks if c["blocks"]]
    return {"ready": not blocking, "checks": checks,
            "blocking": [c["name"] for c in blocking],
            "why_not": [c["detail"] for c in blocking]}


def one_line(state=None, now=None):
    """A single sentence for the terminal or the top of the screen."""
    state = state or check(now=now)
    if state["ready"]:
        return "[READY] Every morning input has arrived."
    return ("[NOT READY] " + "; ".join(state["why_not"])) or "[NOT READY]"


# ===================================================================
# DURING THE SESSION -- the checklist is not only a door
# ===================================================================
#
#     "so if the collector dies at 11 o'clock while the bot is already
#      trading, the bot keeps going ... should i build it? -- yes"
#                                       -- operator, 7 August 2026
#
# check() above runs when he ARMS the bot. After that nothing looked
# again. A collector that dies at 11:00 leaves the bot buying at 11:30
# on news that stopped arriving half an hour earlier, and the only
# sign is a red panel he may not be looking at.
#
# This is the running version. It asks ONE question -- is the feed
# still alive -- because that is the only morning check that can go
# from true to false during a session. The catch-up finishing and the
# gapper card arriving are one-way doors; they never un-happen.
#
# IT IS DELIBERATELY SLOW TO PANIC.
#
#     "if it's too twitchy -- say the collector pauses for 30 seconds
#      -- it could disarm you in the middle of a good move"
#
# The channels themselves go quiet for long stretches; a 20-minute
# silence at 14:00 is a normal afternoon, not a failure. So the guard
# needs the check to fail STRIKES_TO_DISARM times in a row, spaced by
# the caller's own loop, before it acts. One green check resets it to
# zero.
#
# AND IT NEVER TOUCHES AN OPEN POSITION. Disarming stops NEW entries.
# Stops, trails, targets and the circuit guard keep running on
# everything already held -- abandoning live positions because the
# news feed died would be a far worse failure than the one it guards
# against.

STRIKES_TO_DISARM = 3


def during_session(now=None, telegram_db=TELEGRAM_DB):
    """Is the feed still alive right now? {"ok", "why"}."""
    now = now or datetime.now()
    got = _rows(telegram_db,
                "select max(seen_at) from messages where seen_at <= ?",
                (now.isoformat(),))
    newest = _parse(got[0][0]) if got and got[0] else None
    if newest is None:
        return {"ok": False, "why": "nothing has ever been stored"}
    quiet = (now - newest).total_seconds() / 60.0
    if quiet <= FEED_ALIVE_MINUTES:
        return {"ok": True, "why": f"feed alive, {quiet:.0f} min ago"}
    return {"ok": False,
            "why": (f"no telegram message for {quiet:.0f} minutes -- the "
                    f"collector has stopped or stalled")}


class LiveGuard:
    """Watches the feed during the session and disarms if it dies.

    `disarm()` is injected rather than reaching into an Engine, so this
    can be driven in a test without one -- the class of bug that let
    the ranker sit unwired through 3,541 green tests.

    Never raises. It runs on the trading loop.
    """

    def __init__(self, disarm=None, say=None, strikes=STRIKES_TO_DISARM):
        self.disarm = disarm
        self.say = say
        self.strikes_needed = int(strikes)
        self.strikes = 0
        self.disarmed = False

    def poll(self, now=None, armed=True, telegram_db=TELEGRAM_DB):
        """Call once per loop. Returns the state it decided on."""
        if not armed:
            # Not trading -- nothing to protect, and the strike count
            # must not carry over into the next time he arms it.
            self.strikes = 0
            return {"acted": False, "strikes": 0, "ok": None}
        try:
            state = during_session(now=now, telegram_db=telegram_db)
        except Exception as exc:                           # noqa: BLE001
            return {"acted": False, "strikes": self.strikes,
                    "ok": None, "why": f"could not check ({exc})"}

        if state["ok"]:
            if self.strikes and self.say is not None:
                self.say(f"[GUARD] Feed recovered -- {state['why']}. "
                         f"Strike count reset.")
            self.strikes = 0
            return {"acted": False, "strikes": 0, "ok": True}

        self.strikes += 1
        if self.strikes < self.strikes_needed:
            if self.say is not None:
                self.say(f"[GUARD] {state['why']}. Strike "
                         f"{self.strikes} of {self.strikes_needed} -- "
                         f"still trading.")
            return {"acted": False, "strikes": self.strikes, "ok": False}

        acted = False
        if self.disarm is not None and not self.disarmed:
            try:
                self.disarm()
                acted = True
                self.disarmed = True
            except Exception as exc:                       # noqa: BLE001
                if self.say is not None:
                    self.say(f"[GUARD] COULD NOT DISARM ({exc}). Turn bot "
                             f"trading OFF on the dashboard NOW.")
        if self.say is not None and acted:
            self.say("=" * 62)
            self.say(f"  BOT TRADING SWITCHED OFF BY THE GUARD.")
            self.say(f"  {state['why']}.")
            self.say(f"  No new entries. Open positions keep their stops "
                     f"and trails.")
            self.say(f"  Restart py tools/collector.py, then arm it again "
                     f"from the dashboard.")
            self.say("=" * 62)
        return {"acted": acted, "strikes": self.strikes, "ok": False,
                "why": state["why"]}
