"""
==========================================================
py tools/inventory.py  --  what arrives, and what is READ
==========================================================

    "EVERYTHING IS HAD BUT I'M NOT SURE BOT KNOWS ALL"
    "I NEED YOUR COMPLETE AWARENESS ON BOT FROM END TO END ABOUT
     WHAT BOT CONSUMING, PRODUCING"
                                -- operator, 7 August 2026

WHY THIS EXISTS
---------------
He pays for nine PRO channels. The collector stores everything they
send. Whether any of it reaches a trading decision has never been
measured -- it has only ever been asserted, by me, from reading code.

On 7 August that assertion was wrong twice in one day. Business Pulse
and OrderBook Pulse had been arriving for a month, with the symbols
extracted correctly, and why_moving() returned NOTHING for eleven of
twelve stocks they had named.

    "do not throw away any information we are receiving"

This tool does not read code. It takes real symbols out of each
channel and asks the bot the only question that matters:

    "Why is this stock moving?"

If the bot has no answer for a stock its own channel named an hour
ago, that channel is decoration. The hit rate is the measurement.

WHAT THE COLUMNS MEAN
---------------------
    STORED    messages kept from this channel in the window
    NAMED     of those, how many carried a usable symbol
    KNOWN     of those symbols, how many the bot can explain
    READ      KNOWN as a percentage -- the number that matters

A channel at 0% READ is one the operator is paying for and the bot
is ignoring.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TELEGRAM_DB = "data/telegram.db"

# How far back to sample. Long enough to cover a results season, short
# enough that the answer describes the bot as it is now.
WINDOW_DAYS = 30

# Symbols to test per channel. Every symbol would be honest and slow;
# this is a sample, and the tool says so rather than implying a census.
SAMPLE_PER_CHANNEL = 25


def _symbols(raw):
    """The symbols on a stored message, however they were written."""
    if not raw:
        return []
    text = str(raw).strip()
    if not text or text == "[]":
        return []
    try:
        got = json.loads(text)
        if isinstance(got, list):
            return [str(s).upper() for s in got if s]
        if isinstance(got, str):
            return [got.upper()]
    except Exception:                                      # noqa: BLE001
        pass
    # Bare "LT,ONGC" -- seen in OrderBook Pulse.
    return [part.strip().upper() for part in text.split(",") if part.strip()]


def main():
    from core.why_moving import why

    con = sqlite3.connect(TELEGRAM_DB)
    channels = [row[0] for row in con.execute(
        "select channel, count(*) from messages "
        "where seen_at > date('now', ?) group by channel order by 2 desc",
        (f"-{WINDOW_DAYS} day",))]

    print("=" * 76)
    print(f"  WHAT THE BOT RECEIVES, AND WHAT IT ACTUALLY READS")
    print(f"  last {WINDOW_DAYS} days, up to {SAMPLE_PER_CHANNEL} "
          f"symbols sampled per channel")
    print("=" * 76)
    print(f"  {'CHANNEL':<20}{'STORED':>8}{'NAMED':>8}{'TESTED':>8}"
          f"{'KNOWN':>8}{'READ':>8}")
    print("  " + "-" * 58)

    silent = []
    for channel in channels:
        rows = con.execute(
            "select symbols from messages where channel = ? "
            "and seen_at > date('now', ?) order by seen_at desc",
            (channel, f"-{WINDOW_DAYS} day")).fetchall()
        stored = len(rows)

        # Deduplicate: a channel that names the same stock forty times
        # should not score forty times for one reason.
        wanted = OrderedDict()
        named = 0
        for (raw,) in rows:
            got = _symbols(raw)
            if got:
                named += 1
            for symbol in got:
                wanted.setdefault(symbol, None)

        tested = list(wanted)[:SAMPLE_PER_CHANNEL]
        known = 0
        for symbol in tested:
            try:
                answer = why(symbol=symbol)
            except Exception:                              # noqa: BLE001
                answer = None
            if answer and (answer.get("text") if isinstance(answer, dict)
                           else answer):
                known += 1

        pct = (100.0 * known / len(tested)) if tested else 0.0
        print(f"  {channel[:20]:<20}{stored:>8}{named:>8}{len(tested):>8}"
              f"{known:>8}{pct:>7.0f}%")
        if tested and pct < 25.0:
            silent.append((channel, pct, len(tested)))

    con.close()
    print("  " + "-" * 58)

    if not silent:
        print("\n  Every channel reaches a decision. Nothing is being "
              "thrown away.")
    else:
        print(f"\n  {len(silent)} CHANNEL(S) THE BOT IS NOT READING:\n")
        for channel, pct, n in silent:
            print(f"     {channel}  --  {pct:.0f}% of {n} sampled symbols "
                  f"have a reason")
        print("\n  These are paid for and arriving. The collector stores")
        print("  them, the symbols are extracted, and no decision path")
        print("  asks. That is information being thrown away.")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
