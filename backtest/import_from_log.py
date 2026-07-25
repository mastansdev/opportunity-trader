"""
Bootstrap the replay corpus from the running bot's diagnostics.log.

Parses lines of the form
    2026-07-24 09:15:00,133 [DEBUG] [CANDLE] TATASTEEL closed O=184.20 H=184.20 L=184.20 C=184.20
into 1-minute candles and writes them to the CandleStore.

Honest about its limits: these log candles have NO volume and NO explicit
market timestamp (we use the log's close time floored to the minute), and
the day was muddied by restarts (a bar re-logged after a restart just
overwrites -- last write wins). Good enough to get the replay harness
working on real prices TODAY; the forward recorder (separate task) is the
clean source going forward.

Run:  py backtest/import_from_log.py 2026-07-24
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.candle_store import CandleStore

LOG_PATH = os.path.join("logs", "diagnostics.log")

_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2},\d+ .*?\[CANDLE\] "
    r"(\S+) closed O=([\d.]+) H=([\d.]+) L=([\d.]+) C=([\d.]+)"
)

# Regular NSE session only -- drop pre-open warm candles and anything
# after square-off so the replay sees a clean 09:15-15:30 session.
SESSION_START = "09:15"
SESSION_END = "15:30"


def import_date(date, log_path=LOG_PATH, store=None):
    store = store or CandleStore()
    rows = {}   # (symbol, minute) -> row, last write wins (mirrors restarts)
    scanned = matched = 0

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "[CANDLE]" not in line:
                continue
            scanned += 1
            m = _LINE.match(line)
            if not m:
                continue
            d, hh, mm, sym, o, h, l, c = m.groups()
            if d != date:
                continue

            # ---- TIMESTAMP CORRECTION (2026-07-25, operator-found) ----
            # A [CANDLE] line is written when the candle CLOSES, i.e. on
            # the first tick of the NEXT minute. So a line stamped 09:31
            # is the 09:30 candle -- shift back one minute.
            #
            # And the line stamped 09:15 is NOT the 09:15 candle at all:
            # it's the PRE-MARKET candle the bot accumulated from stale
            # snapshot ticks since ~08:15, flushed by the first real
            # open tick. It carries the previous close (COROMANDEL
            # 2019.00 vs a real 09:15-09:30 high of 1982.50), which
            # corrupted every ORB range this corpus produced. The LIVE
            # engine was never affected -- orb_engine.py correctly
            # ignores ticks outside [MARKET_OPEN, ORB_WINDOW_END) -- this
            # was purely an artefact of reconstructing candles from log
            # write-times. Dropped entirely.
            total = int(hh) * 60 + int(mm) - 1
            if total < 0:
                continue
            hhmm = f"{total // 60:02d}:{total % 60:02d}"
            if hhmm < SESSION_START or hhmm > SESSION_END:
                continue
            minute = f"{d}T{hhmm}"
            rows[(sym, minute)] = dict(
                date=d, symbol=sym, minute=minute,
                o=float(o), h=float(h), l=float(l), c=float(c), v=None,
            )
            matched += 1

    store.clear_date(date)
    # Fast bulk insert -- we've already deduped in memory, no conflicts left.
    vals = list(rows.values())
    with store.engine.begin() as conn:
        CHUNK = 5000
        for i in range(0, len(vals), CHUNK):
            conn.execute(store.candles.insert(), vals[i:i + CHUNK])

    n_syms = len({k[0] for k in rows})
    print(f"[IMPORT] {date}: scanned {scanned} candle lines, matched {matched}, "
          f"stored {len(vals)} unique bars across {n_syms} symbols.")
    return len(vals)


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-07-24"
    import_date(date)
