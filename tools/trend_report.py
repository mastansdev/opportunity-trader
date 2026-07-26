"""
==========================================================
Trend Report -- the 7-day structure of every stock we can trade
==========================================================

    py tools/trend_report.py                  # the whole tradeable list
    py tools/trend_report.py PARAS KALYANKJIL DATAPATTERNS

Reads the daily history and prints what shape each stock has been
making: stepping up, stepping down, range-bound, or -- the case the
operator singled out -- an uptrend that has just BROKEN (stopped making
higher highs, then took out the previous day's low).

Writes data/trend_structure.csv so it can be opened in Excel and sorted.

This is OBSERVATION ONLY. Nothing here gates a trade. See
core/trend_structure.py for why.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.daily_store import DailyStore  # noqa: E402
from core.logger import decision, warn  # noqa: E402
from core.master_loader import MasterLoader  # noqa: E402
from core.trend_structure import analyse, describe  # noqa: E402

OUT_CSV = os.path.join("data", "trend_structure.csv")


def run(symbols=None, days=8, store=None, out_csv=OUT_CSV):
    store = store or DailyStore()
    stats = store.stats()
    if stats["days"] < 3:
        warn("Not enough daily history. Run: py tools/build_daily_history.py")
        return 1

    if not symbols:
        loader = MasterLoader()
        loader.load()
        symbols = loader.all_symbols()          # SUBSCRIBE = YES only

    rows = []
    for symbol in symbols:
        bars = store.history(symbol, days=days)
        result = analyse(bars)
        if result["structure"] == "UNKNOWN":
            continue
        rows.append(dict(
            symbol=symbol,
            structure=result["structure"],
            hh_streak=result["hh_streak"],
            ll_streak=result["ll_streak"],
            broke=result["broke_structure"] or "",
            pct_from_high=round(result["pct_from_high"] or 0, 2),
            pct_from_low=round(result["pct_from_low"] or 0, 2),
            days_since_high=result["days_since_high"],
            legs="|".join(result["legs"]),
            close=bars[-1]["close"] if bars else None,
        ))

    if not rows:
        warn("No symbol had enough history to analyse.")
        return 1

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    counts = Counter(r["structure"] for r in rows)
    decision("=" * 62)
    decision(f"  7-DAY STRUCTURE  ({len(rows)} stocks, "
             f"{stats['first']} -> {stats['last']})")
    decision("=" * 62)
    for label in ("STRONG_UP", "UPTREND", "RANGE", "DOWNTREND",
                  "STRONG_DOWN"):
        if counts.get(label):
            decision(f"  {label:<12} {counts[label]:>4}")

    broke_up = [r for r in rows if r["broke"] == "UP"]
    if broke_up:
        warn(f"  Uptrend just BROKE ({len(broke_up)}): "
             + ", ".join(r["symbol"] for r in sorted(
                 broke_up, key=lambda r: r["pct_from_high"])[:12]))

    stepping = sorted([r for r in rows if r["structure"] == "STRONG_UP"],
                      key=lambda r: -r["hh_streak"])[:12]
    if stepping:
        decision("  Longest higher-high runs: "
                 + ", ".join(f"{r['symbol']}({r['hh_streak']}d)"
                             for r in stepping))

    decision("-" * 62)
    decision(f"  Written: {out_csv}")
    return 0


def main():
    symbols = [s.upper() for s in sys.argv[1:]] or None
    if symbols:
        store = DailyStore()
        for symbol in symbols:
            bars = store.history(symbol, days=8)
            result = analyse(bars)
            decision(f"\n  {symbol}  ({result['bars']} daily bars)")
            decision(f"    {describe(result)}")
            if result["legs"]:
                decision(f"    legs (oldest->newest): "
                         f"{' '.join(result['legs'])}")
                decision(f"    close is {result['pct_from_high']:+.2f}% from "
                         f"the 7-day high, {result['pct_from_low']:+.2f}% "
                         f"from the low")
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
