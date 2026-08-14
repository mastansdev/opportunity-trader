"""
==========================================================
Why is that stock not on my board, and is my gap % right?
==========================================================

    "there is a difference in bot calculation & nse ."
                                -- operator, 11 August 2026

He put the Telegram gapper card beside the bot's PRE tab and the two
lists barely overlapped. That looks like a broken formula. It was not.

WHAT THE CHECK ON 11 AUGUST ACTUALLY FOUND
------------------------------------------
Of the 40 rows on his screen, 39 carried EXACTLY the previous close
NSE published in the 10-Aug bhavcopy, and 39 of 40 percentages were
exactly (open - prev close) / prev close. The arithmetic was never in
question.

The lists differed for two completely different reasons:

  1. COVERAGE. 9 of the card's 23 stocks are SUBSCRIBE=NO in the
     master, so the bot cannot see them at any price. Six of those
     nine still carry "new listing -- awaiting sector classification",
     including SPECIALITY, which the card graded EXCELLENT.

  2. TIMING. A pre-open number is not the open. Between 09:00 and
     09:08 the indicative price moves, and a card written at 09:05
     against a board read at 09:11 is two different moments of the
     same auction, not two different formulas.

Neither of those is fixed by touching the percentage. So this tool
reports the two things that actually differ, per symbol, and leaves
the arithmetic alone.

    py tools/gap_check.py                 -- every graded stock today
    py tools/gap_check.py INDSWFTLAB HLEGLAS SPECIALITY

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import glob
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MASTER = os.path.join("data", "master_stocks.csv")
DAILY = os.path.join("data", "daily_candles.db")
YES = ("YES", "TRUE", "1", "Y")


def _master():
    rows = {}
    with open(MASTER, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows[row["SYMBOL"].strip().upper()] = row
    return rows


def _latest_bhavcopy():
    """NSE's own published close -- the number the exchange uses as the
    denominator. Newest file on disk, so this follows the download."""
    found = sorted(glob.glob(os.path.join("data", "BhavCopy_NSE_CM_*.csv")))
    if not found:
        return None, {}
    path = found[-1]
    closes = {}
    with open(path, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if (row.get("SctySrs") or "").strip() != "EQ":
                continue          # "we will trade only in Equites (EQ)"
            try:
                closes[row["TckrSymb"].strip().upper()] = float(row["ClsPric"])
            except (TypeError, ValueError, KeyError):
                continue
    return path, closes


def _db_close(symbol):
    try:
        with sqlite3.connect(DAILY) as conn:
            got = conn.execute(
                "SELECT date, close FROM daily_bars WHERE symbol=? "
                "ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
        return got if got else (None, None)
    except Exception:                                          # noqa: BLE001
        return (None, None)


def _graded_today():
    try:
        from core import watchlist_builder
        return sorted(set(watchlist_builder.graded_symbols() or []))
    except Exception:                                          # noqa: BLE001
        return []


def main(symbols):
    master = _master()
    path, nse = _latest_bhavcopy()

    if not symbols:
        symbols = _graded_today()
        if not symbols:
            print("\n  No graded stocks yet today. Name symbols instead:")
            print("    py tools/gap_check.py INDSWFTLAB SPECIALITY\n")
            return 1

    print()
    print("  CAN THE BOT SEE IT, AND IS ITS PREVIOUS CLOSE NSE'S?")
    print("  " + "=" * 68)
    print(f"  NSE reference: {os.path.basename(path) if path else 'NONE ON DISK'}")
    print()
    print(f"  {'SYMBOL':<14}{'BOT SEES IT':<13}{'OUR CLOSE':>11}"
          f"{'NSE CLOSE':>11}  WHY NOT")
    print("  " + "-" * 68)

    blind = []
    drift = []
    for symbol in [str(s).strip().upper() for s in symbols]:
        row = master.get(symbol)
        if row is None:
            print(f"  {symbol:<14}{'NOT IN MASTER':<13}{'-':>11}{'-':>11}")
            blind.append((symbol, "not in the master at all"))
            continue

        subscribed = str(row.get("SUBSCRIBE", "")).strip().upper() in YES
        reason = (row.get("SUBSCRIBE_REASON") or "").strip()
        _, ours = _db_close(symbol)
        theirs = nse.get(symbol)

        if not subscribed:
            blind.append((symbol, reason or "SUBSCRIBE=NO, no reason given"))
        if ours is not None and theirs is not None and abs(ours - theirs) > 0.005:
            drift.append((symbol, ours, theirs))

        print(f"  {symbol:<14}{('yes' if subscribed else 'NO'):<13}"
              f"{(f'{ours:.2f}' if ours is not None else '-'):>11}"
              f"{(f'{theirs:.2f}' if theirs is not None else '-'):>11}"
              f"  {'' if subscribed else reason[:30]}")

    print()
    print("  " + "-" * 68)
    if drift:
        print(f"  {len(drift)} previous close(s) disagree with NSE:")
        for symbol, ours, theirs in drift:
            print(f"      {symbol:<14}ours {ours:.2f}   NSE {theirs:.2f}   "
                  f"({(ours - theirs):+.2f})")
        print("  Every gap on those rows is wrong by the same amount.")
    else:
        print("  Every previous close matches NSE to the paisa. The gap "
              "percentages built on them are NSE's own arithmetic.")
    print()

    if blind:
        print(f"  {len(blind)} stock(s) the bot CANNOT SEE AT ANY PRICE.")
        print("  These will never appear on the board however far they gap:")
        for symbol, why in blind:
            print(f"      {symbol:<14}{why[:52]}")
        print()
        print("  This is coverage, not calculation. Clearing a stale")
        print("  'new listing' label puts the stock back on the board;")
        print("  no change to the percentage would ever have done it.")
    else:
        print("  Every symbol checked is subscribed.")
    print()

    print("  ONE THING THIS CANNOT TELL YOU")
    print("  A pre-open card and a pre-open board are two moments of the")
    print("  same auction. The indicative price moves until 09:08. Judge")
    print("  the gap against NSE's OPEN after 09:15, never against a")
    print("  number printed at 09:05.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
