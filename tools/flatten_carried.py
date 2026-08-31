"""
==========================================================
Close a position the bot has been carrying, and say so
==========================================================

    py tools/flatten_carried.py                 # show what is carried
    py tools/flatten_carried.py --close         # close it at the last price

    "why it still held"                       -- the operator, 31 Aug 2026

WHY THIS HAD TO EXIST
---------------------
On 31 August the bot was still holding NCC and CDSL, both opened on 21
August at 12:41 and 12:49. Ten days, in a bot that scans 09:15-15:30
and books "when momentum exhausted".

Nothing was broken, which is the worrying part. FORCE_SQUARE_OFF_AT_CLOSE
had been False since 28 July, so nothing force-closed at the close; the
end-of-day sweep only REPORTED what was being carried. The trailing
stops were live the whole time and simply never fired. So the positions
sat, correctly, for nine sessions, and no line of code thought anything
was wrong.

The config is fixed. This exists for what the config fix cannot reach:
the positions already sitting in data/session_state.json.

WHAT IT DOES
------------
Closes at the last price the dashboard has, writes the trade to
trade_memory with an exit reason that says exactly what happened, and
removes it from the open book. Backs up the state file first.

WHAT IT WILL NOT DO
-------------------
It will not touch a real position. This only rewrites the bot's own
paper book. A real position is closed at the broker, by him, or by a
stop -- never by a maintenance script reaching into a JSON file.
"""

import argparse
import json
import os
import shutil
import sqlite3
import urllib.request
from datetime import datetime

STATE = os.path.join("data", "session_state.json")
TRADES_DB = os.path.join("data", "trade_memory.db")
SNAPSHOT = "http://127.0.0.1:8000/api/snapshot"


CANDLES_DB = os.path.join("data", "backtest_candles.db")


def last_prices(symbols=()):
    """{symbol: last_price}.

    ---- IT NEEDED A RUNNING DASHBOARD. 31 August 2026. ----

    This read the live snapshot and returned {} if the snapshot was not
    there. He ran it after main.py had exited, so every position printed
    "no last price available, cannot close" and nothing closed -- a
    maintenance tool that only works while the thing it is maintaining
    is running.

    The dashboard is still tried first: it is the freshest price and, if
    the process is up, the one he is looking at. The candle store is the
    fallback, and it is on disk whether anything is running or not.
    """
    out = {}
    try:
        snap = json.load(urllib.request.urlopen(SNAPSHOT, timeout=5))
        out = {p["symbol"]: p.get("last_price") or p.get("cmp")
               for p in snap.get("open_positions", [])
               if p.get("last_price") or p.get("cmp")}
    except Exception:                                      # noqa: BLE001
        pass

    missing = [s for s in symbols if s not in out]
    if not missing or not os.path.exists(CANDLES_DB):
        return out
    try:
        conn = sqlite3.connect(f"file:{CANDLES_DB}?mode=ro", uri=True)
        for symbol in missing:
            row = conn.execute(
                "SELECT c FROM candles WHERE symbol = ? "
                "ORDER BY date DESC, minute DESC LIMIT 1", (symbol,)).fetchone()
            if row and row[0]:
                out[symbol] = row[0]
        conn.close()
    except sqlite3.Error:
        pass
    return out


def carried(state, today):
    """Positions opened before today. A position opened TODAY is not
    carried, it is simply open, and must not be swept up by this."""
    out = []
    for symbol, pos in (state.get("open_positions") or {}).items():
        opened = str(pos.get("entry_time") or "")[:10]
        if opened and opened < today:
            out.append((symbol, pos, opened))
    return out


def main():
    ap = argparse.ArgumentParser(description="Close carried positions.")
    ap.add_argument("--close", action="store_true",
                    help="actually close them; without this it only reports")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()

    if not os.path.exists(STATE):
        print("  no session state to read")
        return 0
    state = json.load(open(STATE, encoding="utf-8"))
    rows = carried(state, args.date)
    if not rows:
        print("  nothing is being carried. Every open position was "
              "opened today.")
        return 0

    prices = last_prices([symbol for symbol, _, _ in rows])
    print(f"  {len(rows)} position(s) carried from an earlier session:")
    plan = []
    for symbol, pos, opened in rows:
        price = prices.get(symbol)
        entry = pos.get("entry_price")
        qty = pos.get("qty") or 0
        days = (datetime.fromisoformat(args.date)
                - datetime.fromisoformat(opened)).days
        if price is None or entry is None:
            print(f"    {symbol:8s} opened {opened} ({days} days) -- no last "
                  f"price available, cannot close")
            continue
        pnl = (price - entry) * qty
        print(f"    {symbol:8s} opened {opened} ({days} days)  qty {qty}  "
              f"in {entry:,.2f}  now {price:,.2f}  Rs {pnl:+,.2f}")
        plan.append((symbol, pos, opened, price, qty, entry, pnl))

    if not args.close:
        print()
        print("  Nothing changed. Run again with --close to close them.")
        return 0
    if not plan:
        print("  nothing closeable")
        return 1

    backup = f"{STATE}.bak-flatten-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(STATE, backup)
    print(f"\n  state backed up to {backup}")

    conn = sqlite3.connect(TRADES_DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(trade_memory)")}
    exit_at = f"{args.date} 15:30:00"

    for symbol, pos, opened, price, qty, entry, pnl in plan:
        entered = str(pos.get("entry_time") or "").replace("T", " ")[:19]
        try:
            held = (datetime.fromisoformat(exit_at)
                    - datetime.fromisoformat(entered)).total_seconds() / 60.0
        except ValueError:
            held = None
        row = {
            "symbol": symbol, "direction": "LONG", "trade_date": args.date,
            "entry_time": entered, "exit_time": exit_at,
            "entry_price": entry, "exit_price": price, "qty": qty,
            "pnl": round(pnl, 2), "holding_minutes": held,
            "entry_reason": pos.get("entry_reason") or "RANKED_SETUP",
            # The exit reason is the finding. Anyone reading this trade
            # later must see that it was not a rule that closed it.
            "exit_reason": "CARRIED_OVERNIGHT_CLOSED_BY_HAND",
            "sector": pos.get("sector"),
        }
        use = {k: v for k, v in row.items() if k in cols}
        conn.execute(
            f"INSERT INTO trade_memory ({','.join(use)}) "
            f"VALUES ({','.join('?' * len(use))})", tuple(use.values()))
        del state["open_positions"][symbol]
        print(f"  closed {symbol:8s} @ {price:,.2f}   Rs {pnl:+,.2f}")

    conn.commit()
    conn.close()
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    print(f"  open positions now: {len(state.get('open_positions') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
