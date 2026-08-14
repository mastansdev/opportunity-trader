"""
==========================================================
The dates that move the whole market at once
==========================================================

    "dashboard is not equipped with all my requirements. it doesn't
     know when FED meeting, RBI Meeting will happen"
                                    -- operator, 29 July 2026

WHY IT MATTERS TO THIS BOT SPECIFICALLY
---------------------------------------
Not for pausing. The operator settled that argument himself, and he
was right:

    "FED meeting will be completed by our market opening and we will
     get complete picture before market moves as we are not trading
     live markets & no positions held, then whats our problem now?"

An FOMC statement lands at 2pm ET, which is 11:30pm IST. He is flat
and asleep. There is nothing to pause -- the news is fully priced by
the time NSE opens, and a rule that stopped trading on FOMC day would
only have cost money.

RBI is the opposite and this is the real point. The MPC decision is
announced around 10:00 IST -- **inside** the session, with positions
open. **5 August 2026 is two days after this bot goes live.**

So this module states a fact and stops. It does not block, size, or
score anything. Knowing "RBI decides in 55 minutes" is what lets the
operator decide; deciding for him is not this module's business.

WHY THE DATES ARE HARD-CODED
----------------------------
They are published a year ahead and never move except in an
emergency. A scraper for eight known dates would be a network call
that can fail, at 09:00, to learn something already certain. When the
list runs out the panel says so, loudly, rather than quietly showing
nothing -- an empty calendar and a calendar that has expired must
never look the same.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date, datetime

# --- US Federal Reserve, FOMC 2026 -------------------------------
# Decision day is the SECOND date. Statement 14:00 ET = 23:30 IST,
# i.e. after our close and before our next open.
FOMC_2026 = [
    (date(2026, 1, 27), date(2026, 1, 28)),
    (date(2026, 3, 17), date(2026, 3, 18)),
    (date(2026, 4, 28), date(2026, 4, 29)),
    (date(2026, 6, 16), date(2026, 6, 17)),
    (date(2026, 7, 28), date(2026, 7, 29)),
    (date(2026, 9, 15), date(2026, 9, 16)),
    (date(2026, 10, 27), date(2026, 10, 28)),
    (date(2026, 12, 8), date(2026, 12, 9)),
]

# --- RBI Monetary Policy Committee, FY 2026-27 -------------------
# Decision announced on the LAST day, around 10:00 IST -- during our
# session, with positions open. This is the one that matters.
RBI_MPC_FY27 = [
    (date(2026, 4, 6), date(2026, 4, 8)),
    (date(2026, 6, 3), date(2026, 6, 5)),
    (date(2026, 8, 3), date(2026, 8, 5)),
    (date(2026, 10, 5), date(2026, 10, 7)),
    (date(2026, 12, 2), date(2026, 12, 4)),
    (date(2027, 2, 3), date(2027, 2, 5)),
]

# --- India CPI ---------------------------------------------------
# MoSPI publishes around the 12th at 16:00 IST -- after our close.
INDIA_CPI_2026 = [date(2026, m, 12) for m in range(1, 13)] + \
                 [date(2027, 1, 12), date(2027, 2, 12)]

EVENTS = [
    {"key": "fomc", "name": "US Fed (FOMC)", "at": "23:30 IST",
     "during_session": False,
     "note": "Statement lands overnight. Priced in before NSE opens.",
     "dates": [d[1] for d in FOMC_2026]},
    {"key": "rbi", "name": "RBI policy (MPC)", "at": "~10:00 IST",
     "during_session": True,
     "note": "DECIDED DURING OUR SESSION, with positions open.",
     "dates": [d[1] for d in RBI_MPC_FY27]},
    {"key": "cpi", "name": "India CPI", "at": "16:00 IST",
     "during_session": False,
     "note": "Published after our close.",
     "dates": INDIA_CPI_2026},
]


def _today():
    return datetime.now().date()


def next_event(event, today=None):
    """The next occurrence of one event, or None if the list ran out."""
    today = today or _today()
    upcoming = [d for d in event["dates"] if d >= today]
    if not upcoming:
        return None
    when = min(upcoming)
    days = (when - today).days
    return {
        "key": event["key"],
        "name": event["name"],
        "date": when.isoformat(),
        "at": event["at"],
        "days_away": days,
        "today": days == 0,
        "during_session": event["during_session"],
        "note": event["note"],
        # The one line the operator reads at a glance.
        "when": ("TODAY" if days == 0 else
                 "tomorrow" if days == 1 else
                 f"in {days} days"),
    }


def last_event(event, today=None, within_days=7):
    """The most recent occurrence within the last `within_days`, or None.

    WHY THIS HAD TO EXIST -- 30 July 2026.

        "last night FED meeting but today bot doesn't know anything
         about that & why markets are weakly opened & trading
         negatively"                    -- operator

    It DID know. FOMC_2026 above holds (2026-07-28, 2026-07-29) and the
    decision landed at 23:30 IST on the 29th. But next_event() filters
    `d >= today`, so on the 30th that meeting was dropped and the panel
    showed the NEXT one -- 16 September, 48 days away.

    A calendar that only looks forward is useless for the one question
    asked at the open: "what happened overnight that explains this
    tape?" The event that moved the market is always in the past by the
    time you are trading it.

    Seven days because that is the window in which an event is still the
    reason for the tape. Beyond that it is history.
    """
    today = today or _today()
    past = [d for d in event["dates"]
            if d < today and (today - d).days <= within_days]
    if not past:
        return None
    when = max(past)
    ago = (today - when).days
    return {
        "key": event["key"],
        "name": event["name"],
        "date": when.isoformat(),
        "at": event["at"],
        "days_ago": ago,
        "during_session": event["during_session"],
        "note": event["note"],
        "when": ("last night" if ago == 1 and not event["during_session"]
                 else "yesterday" if ago == 1
                 else f"{ago} days ago"),
    }


def recent(today=None, events=None, within_days=7):
    """Every event that has ALREADY happened in the last week.

    The answer to "why did it open like this". Facts only -- the event
    and when. It does NOT say what the event did to the market, because
    the bot has no way to know that and a guess would be worse than the
    date alone.
    """
    today = today or _today()
    rows = [r for r in (last_event(e, today, within_days)
                        for e in (events or EVENTS)) if r]
    rows.sort(key=lambda r: r["days_ago"])
    return rows


def upcoming(today=None, events=None):
    """Every event's next date, soonest first.

    An event whose date list has run out is reported EXPIRED rather
    than dropped. A calendar that has quietly reached its end looks
    exactly like a calendar with nothing on it, and the operator would
    have no way to tell which he was looking at.
    """
    today = today or _today()
    rows, expired = [], []
    for event in (events or EVENTS):
        row = next_event(event, today)
        if row is None:
            expired.append(event["name"])
        else:
            rows.append(row)
    rows.sort(key=lambda r: r["days_away"])
    return {
        "rows": rows,
        "expired": expired,
        "needs_update": bool(expired),
    }


def in_session_today(today=None):
    """Is there an event landing DURING today's session?

    Only RBI qualifies. Deliberately a question the dashboard asks and
    answers on screen -- nothing in the trading path reads it. The
    operator's own ruling: he is flat overnight, so there is nothing
    to pause for anything that resolves overnight, and for RBI the
    right response is his judgement, not an automatic rule.
    """
    today = today or _today()
    for row in upcoming(today)["rows"]:
        if row["today"] and row["during_session"]:
            return row
    return None
