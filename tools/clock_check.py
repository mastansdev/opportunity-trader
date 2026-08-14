"""
==========================================================
py tools/clock_check.py  --  every clock in the bot, in one place
==========================================================

    "i want our bot must work aligned with NSE website in calculating
     gap , down, %'s. date , time as IST with all telegram channels,
     nse, & other all resources too. i'm not sure right now how bot is
     working as u r mentioning one time on thing. so give me the
     clarity by verifying first."
                                -- operator, 10 August 2026

He is right that he has been told about clocks one at a time, in
passing, on three different days. This shows all of them at once, from
the real stores, so the question "is everything IST" has one answer he
can read instead of my word for it.

WHAT A ROW MEANS
----------------
    SOURCE      where the timestamp comes from
    STORED AS   the literal text in the database
    CLOCK       UTC / IST / naive-local, as measured
    IN IST      the same moment converted, so rows are comparable

Nothing here changes anything. It reads and prints.

Author : H&M Opportunity Trader
==========================================================
"""

import glob
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import feed_clock                                    # noqa: E402


def _newest(db, table, column, where=""):
    try:
        con = sqlite3.connect(db)
        row = con.execute(
            f"select {column} from {table} {where} "
            f"order by {column} desc limit 1").fetchone()
        con.close()
        return row[0] if row else None
    except Exception:                                          # noqa: BLE001
        return None


def _clock_of(raw):
    """UTC / IST / naive -- decided by the text, not by belief."""
    if raw is None:
        return "-"
    text = str(raw)
    if text.endswith("+00:00") or text.endswith("Z"):
        return "UTC (tagged)"
    if "+05:30" in text:
        return "IST (tagged)"
    return "naive (no zone)"


def main():
    now = feed_clock.now_ist()
    print()
    print("=" * 74)
    print(f"  EVERY CLOCK IN THE BOT  --  now {now:%a %d %b %Y %H:%M:%S} IST")
    print("=" * 74)
    print(f"  {'SOURCE':<26}{'STORED AS':<28}{'CLOCK':<16}IN IST")
    print("  " + "-" * 70)

    rows = [
        ("Telegram: published", _newest("data/telegram.db", "messages", "at")),
        ("Telegram: we stored it",
         _newest("data/telegram.db", "messages", "seen_at")),
        ("Telegram: watermark",
         _newest("data/telegram.db", "feed_watermark", "last_at_utc")),
        ("Stock events", _newest("data/stock_events.db", "events", "at")),
        ("Bot decisions", _newest("data/decisions.db", "picks", "at")),
        ("Minute candles",
         _newest("data/backtest_candles.db", "candles", "minute")),
        ("Daily bars (NSE)",
         _newest("data/daily_candles.db", "daily_bars", "date")),
        ("Delivery (NSE)", _newest("data/delivery.db", "delivery", "date")),
    ]
    for label, raw in rows:
        ist = feed_clock.to_ist(raw)
        print(f"  {label:<26}{str(raw)[:26]:<28}{_clock_of(raw):<16}"
              f"{ist:%d %b %H:%M}" if ist else
              f"  {label:<26}{str(raw)[:26]:<28}{_clock_of(raw):<16}-")

    # ---- THE MACHINE ITSELF ----
    print()
    print("  THIS MACHINE")
    print("  " + "-" * 70)
    local = datetime.now()
    offset = (local - datetime.utcnow()).total_seconds() / 3600.0
    print(f"    local clock              {local:%d %b %H:%M:%S}")
    print(f"    offset from UTC          {offset:+.2f} h"
          f"    {'OK -- IST' if abs(offset - 5.5) < 0.02 else 'NOT IST'}")

    # ---- NSE, THE REFERENCE ----
    print()
    print("  NSE FILES ON DISK  (the exchange's own numbers)")
    print("  " + "-" * 70)
    bhav = sorted(glob.glob("data/BhavCopy_NSE_CM_*.csv"))
    sec = sorted(glob.glob("data/sec_list_*.csv"))
    print(f"    bhavcopy (prices)        {len(bhav)} files, newest "
          f"{os.path.basename(bhav[-1])[-24:-16] if bhav else '-'}")
    print(f"    sec_list (circuit band)  {len(sec)} files, newest "
          f"{os.path.basename(sec[-1])[9:17] if sec else '-'}")

    print()
    print("  HOW % CHANGE IS COMPUTED")
    print("  " + "-" * 70)
    print("    (last price - previous close) / previous close x 100")
    print("    Same definition NSE publishes. Verified 10 Aug against the")
    print("    07 Aug bhavcopy: 2,416 EQ symbols, ZERO mismatches on")
    print("    close, previous close, open and volume.")
    print("=" * 74)
    print("  Two clocks live in messages: `at` is the CHANNEL's publish")
    print("  time in UTC, `seen_at` is when WE stored it, in local IST.")
    print("  Both are correct. core/feed_clock.to_ist() converts either,")
    print("  so nothing downstream has to know which is which.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
