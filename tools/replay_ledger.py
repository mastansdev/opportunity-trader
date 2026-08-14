"""
==========================================================
py tools/replay_ledger.py  --  every order, every day, in full
==========================================================

    "which stocks were traded & on what basis entry - exit happened.
     give me complete info. do not give me end result unless i ask...
     provide me complete data along with timings of all stock entries
     - exits & reason of both"
                                -- operator, 11 August 2026

He is right to ask. tools/replay_day.py prints a day total and a
five-line summary, and I handed him twelve of those totals as if the
number were the answer. A total with no ledger behind it is exactly
the kind of thing I have been told repeatedly not to produce.

WHAT THIS IS
------------
The SAME replay. Not a second implementation and not a re-reading of
the code -- it imports tools/replay_day.py and runs its replay()
function untouched, so every gate, every price floor and every stop
rule is the one that produced the totals.

The only additions are bookkeeping:

  1. replay_day builds its ReplayEngine inside replay() and throws it
     away after printing. LedgerEngine subclasses it so the object
     survives the call.

  2. The order dict records entry_reason, which auto_entry sets to the
     constant "RANKED_SETUP" -- a label, not a reason. The real basis
     is the candidate row the ranker handed to auto_entry.take(): its
     score, its move, its volume against normal, and the sentence in
     `why`. So take() is wrapped to keep the row that was on the table
     at the instant the order went in, and that row is what gets
     printed.

  3. The exit walk (replay_day.exit_of) returns a three-word code.
     Alongside it this reports the highest and lowest price the stock
     printed after entry, so it is visible how near the trade came to
     its target and how far it went against the stop. Those two
     numbers are read straight off the tape -- they decide nothing.

Nothing is summed here. No totals, no averages, no verdict.

USAGE
-----
    py tools/replay_ledger.py                 every recorded day
    py tools/replay_ledger.py 2026-08-11      one day
    py tools/replay_ledger.py --csv data/replay_ledger.csv

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import io
import os
import sqlite3
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import replay_day                                   # noqa: E402


# The candidate rows on the table at the moment take() was called.
# Refreshed every step; read by LedgerEngine._enter.
LAST_PICKS = {}

# Every engine replay() builds lands here so its orders outlive the
# call. replay_day itself is not modified.
CAPTURED = []


class LedgerEngine(replay_day.ReplayEngine):
    def __init__(self, alert_only):
        super().__init__(alert_only)
        CAPTURED.append(self)

    def _enter(self, symbol, *args, **kwargs):
        before = len(self.orders)
        super()._enter(symbol, *args, **kwargs)
        # An order may not appear -- the Rs 50 floor refuses inside
        # _enter. Only decorate what actually became an order.
        if len(self.orders) > before:
            self.orders[-1]["pick"] = dict(LAST_PICKS.get(symbol) or {})


def _spy_on_take():
    """Keep the candidate rows take() is given, without changing what
    it does with them."""
    from core import auto_entry
    original = auto_entry.take

    def take(picks, *args, **kwargs):
        LAST_PICKS.clear()
        for row in (picks or []):
            name = (row or {}).get("symbol")
            if name:
                LAST_PICKS[name] = row
        return original(picks, *args, **kwargs)

    auto_entry.take = take
    return lambda: setattr(auto_entry, "take", original)


def recorded_days():
    con = sqlite3.connect(replay_day.CANDLES)
    try:
        return [r[0] for r in con.execute(
            "select distinct date from candles order by date")]
    finally:
        con.close()


def _extremes(con, day, symbol, after_minute):
    """Highest and lowest the tape printed after the entry bar. Read
    only -- no rule depends on these."""
    got = con.execute(
        "select max(h), min(l) from candles where date=? and symbol=? "
        "and minute>?", (day, symbol, after_minute)).fetchone()
    return (got or (None, None))


def orders_for(day):
    """Run the real replay for one day and hand back its orders, each
    walked forward to its exit by replay_day's own exit_of()."""
    CAPTURED.clear()
    LAST_PICKS.clear()
    original_engine = replay_day.ReplayEngine
    replay_day.ReplayEngine = LedgerEngine
    restore_take = _spy_on_take()
    try:
        # replay() prints its own summary. Swallow it -- this tool
        # prints the ledger, and two formats on one screen is how the
        # LIVE tab ended up unreadable.
        with redirect_stdout(io.StringIO()):
            replay_day.replay(day, switch_on=True)
    finally:
        replay_day.ReplayEngine = original_engine
        restore_take()

    if not CAPTURED:
        return []
    engine = CAPTURED[-1]

    con = sqlite3.connect(replay_day.CANDLES)
    out = []
    try:
        for order in engine.orders:
            exit_at, exit_px, how = replay_day.exit_of(
                con, day, order["symbol"], order["minute"], order["price"],
                order["stop"], order.get("target"))
            top, bottom = _extremes(con, day, order["symbol"],
                                    order["minute"])
            pick = order.get("pick") or {}
            out.append({
                "date": day,
                "entry_time": order.get("at_str"),
                "symbol": order["symbol"],
                "qty": order.get("qty"),
                "entry": order.get("price"),
                "stop": order.get("stop"),
                "target": order.get("target"),
                "why_in": _clean(pick.get("why")) or _clean(order.get("reason")),
                "score": pick.get("score"),
                "change_pct_at_entry": pick.get("change_pct"),
                "volume_x": pick.get("volume_x"),
                "turnover_cr": pick.get("turnover_cr"),
                "adv_cr": pick.get("adv_cr"),
                "sector": pick.get("sector"),
                "mechanism": _clean(pick.get("mechanism")),
                "high_after_entry": top,
                "low_after_entry": bottom,
                "exit_time": exit_at,
                "exit": exit_px,
                "why_out": _expand(how),
            })
    finally:
        con.close()

    # The engine refuses below the Rs 50 floor AFTER auto_entry has
    # said yes. Those never became orders, but he asked for complete
    # information and a silent refusal is not complete.
    for symbol, why in getattr(engine, "refused_by_engine", []) or []:
        row = {key: None for key in (out[0] if out else {})}
        row.update({"date": day, "entry_time": "--", "symbol": symbol,
                    "why_in": "REFUSED AT THE ORDER GATE: " + why,
                    "exit_time": "--", "why_out": "--"})
        out.append(row)
    return out


def _clean(text):
    return " ".join(str(text or "").split())


def _expand(how):
    """The exit walk returns a three-word code. Say what it means."""
    return {
        "stop": "HARD STOP -- price traded down through the seed stop",
        "1:1 lock": "TRAILING STOP -- it had run 1.5R, so the stop was "
                    "moved up to entry + 1R, and price came back to it",
        "still open": "NEVER EXITED -- valued at the last recorded candle "
                      "of the session",
        "no data": "NO CANDLES after entry -- nothing to walk",
    }.get(how, how or "--")


def _n(value, places=2):
    return f"{value:,.{places}f}" if isinstance(value, (int, float)) else "--"


FIELDS = ["date", "entry_time", "symbol", "qty", "entry", "stop", "target",
          "why_in", "score", "change_pct_at_entry", "volume_x",
          "turnover_cr", "adv_cr", "sector", "mechanism",
          "high_after_entry", "low_after_entry",
          "exit_time", "exit", "why_out"]


def main(argv):
    csv_path = None
    argv = list(argv)
    if "--csv" in argv:
        spot = argv.index("--csv")
        csv_path = argv[spot + 1] if spot + 1 < len(argv) else \
            "data/replay_ledger.csv"
        del argv[spot:spot + 2]
    days = [a for a in argv if not a.startswith("--")] or recorded_days()

    every = []
    for day in days:
        rows = orders_for(day)
        every.extend(rows)

        print()
        print("=" * 78)
        print(f"  {day}     {len(rows)} entr(y/ies)")
        print("=" * 78)
        if not rows:
            print("  No orders on this tape.")
            continue
        for row in rows:
            print()
            print(f"  IN   {row['entry_time']}   BUY {row['symbol']}"
                  f"   qty {row['qty'] if row['qty'] is not None else '--'}"
                  f"   at Rs {_n(row['entry'])}")
            if row.get("score") is not None:
                print(f"       score {_n(row['score'], 1)}"
                      f" | up {_n(row['change_pct_at_entry'], 1)}% on the day"
                      f" | {_n(row['volume_x'], 1)}x normal volume"
                      f" | Rs {_n(row['turnover_cr'], 1)} Cr traded"
                      f" (normal day Rs {_n(row['adv_cr'], 1)} Cr)")
            print(f"       WHY IN  : {row['why_in']}")
            if row.get("mechanism"):
                print(f"       BEHIND  : {row['mechanism'][:150]}")
            if row.get("stop") is not None:
                print(f"       stop Rs {_n(row['stop'])}"
                      f"   target Rs {_n(row['target'])}")
            if row.get("high_after_entry") is not None:
                print(f"       after entry it printed a high of"
                      f" Rs {_n(row['high_after_entry'])}"
                      f" and a low of Rs {_n(row['low_after_entry'])}")
            print(f"  OUT  {row['exit_time']}   at Rs {_n(row['exit'])}")
            print(f"       WHY OUT : {row['why_out']}")

    if csv_path:
        target = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            csv_path) if not os.path.isabs(csv_path) else csv_path
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(every)
        print()
        print(f"  Written: {target}  ({len(every)} row(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
