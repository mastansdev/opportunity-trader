"""
==========================================================
Five lakh a month, and what is left of it
==========================================================

    "on monthly 5L target & in case day -1 bot booked 70 K then
     remaining 4.3L on remaining days & so on. not like averaging each
     day targets. as market may give more opportunites in some days &
     less in other days"
                                -- the operator, 6 September 2026

A RUNNING REMAINDER, NOT A QUOTA. The distinction is the whole
instruction. 5,00,000 divided by 21 trading days is 23,810 a day, and
that number is a lie on both ends: it makes a quiet Tuesday look like
a failure and a day that hands you two NIACLs look finished at noon.
The market decides how much is on offer; this only says how much of
the month's goal is still outstanding.

    booked 70,000 on day one  ->  4,30,000 left, over whatever days
                                  remain and whatever they offer

SO THIS FUNCTION DIVIDES BY NOTHING. There is deliberately no
"needed per day" field, because the moment one exists somebody reads
it as a target and starts forcing trades on a thin morning to hit it.

AND IT DECIDES NOTHING. No gate imports this, and a test enforces
that. His rule, 1 September:

    "there is no fixed time ,price or fixed limitations to follow.
     this is stock market not our own shop to do as we want."

config.DAILY_PROFIT_TARGET_RS was already stripped of its power for
exactly this reason -- it announces when a day clears 75,000 and
decides nothing. This is the same shape, one level up. The only
number that still STOPS anything is DAILY_MAX_LOSS_RS, which he chose
against his real account and which triggers on money already lost.

ONE LINE PER DAY, NEVER AN AVERAGE. `days` is the day-by-day record
because that is how he reads a month -- 2 Sep lost 6,376, 4 Sep made
11,794, and no single figure describes both.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
from datetime import date, datetime

from core.logger import diagnostic

TRADES_DB = os.path.join("data", "trade_memory.db")

try:
    from config import MONTHLY_TARGET_RS
except Exception:                                          # noqa: BLE001
    MONTHLY_TARGET_RS = 5_00_000.0


def _month_bounds(day):
    """First and last calendar day of that month."""
    first = day.replace(day=1)
    if day.month == 12:
        nxt = date(day.year + 1, 1, 1)
    else:
        nxt = date(day.year, day.month + 1, 1)
    return first, nxt


def _sessions(first, last):
    """Trading days in [first, last), asked of the live calendar.

    Falls back to weekdays if the calendar cannot be built -- a
    holiday counted as a session overstates the days remaining by one
    or two, which is a smaller error than refusing to answer at all.
    """
    try:
        from core.market_calendar import default_calendar
        cal = default_calendar()
        return [d for d in cal.trading_days_between(first, last)
                if d < last]
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MONTH] calendar unavailable ({exc}); "
                   f"counting weekdays instead")
        out, day = [], first
        while day < last:
            if day.weekday() < 5:
                out.append(day)
            day += _one_day()
        return out


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


def _charges(row):
    """What this round trip cost, or None if it cannot be priced.

    ---- GROSS IS NOT THE ANSWER. 6 September 2026. ----

        "we want their final PnL after charges"    -- the operator

    trade_memory stores pnl GROSS -- (exit - entry) x qty, as
    core/engine.py says in its own comment. Charges were never stored
    beside it, so the month was reading a number he does not actually
    receive. They are priced here from trading/charges.py, the same
    module the closed-trades table already uses, so the two can never
    give different answers.

    None, never zero: a zero charge is a claim.
    """
    try:
        from trading.charges import round_trip_charges, nights_between
    except Exception:                                      # noqa: BLE001
        return None
    entry, exit_, qty = (row.get("entry_price"), row.get("exit_price"),
                         row.get("qty"))
    if not entry or not exit_ or not qty:
        return None
    try:
        nights = nights_between(row.get("entry_time"), row.get("exit_time"))
    except Exception:                                      # noqa: BLE001
        nights = 0
    try:
        return float(round_trip_charges(
            entry, exit_, qty,
            direction=str(row.get("direction") or "LONG").upper(),
            nights_held=nights or 0))
    except Exception:                                      # noqa: BLE001
        return None


def _booked(first, last, db_path=None):
    """One row per trading day this month, NET of charges.

    Carries the count, the wins and losses, what the day cost in
    charges, the money actually kept, and what the day made WITHOUT
    ITS BEST TWO TRADES -- because on his book so far, every day's
    profit has been its best two and the rest has bled.
    """
    try:
        conn = sqlite3.connect("file:" + (db_path or TRADES_DB)
                               + "?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trade_date, pnl, entry_price, exit_price, qty, "
            "direction, entry_time, exit_time FROM trade_memory "
            "WHERE trade_date >= ? AND trade_date < ? "
            "ORDER BY trade_date", (first.isoformat(), last.isoformat())
        ).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MONTH] could not read the book ({exc})")
        return []

    by_day = {}
    for row in rows:
        row = dict(row)
        day = row.get("trade_date")
        if not day:
            continue
        gross = float(row.get("pnl") or 0.0)
        cost = _charges(row)
        by_day.setdefault(str(day), []).append(
            {"gross": gross, "cost": cost,
             "net": gross - (cost or 0.0), "priced": cost is not None})

    out = []
    for day in sorted(by_day):
        got = by_day[day]
        nets = sorted(t["net"] for t in got)
        total = sum(nets)
        cost = sum(t["cost"] or 0.0 for t in got)
        out.append({
            "day": day,
            "trades": len(got),
            "up": sum(1 for n in nets if n > 0),
            "down": sum(1 for n in nets if n < 0),
            "gross": round(sum(t["gross"] for t in got), 2),
            "charges": round(cost, 2),
            # What he actually keeps. This is the figure the month
            # counts, and the one the remainder comes off.
            "pnl": round(total, 2),
            "rest": round(total - sum(nets[-2:]), 2),
            # A trade the charges module could not price is counted at
            # gross and said so, rather than quietly costing nothing.
            "unpriced": sum(1 for t in got if not t["priced"]),
        })
    return out


def progress(now=None, target=None, db_path=None):
    """Where the month stands. Never raises, and decides nothing.

    Returns {"month", "target", "booked", "remaining", "days_done",
             "days_left", "sessions", "days", "best", "worst"}.

    There is NO per-day figure. See the module docstring.
    """
    today = now or datetime.now()
    if isinstance(today, datetime):
        today = today.date()
    goal = float(MONTHLY_TARGET_RS if target is None else target)

    first, nxt = _month_bounds(today)
    sessions = _sessions(first, nxt)
    days = _booked(first, nxt, db_path)
    booked = sum(d["pnl"] for d in days)

    # The remainder AS IT STOOD after each day -- the running figure
    # he described: "day -1 bot booked 70 K then remaining 4.3L".
    running = goal
    for day in days:
        running -= day["pnl"]
        day["remaining"] = round(running, 2)

    done = [d for d in sessions if d <= today]
    left = [d for d in sessions if d > today]

    best = max(days, key=lambda d: d["pnl"]) if days else None
    worst = min(days, key=lambda d: d["pnl"]) if days else None

    return {
        "month": today.strftime("%Y-%m"),
        "target": goal,
        "booked": round(booked, 2),
        "remaining": round(goal - booked, 2),
        "days_done": len(done),
        "days_left": len(left),
        "sessions": len(sessions),
        "days": days,
        "traded_on": len(days),
        "best": best,
        "worst": worst,
    }


def line(now=None, target=None, db_path=None):
    """One sentence for the console or the board."""
    got = progress(now, target, db_path)
    booked, remaining = got["booked"], got["remaining"]
    if remaining <= 0:
        return (f"[MONTH] {got['month']}: {booked:,.0f} booked of "
                f"{got['target']:,.0f} -- the month's goal is met, with "
                f"{got['days_left']} session(s) still to trade. Nothing "
                f"stops; a good month is not a reason to stop taking the "
                f"next opportunity.")
    return (f"[MONTH] {got['month']}: {booked:,.0f} booked, "
            f"{remaining:,.0f} of {got['target']:,.0f} still to go, "
            f"{got['days_left']} session(s) left. Traded on "
            f"{got['traded_on']} of {got['days_done']} so far.")
