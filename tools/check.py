"""
==========================================================
py tools/check.py  --  is anything wrong, and what do I do?
==========================================================

    "i need to know how to check all of them ? if any error occured
     then what i need to do?"
                                -- operator, 7 August 2026

One command. It looks at everything that can be wrong on a trading
morning and, for each fault, prints the ONE thing to type.

It is deliberately not a health dashboard. He has a dashboard. This is
for the moment something looks wrong and he wants a straight answer
without reading logs.

Every line ends in either OK or an instruction. Nothing else.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = timezone(timedelta(hours=5, minutes=30))
OK, BAD, WAIT = "  OK  ", " FIX  ", " WAIT "

_problems = []


def line(state, name, detail, fix=None):
    print(f"[{state}] {name:<26} {detail}")
    if state == BAD and fix:
        _problems.append((name, fix))


def _q(db, sql, args=()):
    try:
        con = sqlite3.connect(db)
        got = con.execute(sql, args).fetchall()
        con.close()
        return got
    except Exception:                                      # noqa: BLE001
        return []


def main():
    now = datetime.now(IST).replace(tzinfo=None)
    print("=" * 68)
    print(f"  BOT CHECK   {now:%d %b %Y  %H:%M} IST")
    print("=" * 68)

    # ---- 1. THE TOKEN ----
    try:
        import base64
        import json

        from config import DHAN_ACCESS_TOKEN
        parts = str(DHAN_ACCESS_TOKEN or "").split(".")
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        exp = json.loads(base64.urlsafe_b64decode(pad)).get("exp")
        dies = datetime.fromtimestamp(exp, IST).replace(tzinfo=None)
        if dies <= now:
            line(BAD, "Dhan token", "EXPIRED",
                 "generate a new token, then restart main.py")
        elif dies < now.replace(hour=15, minute=30):
            line(BAD, "Dhan token", f"dies {dies:%H:%M} -- mid-session",
                 "generate a new token now, before you arm the bot")
        else:
            line(OK, "Dhan token", f"good until {dies:%d %b %H:%M}")
    except Exception as exc:                               # noqa: BLE001
        line(BAD, "Dhan token", f"unreadable ({exc})",
             "generate a new token")

    # ---- 2. THE COLLECTOR ----
    got = _q("data/telegram.db", "select max(seen_at) from messages")
    if not got or not got[0][0]:
        line(BAD, "Telegram collector", "nothing has ever been stored",
             "py tools/collector.py")
    else:
        last = datetime.fromisoformat(str(got[0][0]))
        quiet = (now - last).total_seconds() / 60.0
        if quiet > 20:
            line(BAD, "Telegram collector",
                 f"silent for {quiet:.0f} min",
                 "py tools/collector.py   (it is not running)")
        else:
            line(OK, "Telegram collector", f"last message {quiet:.0f} min ago")

    # ---- 3. THE CATCH-UP ----
    got = _q("data/telegram.db",
             "select at from messages order by seen_at desc limit 25")
    if got:
        ages = []
        for (at,) in got:
            try:
                posted = datetime.fromisoformat(
                    str(at).replace("+00:00", "")) + timedelta(hours=5,
                                                               minutes=30)
                ages.append((now - posted).total_seconds() / 3600.0)
            except Exception:                              # noqa: BLE001
                continue
        # The MEDIAN age of what is being stored, not the max -- one
        # old post from a quiet channel is not a running catch-up.
        ages.sort()
        mid = ages[len(ages) // 2] if ages else 0
        if ages and mid > 6:
            line(WAIT, "Catch-up",
                 f"still recovering (typically {mid:.0f}h old posts)",
                 None)
        elif ages:
            line(OK, "Catch-up", "finished -- storing current material")

    # ---- 4. TODAY'S GAPPER CARD ----
    today = now.date().isoformat()
    got = _q("data/telegram.db",
             "select seen_at from messages where date(seen_at)=? "
             "and (ocr_text like '%Gapping Up%' "
             "or ocr_text like '%Pre-Open Earnings Gapper%') limit 1",
             (today,))
    if got:
        line(OK, "Pre-open gapper card", f"in, seen {str(got[0][0])[11:16]}")
    elif now.strftime("%H:%M") < "09:12":
        # It lands 09:08-09:09. Before 09:12 its absence is not a fault.
        line(WAIT, "Pre-open gapper card", "not published yet (~09:09)")
    else:
        line(BAD, "Pre-open gapper card", "NOT in the store",
             "check the collector is running -- Row 1 will be empty")

    # ---- 5. THE RESULTS CALENDAR ----
    got = _q("data/results_calendar.db",
             "select value from results_meta where key='last_refresh'")
    stamp = str(got[0][0]) if got else None
    if stamp == today:
        n = _q("data/results_calendar.db",
               "select count(distinct symbol) from results_events "
               "where results_date=?", (today,))
        line(OK, "Results calendar",
             f"refreshed -- {n[0][0] if n else 0} companies report today")
    else:
        line(BAD, "Results calendar", f"last refreshed {stamp or 'never'}",
             "py tools/refresh_calendars.py")

    # ---- 6. THE BOT'S BOOK vs REALITY ----
    try:
        import json
        state = json.load(open("data/session_state.json"))
        held = list((state.get("open_positions") or {}))
        if held:
            line(WAIT, "Bot's book", f"{len(held)} position(s): "
                 f"{', '.join(held[:4])}",
                 None)
            print("        -> if you closed any of these yourself, the bot "
                  "clears them on its next sync")
        else:
            line(OK, "Bot's book", "empty")
    except Exception:                                      # noqa: BLE001
        line(OK, "Bot's book", "no saved state (fresh start)")

    # ---- 7. IS THE WATCHLIST GOING TO HAVE ANYTHING ----
    try:
        from core import watchlist_builder as W
        graded = len(W.graded_symbols() or {})
        reporting = len(W.reporting_on(today) or {})
        if graded == 0 and now.strftime("%H:%M") > "09:15":
            line(BAD, "Watchlist row 1", "no graded results found",
                 "the gapper card has not been read -- check the collector")
        else:
            line(OK, "Watchlist rows",
                 f"{graded} graded, {reporting} reporting today")
    except Exception as exc:                               # noqa: BLE001
        line(BAD, "Watchlist", f"could not build ({exc})",
             "tell Claude -- this one is a code fault, not a setup fault")

    # ---- THE ANSWER ----
    print("=" * 68)
    if not _problems:
        print("  NOTHING TO FIX. Open the dashboard and press the switch.")
    else:
        print(f"  {len(_problems)} thing(s) to fix, in order:\n")
        for i, (name, fix) in enumerate(_problems, 1):
            print(f"   {i}. {name}")
            print(f"      {fix}\n")
    print("=" * 68)
    return 0 if not _problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
