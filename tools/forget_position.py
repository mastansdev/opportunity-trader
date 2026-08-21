"""Remove a position from the bot's own book. Places no order.

    "EVEN TODAY NILKAMAL IS ON DAHBOARD. WHY? this is 10 th time i'm
     telling u that stock was rejected & not sell/buy happened."
                                -- operator, 21 August 2026

NILKAMAL entered the book on 19 August as MANUAL_BUY_DASHBOARD while
TRADING_MODE was PAPER. No order ever reached Dhan -- the buy was
simulated and the protective sell that followed it was REJECTED by
the exchange. Nothing about it was ever real.

It has sat on his dashboard ever since, holding one of three seats,
because the bot carries MTF positions overnight (FORCE_SQUARE_OFF_AT_
CLOSE is False) and correctly refuses to sell a position it believes
is HIS rather than its own.

There was no way to say "this never happened". exit_all would have
booked a fake trade into the record; editing the engine's memory is
not something he should have to do. Hence this.

RUN IT WITH THE BOT STOPPED. The running engine holds the book in
memory and rewrites data/session_state.json on its heartbeat, so an
edit made underneath a live process is overwritten within the minute.

    py tools/forget_position.py NILKAMAL

Author : H&M Opportunity Trader
"""

import json
import pathlib
import shutil
import sys
from datetime import datetime

STATE = pathlib.Path(__file__).resolve().parents[1] / "data" / "session_state.json"

# Every place a symbol can be remembered as HELD. orb_ranges is the
# day's opening range and is keyed by symbol too -- harmless to leave,
# but leaving it means the next session still thinks the stock is one
# it was watching for a position.
KEYS = ("open_positions", "trailing_stops", "orb_ranges", "portfolio")


def forget(symbol, state_path=STATE, backup=True):
    """Strip `symbol` from the saved book. Returns what was removed."""
    symbol = str(symbol).upper().strip()
    if not symbol:
        raise ValueError("no symbol given")
    if not state_path.exists():
        raise FileNotFoundError(f"no state file at {state_path}")

    data = json.loads(state_path.read_text(encoding="utf-8"))
    removed = {}
    for key in KEYS:
        block = data.get(key)
        if isinstance(block, dict) and symbol in block:
            removed[key] = block.pop(symbol)
        elif isinstance(block, list):
            keep = [r for r in block
                    if str((r or {}).get("symbol", "")).upper() != symbol]
            if len(keep) != len(block):
                removed[key] = len(block) - len(keep)
                data[key] = keep

    if not removed:
        return {}

    if backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(state_path, state_path.with_suffix(f".{stamp}.bak"))
    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return removed


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    symbol = argv[1]
    try:
        removed = forget(symbol)
    except Exception as exc:                                # noqa: BLE001
        print(f"FAILED: {exc}")
        return 1
    if not removed:
        print(f"{symbol.upper()} is not in the saved book -- nothing to do.")
        return 0
    print(f"Removed {symbol.upper()} from: {', '.join(removed)}")
    print("A backup of the previous state sits beside it.")
    print("No order was placed and nothing at Dhan was touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
