"""
==========================================================
The trades the bot did not take -- named, timed, and priced
==========================================================

    py tools/would_have_traded.py
    py tools/would_have_traded.py 2026-08-04

    "give me which trades it took? names, timing, entry reason,
     exit reason, capital used , PNL."
                                -- operator, 5 August 2026

THE HONEST ANSWER IS NONE
-------------------------
It is Phase 1. The bot places no orders, and data/fills.db proves it:
every fill in the book is MANUAL_BUY_DASHBOARD or MANUAL_EXIT -- his
own clicks. The bot has never autonomously entered a position.

So this reconstructs the day it WOULD have had, and every number in
it comes from something the bot actually recorded at the time:

    entry      the price at the moment the pick was published
    qty        the size core/position_plan.py computed THEN, off the
               stop, so every trade risks about Rs 1,500
    stop
    target     the same, recorded in the pick's detail column
    exit       walked forward through the minute candles the bot's own
               feed recorded, minute by minute, from the entry time

Nothing is chosen with hindsight. The stop and target were written
down before the outcome existed.

WHAT IT IS NOT
--------------
Not a fill. Not net of brokerage, STT or MTF interest. Intrabar it
assumes the stop is hit at the stop and the target at the target,
which flatters a gap and is honest enough on a liquid name.

Where both stop and target fall inside the same minute candle, the
STOP is taken. That is the pessimistic reading and it is the right
one: assuming the good outcome would make this a sales document.

    "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS"

so the summary reports average win against average loss, not just the
net, because a net can be positive while that ratio is wrong.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn                     # noqa: E402

DECISIONS_DB = os.path.join("data", "decisions.db")
CANDLES_DB = os.path.join("data", "backtest_candles.db")
FILLS_DB = os.path.join("data", "fills.db")


def real_trades(day):
    """What the bot ACTUALLY did. Asked first, every time."""
    if not os.path.exists(FILLS_DB):
        return []
    con = sqlite3.connect(FILLS_DB)
    try:
        return list(con.execute(
            "select at, side, symbol, qty, fill_price, reason "
            "from fills where trade_date=? order by at", (day,)))
    except sqlite3.Error:
        return []
    finally:
        con.close()


def planned_entries(day):
    """The FIRST time each stock was named with a plan the bot would size.

    First, not best. Taking the best entry of the day for a symbol is
    hindsight wearing a backtest's clothes.
    """
    con = sqlite3.connect(DECISIONS_DB)
    picks = {}
    for at, symbol, action, price, why, detail in con.execute(
            "select at, symbol, action, price, why, detail from picks "
            "where date=? order by at", (day,)):
        # LONG ONLY -- "i only trade in long positions".
        if action != "BUY" or symbol in picks:
            continue
        try:
            parsed = json.loads(detail or "{}")
        except (ValueError, TypeError):
            parsed = {}
        plan = parsed.get("plan") or {}
        if not plan.get("ok") or not price:
            continue
        picks[symbol] = {
            "at": at, "entry": float(price), "why": why or "",
            "plan": plan, "detail": parsed,
        }
    con.close()
    return picks


def walk_forward(day, symbol, from_hhmm, stop, target):
    """Minute by minute from the entry. Returns (price, why, at)."""
    con = sqlite3.connect(CANDLES_DB)
    bars = list(con.execute(
        "select minute, h, l, c from candles where date=? and symbol=? "
        "and substr(minute, 12) >= ? order by minute",
        (day, symbol, from_hhmm)))
    con.close()
    if not bars:
        return None, "no candles recorded", ""
    for minute, high, low, _close in bars:
        # The stop is checked FIRST. Inside one minute there is no way
        # to know which came first, and assuming the target would turn
        # every whippy loser into a winner on paper.
        if low is not None and low <= stop:
            return stop, "STOP", minute[11:]
        if high is not None and high >= target:
            return target, "TARGET", minute[11:]
    return bars[-1][3], "still open at " + bars[-1][0][11:], bars[-1][0][11:]


def main(day=None):
    day = day or datetime.now().strftime("%Y-%m-%d")

    decision("=" * 118)
    decision(f"  WHAT THE BOT WOULD HAVE TRADED -- {day}")
    decision("=" * 118)

    # ---- WHAT IT ACTUALLY DID, BEFORE ANYTHING HYPOTHETICAL ----
    done = real_trades(day)
    if done:
        decision(f"  REAL FILLS ON {day} -- {len(done)}:")
        for at, side, symbol, qty, price, reason in done:
            decision(f"    {str(at)[11:16]}  {side:<5}{symbol:<12}"
                     f"{qty:>6} @ {price:>9.2f}   {reason}")
    else:
        decision("  REAL TRADES PLACED BY THE BOT: NONE.")
        decision("  Phase 1 -- it watches and records, it does not order.")
    decision("-" * 118)

    picks = planned_entries(day)
    if not picks:
        warn(f"  No BUY pick on {day} carried a plan the bot would size.")
        return 1

    decision(f"  {len(picks)} long setup(s) it would have taken, in the "
             f"order they appeared. Everything below is reconstructed.")
    decision("")
    decision(f"  {'STOCK':<12}{'IN':<7}{'ENTRY':>9}{'QTY':>6}{'STOP':>9}"
             f"{'TARGET':>9}  {'OUT':<7}{'WHY OUT':<10}{'EXIT':>9}"
             f"{'P&L':>9}{'MARGIN':>10}")
    decision("  " + "-" * 114)

    rows = []
    for symbol, pick in sorted(picks.items(), key=lambda kv: kv[1]["at"]):
        plan = pick["plan"]
        qty = int(plan.get("qty") or 0)
        stop = float(plan.get("stop") or 0)
        target = float(plan.get("target") or 0)
        if not (qty and stop and target):
            continue
        exit_px, why_out, exit_at = walk_forward(
            day, symbol, pick["at"][11:16], stop, target)
        if exit_px is None:
            warn(f"  {symbol}: no candles after {pick['at'][11:16]} -- "
                 f"skipped rather than guessed.")
            continue
        entry = pick["entry"]
        pnl = (exit_px - entry) * qty
        leverage = float(pick["detail"].get("mtf_leverage") or 1.0) or 1.0
        rows.append({
            "symbol": symbol, "in": pick["at"][11:16], "entry": entry,
            "qty": qty, "stop": stop, "target": target, "out": exit_at,
            "why_out": why_out, "exit": exit_px, "pnl": pnl,
            "value": entry * qty, "margin": entry * qty / leverage,
            "why_in": pick["why"],
        })
        decision(f"  {symbol:<12}{pick['at'][11:16]:<7}{entry:>9.2f}"
                 f"{qty:>6}{stop:>9.2f}{target:>9.2f}  {exit_at:<7}"
                 f"{why_out[:9]:<10}{exit_px:>9.2f}{pnl:>9,.0f}"
                 f"{entry * qty / leverage:>10,.0f}")

    if not rows:
        warn("  Nothing could be walked forward -- are today's minute "
             "candles recorded? Check data/backtest_candles.db.")
        return 1

    wins = [r["pnl"] for r in rows if r["pnl"] > 0]
    losses = [r["pnl"] for r in rows if r["pnl"] < 0]
    net = sum(r["pnl"] for r in rows)
    margin = sum(r["margin"] for r in rows)

    decision("  " + "-" * 114)
    decision(f"  {len(rows)} trade(s): {len(wins)} win, {len(losses)} lose."
             f"   NET {net:>+,.0f}")
    decision(f"  Stock value if every one were held at once "
             f"Rs {sum(r['value'] for r in rows):,.0f}"
             f"   -- MTF margin Rs {margin:,.0f}")
    if margin:
        decision(f"  Return on margin committed: {net / margin * 100:+.2f}%")

    # ---- THE RATIO HE ACTUALLY CARES ABOUT ----
    #
    #   "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING
    #    STOCKS. THATS THE CORE HEIRARCHY YOU MUST FOLLOW"
    #
    # A positive net with a 0.8:1 win/loss ratio is a losing system
    # having a good day, and reporting only the net would hide that.
    if wins and losses:
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses)) / len(losses)
        decision(f"  Average win Rs {avg_win:,.0f} against average loss "
                 f"Rs {avg_loss:,.0f}  =  {avg_win / avg_loss:.2f} : 1")
        if avg_win / avg_loss < 2.0:
            warn("  Below 2:1. The losses are not small enough relative "
                 "to the wins for a coin-flip hit rate to pay.")

    stalled = [r for r in rows if r["why_out"].startswith("still open")]
    if stalled:
        decision("")
        decision(f"  {len(stalled)} of {len(rows)} never reached a stop or a "
                 f"target and were still open at the close.")
        decision("  Those exits are the closing price, not a decision. The "
                 "bot has no intraday exit rule running yet")
        decision("  -- core/ranker.py's liveness() is not wired as one "
                 "(BACKLOG D).")

    decision("=" * 118)
    decision("  RECONSTRUCTED, NOT TRADED. No brokerage, no STT, no MTF")
    decision("  interest. Where a minute contained both the stop and the")
    decision("  target, the STOP was taken.")
    decision("=" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
