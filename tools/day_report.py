"""
==========================================================
Every trade the bot closed today, and what the stock did next
==========================================================

    py tools/day_report.py                 # today
    py tools/day_report.py --date 2026-08-21
    py tools/day_report.py --csv           # same rows, for a spreadsheet

    "i want report of every trade after market closed with details ,
     which stock , entry reason, entry time, entry price, exit price,
     reason, time & pnl of that trade. after exit change in stock all
     i need to see ."              -- the operator, 31 August 2026

WHY THIS EXISTS WHEN exit_review.py ALREADY DOES HALF OF IT
-----------------------------------------------------------
exit_review answers "is this exit RULE any good", across every session
on record. It groups by exit reason and reports medians, which is the
right shape for that question and the wrong shape for this one.

This answers "what happened today". One line per trade, both sides of
it, nothing grouped and nothing averaged -- because a single day is not
a population, and the middle of five numbers is not a fact about any
one of them.

WHAT "AFTER EXIT" MEANS HERE
----------------------------
Three separate readings from the minute candles after the exit, never
blended into one:

    close       where the stock finished. What patience would have paid.
    high        the best it offered after we left. Did we leave early?
    low         the worst it offered after we left. Did leaving save us?

All three, every time. Showing only the high is how a person talks
himself out of a stop loss; showing only the low is how he talks
himself into holding losers.

A trade exited in the last minutes of the day has no candles after it.
That is said plainly rather than filled in with a zero.

ONE THING IT WILL NOT DO
------------------------
It will not tell him an exit was wrong because the stock went up
afterwards. Every exit gives something back; the question is whether it
gives back more than it saves, and one day cannot answer that. That is
exit_review's job, over every session on record.
"""

import argparse
import os
import sqlite3
from collections import defaultdict
from datetime import datetime

TRADES_DB = os.path.join("data", "trade_memory.db")
CANDLES_DB = os.path.join("data", "backtest_candles.db")


def load_trades(date):
    if not os.path.exists(TRADES_DB):
        return []
    conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT symbol, direction, trade_date, entry_time, exit_time, "
        "       entry_price, exit_price, qty, pnl, entry_reason, "
        "       exit_reason, holding_minutes "
        "FROM trade_memory WHERE trade_date = ? "
        "ORDER BY entry_time", (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_candles(date, symbols):
    """{symbol: [(minute, high, low, close), ...]} for one day."""
    out = defaultdict(list)
    if not symbols or not os.path.exists(CANDLES_DB):
        return out
    conn = sqlite3.connect(f"file:{CANDLES_DB}?mode=ro", uri=True)
    marks = ",".join("?" * len(symbols))
    try:
        for sym, minute, h, l, c in conn.execute(
                f"SELECT symbol, minute, h, l, c FROM candles "
                f"WHERE date = ? AND symbol IN ({marks}) "
                f"ORDER BY symbol, minute", (date, *symbols)):
            out[sym].append((minute, h, l, c))
    except sqlite3.Error:
        pass
    conn.close()
    return out


def after_exit(candles, exit_time):
    """Only what happened strictly after the exit minute."""
    if not exit_time:
        return []
    minute = str(exit_time)[:16].replace(" ", "T")
    return [c for c in candles if c[0] > minute]


def what_happened_next(trade, candles):
    """close / high / low after the exit, each as a % of the exit price.

    None when the exit was too late in the day to have an "after" --
    which is a real answer and must not be shown as zero."""
    rest = after_exit(candles, trade.get("exit_time"))
    exit_price = trade.get("exit_price")
    if not rest or not exit_price:
        return None
    high = max(c[1] for c in rest)
    low = min(c[2] for c in rest)
    close = rest[-1][3]

    def pct(value):
        return (value - exit_price) / exit_price * 100.0

    # The bot is long only. Said out loud rather than assumed: if a
    # short ever reaches this table the signs need reading the other way
    # round, and a silently wrong sign is worse than a missing column.
    return {"close": close, "close_pct": pct(close),
            "high": high, "high_pct": pct(high),
            "low": low, "low_pct": pct(low),
            "short": str(trade.get("direction") or "").upper()
                     not in ("", "LONG", "BUY")}


def _t(value):
    """09:23, out of whatever shape the timestamp was stored in."""
    text = str(value or "")
    for cut in (11, 0):
        piece = text[cut:cut + 5]
        if len(piece) == 5 and piece[2] == ":":
            return piece
    return "--:--"


def _day(value):
    """2026-08-25 out of a timestamp, or "" if it does not carry one."""
    text = str(value or "")
    return text[:10] if len(text) >= 10 and text[4] == "-" else ""


def _held(minutes):
    """---- ELEVEN SECONDS IS NOT "0 MIN". 31 August 2026. ----

    CDSL on 21 August was bought and rotated out 11 seconds later. The
    report rounded that to "held 0 min", which reads like a rounding
    artefact rather than the finding it is: a trade that never had a
    chance to work and still paid a full round trip in charges.

    Seconds below a minute, minutes below a day, days above it.
    """
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return "?"
    if minutes < 1.0:
        return f"{minutes * 60:.0f} sec"
    if minutes < 60 * 8:
        return f"{minutes:,.0f} min"
    return f"{minutes / 60 / 24:.1f} days"


def rows_for(date):
    trades = load_trades(date)
    candles = load_candles(date, sorted({t["symbol"] for t in trades}))
    for t in trades:
        t["next"] = what_happened_next(t, candles.get(t["symbol"], []))
    return trades


def render(date, trades):
    out = []
    add = out.append
    add("=" * 78)
    add(f"  EVERY TRADE ON {date}")
    add("=" * 78)

    if not trades:
        add("")
        add("  The bot closed no trades today.")
        add("")
        add("  That is a finished answer, not a missing one. It only buys")
        add("  when something is behind the move, so a day with no event")
        add("  is a day with no trade.")
        add("")
        return "\n".join(out)

    won = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    net = sum(t.get("pnl") or 0 for t in trades)
    add(f"  {len(trades)} trade(s), {won} won, {len(trades) - won} lost, "
        f"Rs {net:+,.0f} before charges")
    add("")

    for i, t in enumerate(trades, 1):
        nxt = t.get("next")
        head = f"  {i}. {t['symbol']}"
        if t.get("pnl") is not None:
            head += f"   Rs {t['pnl']:+,.0f}"
        add(head)
        add(f"       IN    {_t(t.get('entry_time'))}  "
            f"Rs {t.get('entry_price') or 0:,.2f} x {t.get('qty') or 0}")
        add(f"             {t.get('entry_reason') or 'no reason recorded'}")
        held = ""
        if t.get("holding_minutes") is not None:
            held = f"   held {_held(t['holding_minutes'])}"
        # ---- SAY THE DATE WHEN IT IS A DIFFERENT DAY. 31 Aug 2026. ----
        #
        # JBMA on 21 August printed "IN 12:41 / OUT 09:17", which reads
        # as an exit before the entry. It was not: the position was
        # opened on the 21st and stopped out on the 25th, four calendar
        # days and a weekend later.
        #
        # This is an INTRADAY bot. A position that lived past the close
        # is the single most important thing on the line, and the clock
        # alone hid it completely.
        day = _day(t.get("exit_time"))
        crossed = day and day != str(t.get("trade_date") or "")
        stamp = f"{day} {_t(t.get('exit_time'))}" if crossed \
            else _t(t.get("exit_time"))
        add(f"       OUT   {stamp}  "
            f"Rs {t.get('exit_price') or 0:,.2f}{held}")
        add(f"             {t.get('exit_reason') or 'no reason recorded'}")
        if crossed:
            add("             ^^ HELD PAST THE CLOSE. This bot is "
                "intraday -- it should")
            add("                not have been carrying this overnight.")
        if nxt is None:
            add("       AFTER no candles left after the exit -- nothing to "
                "judge it against")
        else:
            add(f"       AFTER closed Rs {nxt['close']:,.2f} "
                f"({nxt['close_pct']:+.2f}% from our exit)")
            add(f"             best  Rs {nxt['high']:,.2f} "
                f"({nxt['high_pct']:+.2f}%)"
                f"   worst Rs {nxt['low']:,.2f} ({nxt['low_pct']:+.2f}%)")
            if nxt["short"]:
                add("             (SHORT -- read the signs the other way "
                    "round)")
        add("")

    # The only counting that happens here, and it is a count, not an
    # average. Both directions, so neither reading can stand alone.
    judged = [t for t in trades if t.get("next")]
    if judged:
        ran = sum(1 for t in judged if t["next"]["high_pct"] >= 1.0)
        saved = sum(1 for t in judged if t["next"]["low_pct"] <= -1.0)
        add("  AFTER WE LEFT")
        add(f"    {ran} of {len(judged)} ran another 1% or more without us")
        add(f"    {saved} of {len(judged)} fell 1% or more -- "
            f"leaving saved that")
        add("")
        add("    Both lines, always. One day is far too few to conclude")
        add("    anything from either. For whether an exit RULE is any")
        add("    good, run py tools/exit_review.py -- that reads every")
        add("    session on record.")
        add("")
    return "\n".join(out)


def as_csv(date, trades):
    lines = [("date,symbol,entry_time,entry_price,qty,entry_reason,"
              "exit_time,exit_price,exit_reason,holding_minutes,pnl,"
              "close_after,close_after_pct,high_after,high_after_pct,"
              "low_after,low_after_pct")]

    def q(value):
        text = "" if value is None else str(value)
        if "," in text or '"' in text:
            return '"' + text.replace('"', '""') + '"'
        return text

    for t in trades:
        n = t.get("next") or {}
        lines.append(",".join(str(x) for x in (
            date, q(t["symbol"]), q(t.get("entry_time")),
            t.get("entry_price") or "", t.get("qty") or "",
            q(t.get("entry_reason")), q(t.get("exit_time")),
            t.get("exit_price") or "", q(t.get("exit_reason")),
            t.get("holding_minutes") or "", t.get("pnl") or "",
            n.get("close", ""), f"{n['close_pct']:.2f}" if n else "",
            n.get("high", ""), f"{n['high_pct']:.2f}" if n else "",
            n.get("low", ""), f"{n['low_pct']:.2f}" if n else "")))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Every trade closed on a day.")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    trades = rows_for(args.date)
    print(as_csv(args.date, trades) if args.csv
          else render(args.date, trades))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
