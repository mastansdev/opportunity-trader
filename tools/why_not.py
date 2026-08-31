"""
==========================================================
Why didn't the bot trade this stock?
==========================================================

    py tools/why_not.py DIFFNKG
    py tools/why_not.py DIFFNKG --date 2026-08-31
    py tools/why_not.py                     # today's biggest movers

    "i didn't understand why bot can't see the stocks or any other
     thing . literally i'm loosing my control & frustated"
                                    -- the operator, 31 August 2026

He asked why the bot took none of 31 August's twelve best stocks.
DIFFNKG closed +18.3%, MANALIPETC +10.9%, PRUDENT +10.7%. The answer
existed and was unreadable: 20,962 refusal rows for the day, every one
of them anonymous. The largest read "no event -- not evaluated, 99" and
did not say which 99.

This asks one stock one question and answers it in plain words, from
the stores, with the numbers that decided it.

WHAT IT CHECKS, IN THE ORDER THE BOT DOES
-----------------------------------------
    is it a stock the bot knows about at all
    did it move enough
    was there a reason behind the move
    was it ranked
    was it refused, and for what
    was it bought

Each answer is read from a file. Where a store cannot say, this says
so rather than guessing -- "no record" and "refused" are different
answers and must never be printed as the same one.
"""

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MASTER = os.path.join("data", "master_stocks.csv")
DECISIONS = os.path.join("data", "decisions.db")
CANDLES = os.path.join("data", "backtest_candles.db")
TRADES = os.path.join("data", "trade_memory.db")


def _known(symbol):
    if not os.path.exists(MASTER):
        return None
    try:
        with open(MASTER, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("SYMBOL") or "").strip().upper() == symbol:
                    return row
    except OSError:
        return None
    return None


def _day(symbol, date):
    """open / high / low / close from the minute store."""
    if not os.path.exists(CANDLES):
        return None
    try:
        conn = sqlite3.connect(f"file:{CANDLES}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT minute, o, h, l, c FROM candles WHERE date = ? "
            "AND symbol = ? ORDER BY minute", (date, symbol)).fetchall()
        conn.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    return {"open": rows[0][1], "close": rows[-1][4],
            "high": max(r[2] for r in rows), "low": min(r[3] for r in rows),
            "high_at": max(rows, key=lambda r: r[2])[0][11:16]}


def _decisions(symbol, date):
    out = {"picks": [], "refused": []}
    if not os.path.exists(DECISIONS):
        return out
    try:
        conn = sqlite3.connect(f"file:{DECISIONS}?mode=ro", uri=True)
        out["picks"] = conn.execute(
            "SELECT at, rank, score, why FROM picks WHERE date = ? "
            "AND upper(symbol) = ? ORDER BY at LIMIT 3", (date, symbol)
        ).fetchall()
        try:
            out["refused"] = conn.execute(
                "SELECT reason, first_at, last_at, n, detail "
                "FROM refused_symbols WHERE date = ? AND upper(symbol) = ?",
                (date, symbol)).fetchall()
        except sqlite3.Error:
            out["refused"] = conn.execute(
                "SELECT reason, first_at, last_at, n, reason "
                "FROM refused_symbols WHERE date = ? AND upper(symbol) = ?",
                (date, symbol)).fetchall()
        conn.close()
    except sqlite3.Error:
        pass
    return out


def _traded(symbol, date):
    if not os.path.exists(TRADES):
        return []
    try:
        conn = sqlite3.connect(f"file:{TRADES}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT entry_time, entry_price, exit_time, exit_price, pnl, "
            "       exit_reason FROM trade_memory "
            "WHERE trade_date = ? AND upper(symbol) = ?", (date, symbol)
        ).fetchall()
        conn.close()
        return rows
    except sqlite3.Error:
        return []


def explain(symbol, date):
    symbol = symbol.strip().upper()
    out = []
    add = out.append
    add("=" * 74)
    add(f"  {symbol}  on  {date}")
    add("=" * 74)

    known = _known(symbol)
    add("")
    if known is None:
        add("  1. Does the bot know this stock?")
        add("     NO -- it is not in data/master_stocks.csv, so it is never")
        add("     scanned. Nothing below can happen.")
        add("")
        return "\n".join(out)
    add(f"  1. Known stock       yes   {known.get('COMPANY NAME', '')[:40]}")
    add(f"                             sector: {known.get('SECTOR') or '?'}")

    bars = _day(symbol, date)
    if bars is None:
        add("  2. Did it move?      no minute bars stored for that day")
    else:
        move = (bars["close"] - bars["open"]) / bars["open"] * 100
        best = (bars["high"] - bars["open"]) / bars["open"] * 100
        add(f"  2. What it did       open {bars['open']:,.2f} -> close "
            f"{bars['close']:,.2f}  ({move:+.2f}%)")
        add(f"                       best {bars['high']:,.2f} at "
            f"{bars['high_at']}  ({best:+.2f}%)")

    got = _decisions(symbol, date)
    add("")
    if got["picks"]:
        at, rank, score, why = got["picks"][0]
        add(f"  3. Ranked?           YES -- first at {str(at)[11:16]}, "
            f"rank {rank}, score {score}")
        add(f"                       {str(why)[:52]}")
    else:
        add("  3. Ranked?           no -- it never became a candidate")

    if got["refused"]:
        add("")
        add("  4. Refused, and why:")
        for reason, first, last, n, detail in got["refused"]:
            add(f"     {str(detail or reason)[:56]}")
            add(f"       from {str(first)[11:16]} to {str(last)[11:16]}, "
                f"{n} cycles")
    elif got["picks"]:
        add("  4. Refused?          no")
    else:
        add("")
        add("  4. Refused?          NOTHING ON RECORD.")
        add("     It was neither ranked nor refused, which means it never")
        add("     reached the decision path at all. Until 31 August the")
        add("     ranker's per-stock refusals were computed and thrown")
        add("     away, so days before then cannot answer this.")

    trades = _traded(symbol, date)
    add("")
    if trades:
        for entry_at, entry, exit_at, exit_price, pnl, why in trades:
            add(f"  5. Traded            IN {str(entry_at)[11:16]} at "
                f"{entry:,.2f}   OUT {str(exit_at)[11:16]} at "
                f"{exit_price:,.2f}")
            add(f"                       Rs {pnl:+,.0f}   {why}")
    else:
        add("  5. Traded?           no")
    add("")
    return "\n".join(out)


def movers(date, limit=12):
    """Today's biggest closes, and one line each on what the bot did."""
    if not os.path.exists(CANDLES):
        return "  no candle store"
    conn = sqlite3.connect(f"file:{CANDLES}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT symbol, min(minute), max(minute) FROM candles "
        "WHERE date = ? GROUP BY symbol", (date,)).fetchall()
    out = []
    for symbol, first, last in rows:
        o = conn.execute("SELECT o FROM candles WHERE date=? AND symbol=? "
                         "AND minute=?", (date, symbol, first)).fetchone()
        c = conn.execute("SELECT c FROM candles WHERE date=? AND symbol=? "
                         "AND minute=?", (date, symbol, last)).fetchone()
        if o and c and o[0]:
            out.append((symbol, (c[0] - o[0]) / o[0] * 100))
    conn.close()
    out.sort(key=lambda r: -r[1])

    lines = [f"  BIGGEST MOVERS ON {date}", ""]
    lines.append(f"  {'stock':12s} {'close%':>7s}   what the bot did")
    lines.append("  " + "-" * 62)
    for symbol, pct in out[:limit]:
        got = _decisions(symbol, date)
        if _traded(symbol, date):
            did = "TRADED IT"
        elif got["refused"]:
            did = f"refused: {str(got['refused'][0][4] or got['refused'][0][0])[:34]}"
        elif got["picks"]:
            did = "ranked, never bought"
        else:
            did = "never reached the decision path"
        lines.append(f"  {symbol:12s} {pct:+7.2f}   {did}")
    lines.append("")
    lines.append("  py tools/why_not.py <STOCK>   for the full answer on one")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Why didn't the bot trade it?")
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()
    print(explain(args.symbol, args.date) if args.symbol
          else movers(args.date, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
