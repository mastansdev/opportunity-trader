"""
==========================================================
Replay ALL stored sessions -- the multi-day verdict
==========================================================

    py backtest/replay_all.py                    # every stored session
    py backtest/replay_all.py --from 2026-06-01  # a slice
    py backtest/replay_all.py --report           # re-print the last run

backtest/monday_replay.py answers "what would the bot have done on ONE
day". Every open question in POST_MONDAY_TODO needs the same answer
across MANY days, because a single session cannot separate an edge from
a mood. This runs the identical rule set over every session in the
corpus and aggregates.

Each session is replayed INDEPENDENTLY -- ORB, ATR and relative
strength are all built from that day's own candles, and no state
carries across days. That independence is what makes the corpus usable
even though Dhan's intraday history is NOT corporate-action adjusted:
a rescale shows up as a gap BETWEEN days, and nothing here ever
compares one day to the next.

Results append to data/replay_all.json so a long run can be done in
slices and reported once.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import contextlib
import io
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg                                        # noqa: E402
from backtest.candle_store import CandleStore               # noqa: E402
from backtest.monday_replay import run_monday               # noqa: E402

HISTORY_DB = "sqlite:///data/history_candles.db"
RESULTS = os.path.join("data", "replay_all.json")


def _load():
    if os.path.exists(RESULTS):
        with open(RESULTS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(results):
    """
    ATOMIC. Write to a temp file in the same directory, flush, fsync,
    then rename over the target.

    2026-07-26: the first version wrote straight to RESULTS. Saving
    per session meant a run cut short mid-write left a HALF-WRITTEN
    json file, and the next run died on it -- losing every session
    already replayed. Exactly the torn-write failure ISSUES_LOG
    already records for the trade log; same fix.

    os.replace() is atomic on both POSIX and Windows, so a reader
    either sees the whole previous file or the whole new one.
    """
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    tmp = RESULTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, RESULTS)


def run(dates, store, results):
    for date in dates:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                r = run_monday(date, store=store, verbose=False)
        except Exception as exc:                        # noqa: BLE001
            print(f"  {date}  FAILED: {exc}")
            continue
        if not r:
            continue
        trades = r.pop("trade_list", [])
        r["longs"] = sum(1 for t in trades if t["dir"] == "LONG")
        r["shorts"] = sum(1 for t in trades if t["dir"] == "SHORT")
        r["best"] = max((t["pnl"] for t in trades), default=0.0)
        r["worst"] = min((t["pnl"] for t in trades), default=0.0)
        # Keep the trades themselves. Aggregates can tell you THAT the
        # strategy loses; only the individual fills can tell you WHERE.
        r["trades_detail"] = [
            dict(sym=t["sym"], dir=t["dir"], t0=t["t0"], rs=t["rs"],
                 entry=t["entry"], exit=t["exit"], qty=t["qty"],
                 pnl=t["pnl"], reason=t["reason"])
            for t in trades
        ]
        results[date] = r
        # Saved per session, not at the end: a long run gets done in
        # slices, and a slice that is cut short must not throw away the
        # sessions it already replayed.
        _save(results)
        print(f"  {date}  trades {r['trades']:>3}  win {r['win_rate']:>5.1f}%  "
              f"net Rs {r['net']:>10,.0f}")
    return results


def report(results):
    if not results:
        print("Nothing stored yet.")
        return 1
    days = sorted(results)
    nets = [results[d]["net"] for d in days]
    trades = [results[d]["trades"] for d in days]
    gross = sum(results[d]["gross"] for d in days)
    charges = sum(results[d]["charges"] for d in days)
    net = sum(nets)
    total_trades = sum(trades)
    green = [n for n in nets if n > 0]

    print("=" * 64)
    print(f"  REPLAY OVER {len(days)} SESSIONS   {days[0]} -> {days[-1]}")
    print("=" * 64)
    print(f"  Total trades      : {total_trades:,}   "
          f"({statistics.mean(trades):.1f}/session)")
    print(f"  GROSS P&L         : Rs {gross:>12,.0f}")
    print(f"  Charges           : Rs {charges:>12,.0f}   "
          f"({100*charges/gross:.0f}% of gross)" if gross > 0 else
          f"  Charges           : Rs {charges:>12,.0f}")
    print(f"  NET P&L           : Rs {net:>12,.0f}")
    print(f"  Net per trade     : Rs {net/total_trades:>12,.0f}")
    print(f"  Return on capital : {100*net/cfg.MIS_CAPITAL_RS:>12.2f}%  "
          f"over {len(days)} sessions")
    print()
    print(f"  Green sessions    : {len(green)}/{len(days)}  "
          f"({100*len(green)/len(days):.0f}%)")
    print(f"  Best session      : Rs {max(nets):>12,.0f}")
    print(f"  Worst session     : Rs {min(nets):>12,.0f}")
    print(f"  Median session    : Rs {statistics.median(nets):>12,.0f}")
    if len(nets) > 1:
        print(f"  Session std dev   : Rs {statistics.stdev(nets):>12,.0f}")

    # How much of the result is one lucky day? The single-session study
    # was carried entirely by one trade -- check whether that repeats.
    top = max(nets)
    print(f"  Net without best  : Rs {net-top:>12,.0f}")

    equity, peak, dd = 0.0, 0.0, 0.0
    for d in days:
        equity += results[d]["net"]
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    print(f"  Max drawdown      : Rs {dd:>12,.0f}")
    print("=" * 64)
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", default=None)
    p.add_argument("--to", dest="end", default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="only run this many not-yet-done sessions")
    p.add_argument("--report", action="store_true")
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()

    if args.reset and os.path.exists(RESULTS):
        os.remove(RESULTS)

    results = _load()
    if args.report:
        return report(results)

    store = CandleStore(url=HISTORY_DB)
    dates = [d for d in store.dates()
             if (not args.start or d >= args.start)
             and (not args.end or d <= args.end)
             and d not in results]
    if args.limit:
        dates = dates[:args.limit]

    if not dates:
        print("All requested sessions already replayed.")
        return report(results)

    print(f"Replaying {len(dates)} session(s)...")
    results = run(dates, store, results)
    _save(results)
    print(f"\nStored {len(results)} session(s) in {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
