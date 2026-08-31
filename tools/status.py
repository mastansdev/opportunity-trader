"""
==========================================================
What the bot is set to, and what it is holding. No opinion.
==========================================================

    py tools/status.py

    "like this way u sounded very confident each time but in reality
     its opposite. how i can believe u now?"     -- 31 August 2026

He is right, and the honest answer is that he should not have to
believe me. On 31 August I told him the bot had made no trades and the
board was clean. It was holding NCC and CDSL, bought on 21 August, ten
days earlier. I had read the closed-trades store and spoken as if I had
read the system.

That is the pattern in every one of my mistakes that day: one source
read, whole-system claim made, said with confidence.

This file exists so his answer never comes from a summary again. It
reads the live state and prints it. It does not interpret, does not
grade, does not reassure. Every number here is one he can check
himself, and the command that checks it is printed beside it.

THE RULE FOR ANYTHING ADDED HERE
--------------------------------
If it cannot be read directly out of a file or a store, it does not
belong on this screen. No derived judgements, no "looks fine", no
health score. Those are the things that were confidently wrong.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

# Run as `py tools/status.py` and sys.path[0] is tools/, not the repo
# root, so `import config` fails. Every other tool here does this line;
# this one did not, and the first run printed "could not read config"
# for half its content -- silently wrong, in the file whose entire
# purpose is not being silently wrong.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE = os.path.join("data", "session_state.json")
TRADES_DB = os.path.join("data", "trade_memory.db")


def _rule(title):
    print()
    print(f"  {title}")
    print("  " + "-" * 72)


def _read_state():
    if not os.path.exists(STATE):
        return {}
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"    session_state.json unreadable: {exc}")
        return {}


def show_switch():
    _rule("WHOSE MONEY")
    try:
        import config
        from trading.execution import Execution
        print(f"    switch starts          "
              f"{'ON -- REAL' if Execution.live else 'OFF -- PAPER'}")
        print(f"    TRADING_MODE           {config.TRADING_MODE}")
        print(f"    ALERT_ONLY_MODE        {config.ALERT_ONLY_MODE}"
              f"{'   <- the bot is NOT trading' if config.ALERT_ONLY_MODE else ''}")
    except Exception as exc:                               # noqa: BLE001
        print(f"    could not read: {exc}")


def show_holdings(today):
    _rule("WHAT IT IS HOLDING RIGHT NOW")
    state = _read_state()
    book = state.get("open_positions") or {}
    if not book:
        print("    nothing open")
        return
    for symbol, pos in book.items():
        opened = str(pos.get("entry_time") or "")[:10]
        age = ""
        if opened:
            try:
                days = (datetime.fromisoformat(today)
                        - datetime.fromisoformat(opened)).days
                age = (f"   {days} DAYS AGO -- carried"
                       if days > 0 else "   today")
            except ValueError:
                age = ""
        print(f"    {symbol:10s} qty {pos.get('qty')}  "
              f"@ {pos.get('entry_price')}  opened {opened or '?'}{age}")
    if any(str(p.get("entry_time") or "")[:10] < today for p in book.values()):
        print()
        print("    Something is being carried from an earlier session.")
        print("    py tools/flatten_carried.py        to see it")
        print("    py tools/flatten_carried.py --close  to close it")


def show_rules():
    _rule("THE SETTINGS THAT DECIDE WHAT IT DOES")
    try:
        import config
    except Exception as exc:                               # noqa: BLE001
        print(f"    could not read config: {exc}")
        return
    for name in ("FORCE_SQUARE_OFF_AT_CLOSE", "SQUARE_OFF_TIME",
                 "ENABLE_SLOT_ROTATION", "EXIT_ON_MOMENTUM_EXHAUSTED",
                 "MOMENTUM_EXIT_MIN_MINUTES", "ENABLE_BOT_TRAILING_STOP",
                 "ENABLE_SHORT_TRADES", "RISK_PER_TRADE_RS",
                 "FIXED_STOP_LOSS_RS", "FIXED_TARGET_RS"):
        print(f"    {name:30s} {getattr(config, name, '<absent>')}")


def show_last_trade():
    _rule("WHEN IT LAST CLOSED A TRADE")
    if not os.path.exists(TRADES_DB):
        print("    no trade store")
        return
    try:
        conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT trade_date, symbol, exit_reason FROM trade_memory "
            "ORDER BY trade_date DESC, exit_time DESC LIMIT 1").fetchone()
        total = conn.execute("SELECT count(*) FROM trade_memory").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        print(f"    could not read: {exc}")
        return
    if not row:
        print("    it has never closed a trade")
        return
    print(f"    {row[0]}   {row[1]}   {row[2]}")
    print(f"    {total} closed trades on record in total")
    print("    py tools/day_report.py --date " + str(row[0]))


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print("=" * 78)
    print(f"  BOT STATUS  --  {today}")
    print("=" * 78)
    show_switch()
    show_holdings(today)
    show_rules()
    show_last_trade()
    print()
    print("  Every line above is read straight from a file or a store.")
    print("  Nothing here is a judgement, and nothing here is my word for it.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
