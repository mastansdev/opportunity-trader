"""Do the two minute stores agree? Say so, out loud, per session.

    "after trading closed main.py is duplicating the min candle &
     creating mess inside bot"        -- operator, 29 August 2026

He was half right, and the half he was right about is the worse half.

NOTHING IS DUPLICATED. data/history_candles.db carries
CONSTRAINT uq_candle UNIQUE (date, symbol, minute); scanned across all
32.6 million rows there are zero extra rows. The same minute cannot be
written twice.

BUT THERE ARE TWO STORES, and they hold the same minutes with
different numbers:

    data/history_candles.db    fetched from Dhan (the exchange's own)
                               read by core/atr.py, core/liquidity.py,
                               core/volume_pace.py -- THE LIVE PATH
    data/backtest_candles.db   recorded from the bot's own ticks
                               read by core/session_replay.py and
                               every tool in here

Measured on 27 August, over the 156,125 minutes both hold:

    close price   median 0.000%   p90 0.02%    worst 1.5%
    volume        median 10.4%    p90 78.3%    worst 29,300%

Prices agree. VOLUME DOES NOT -- half of all minutes differ by more
than 10%. And volume is a hard gate: a stock needs 2.5x its own normal
to be a candidate at all.

So a replay does not reproduce the volume decisions the live bot made.
Nothing is corrupt; the two simply measure different things -- what
the exchange consolidated against what this machine's feed caught --
and nobody has ever compared them.

WHICH IS ALSO THE POINT. A gap between them is a FEED GAP: minutes
this bot did not see. That is worth knowing on the morning it happens,
not never.

    py tools/candle_agreement.py                 the last session
    py tools/candle_agreement.py 2026-08-27      one session
    py tools/candle_agreement.py --days 5        the last five

Author : H&M Opportunity Trader
"""

import os
import sqlite3
import statistics
import sys

HISTORY = os.path.join("data", "history_candles.db")
BACKTEST = os.path.join("data", "backtest_candles.db")

# A minute whose volume differs by more than this is worth naming.
# Chosen against the gate it feeds: core/rules.MIN_VOLUME_RATIO is
# 2.5, so a reading 25% out can move a stock across it.
VOLUME_GAP_PCT = 25.0
PRICE_GAP_PCT = 0.5


def _open(path):
    if not os.path.exists(path):
        return None
    return sqlite3.connect("file:" + path + "?mode=ro", uri=True)


def _minutes(conn, day):
    """{(symbol, 'YYYY-MM-DDTHH:MM'): (o, h, l, c, v)} for one day."""
    if conn is None:
        return {}
    try:
        rows = conn.execute(
            "SELECT symbol, minute, o, h, l, c, v FROM candles "
            "WHERE date = ?", (day,)).fetchall()
    except sqlite3.Error:
        return {}
    # The two stores write the minute differently -- one carries
    # seconds, the other does not. Compare on the minute itself.
    return {(s, str(m)[:16]): (o, h, l, c, v) for s, m, o, h, l, c, v in rows}


def sessions(conn, count=1):
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT DISTINCT date FROM candles ORDER BY date DESC "
        "LIMIT ?", (count,)).fetchall()
    return [r[0] for r in reversed(rows)]


_DEFAULT = object()


def compare(day, history=_DEFAULT, backtest=_DEFAULT):
    """One session, both stores. Never raises.

    Passing None explicitly means "there is no such store" -- which is
    a real state on a machine that has never recorded a session, and
    must not quietly fall back to opening the live files.
    """
    history = _open(HISTORY) if history is _DEFAULT else history
    backtest = _open(BACKTEST) if backtest is _DEFAULT else backtest
    left, right = _minutes(history, day), _minutes(backtest, day)
    shared = set(left) & set(right)
    prices, volumes = [], []
    worst_volume = []
    for key in shared:
        a, b = left[key], right[key]
        if a[3] and b[3]:
            prices.append(abs(a[3] - b[3]) / a[3] * 100.0)
        if a[4] and b[4]:
            gap = abs(a[4] - b[4]) / a[4] * 100.0
            volumes.append(gap)
            if gap > VOLUME_GAP_PCT:
                worst_volume.append((gap, key[0], key[1], a[4], b[4]))
    worst_volume.sort(reverse=True)

    def summarise(values):
        if not values:
            return {}
        values = sorted(values)
        return {"n": len(values),
                "median": round(statistics.median(values), 3),
                "p90": round(values[int(len(values) * 0.9)], 2),
                "worst": round(values[-1], 1)}

    return {"date": day,
            "history_only": len(left) - len(shared),
            "backtest_only": len(right) - len(shared),
            "shared": len(shared),
            "price": summarise(prices),
            "volume": summarise(volumes),
            "loud": worst_volume[:10]}


def _line(name, got):
    if not got:
        return f"    {name:<14}nothing to compare"
    return (f"    {name:<14}median {got['median']:>8.3f}%   "
            f"p90 {got['p90']:>8.2f}%   worst {got['worst']:>10.1f}%   "
            f"n={got['n']:,}")


def main(argv):
    days = 1
    named = None
    for arg in argv:
        if arg == "--days" or arg.startswith("--days="):
            continue
        if arg.isdigit():
            days = int(arg)
        elif "-" in arg:
            named = arg
    if "--days" in argv:
        i = argv.index("--days")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            days = int(argv[i + 1])

    history, backtest = _open(HISTORY), _open(BACKTEST)
    if history is None:
        print(f"{HISTORY} not found.")
        return 2
    if backtest is None:
        print(f"{BACKTEST} not found -- nothing to compare against.")
        return 0

    wanted = [named] if named else sessions(history, days)
    print("  DO THE TWO MINUTE STORES AGREE?")
    print(f"    history  = {HISTORY}   (Dhan's, and what the live path reads)")
    print(f"    backtest = {BACKTEST}  (this machine's ticks, read by replays)")
    print()
    for day in wanted:
        got = compare(day, history, backtest)
        print(f"  {day}")
        print(f"    minutes in both {got['shared']:,} "
              f"(history only {got['history_only']:,}, "
              f"backtest only {got['backtest_only']:,})")
        print(_line("close price", got["price"]))
        print(_line("volume", got["volume"]))
        if got["loud"]:
            print(f"    widest volume gaps -- minutes this machine's feed "
                  f"saw differently:")
            for gap, symbol, minute, ours, theirs in got["loud"][:5]:
                print(f"      {symbol:<12}{minute[11:]}  "
                      f"exchange {ours:>10,.0f}   recorded {theirs:>10,.0f}"
                      f"   {gap:>8.0f}%")
        print()
    print("  A gap here is not corruption. It is a minute this machine")
    print("  did not see the whole of -- which is worth knowing on the")
    print("  morning it happens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
