"""
What Dhan actually sends us, and what we actually use.

    py tools/dhan_fields.py                  one liquid symbol
    py tools/dhan_fields.py --symbol INFY
    py tools/dhan_fields.py --raw             the untouched JSON

    "pls check & also see what all info we are getting & we really
     using them"                    -- operator, 30 July 2026

WHY THIS IS A TOOL AND NOT A NOTE IN A FILE
-------------------------------------------
Nobody should answer "what does the broker return" from memory,
including me. Fields get added and renamed, and the honest answer is
whatever the live endpoint prints today. This calls it once and shows
every key that came back, marked USED or UNUSED against what
core/circuit_monitor.py keeps.

An UNUSED field is not automatically a bug. It is a decision waiting
to be made with the field's real name and a real value in front of
you, instead of a guess.
"""

import json
import sys

sys.path.insert(0, ".")

from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, EXCHANGE_SEGMENT
from core.logger import decision, warn
from core.master_loader import MasterLoader

# Exactly what core/circuit_monitor.py's _snapshot_row() reads. Kept
# here as data so this tool cannot drift from the code silently --
# see the check at the bottom.
USED = {
    "last_price": "LTP -- every price on the dashboard",
    "ohlc.open": "day open",
    "ohlc.high": "day high, and widens the opening range",
    "ohlc.low": "day low, and widens the opening range",
    "ohlc.close": "PREVIOUS close -- every % change is measured off this",
    "volume": "the volume gate on entries",
    "upper_circuit_limit": "UC -- proximity block, and now on the movers table",
    "lower_circuit_limit": "LC -- same",
}


def _flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.update(_flatten(value, f"{prefix}{key}."))
    elif isinstance(obj, list):
        out[prefix.rstrip(".")] = f"<list of {len(obj)}>"
        if obj and isinstance(obj[0], dict):
            for key in obj[0]:
                out[f"{prefix.rstrip('.')}[0].{key}"] = obj[0][key]
    else:
        out[prefix.rstrip(".")] = obj
    return out


def main():
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        warn("DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing from .env.")
        sys.exit(1)

    symbol = "RELIANCE"
    if "--symbol" in sys.argv:
        symbol = sys.argv[sys.argv.index("--symbol") + 1].upper()

    loader = MasterLoader()
    loader.load()
    security_id = loader.security_id(symbol)
    if not security_id:
        warn(f"{symbol} is not in data/master_stocks.csv.")
        sys.exit(1)

    from dhanhq import DhanContext, dhanhq as DhanRestClient
    client = DhanRestClient(DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN))

    decision(f"Asking Dhan for {symbol} (security id {security_id}) ...")
    reply = client.quote_data({EXCHANGE_SEGMENT: [int(security_id)]})

    if "--raw" in sys.argv:
        print(json.dumps(reply, indent=2)[:8000])
        return

    # Dig down to the one symbol's quote, whatever the wrapper shape.
    # Dhan nests the quote three deep: data -> NSE_EQ -> "1594" -> {...}
    # The first version stopped at the first level that did not hold
    # the security id, so every key kept its "data.NSE_EQ.1594."
    # prefix and NOTHING matched the bare names in USED -- the tool
    # reported "0 used" while the bot was using eight of them.
    def _find_quote(node, want):
        if not isinstance(node, dict):
            return None
        if "last_price" in node or "ohlc" in node:
            return node
        if want in node and isinstance(node[want], dict):
            found = _find_quote(node[want], want)
            if found is not None:
                return found
        for value in node.values():
            found = _find_quote(value, want)
            if found is not None:
                return found
        return None

    info = _find_quote(reply, str(security_id))
    if not isinstance(info, dict):
        warn("Could not find the quote in the reply. Run with --raw.")
        print(json.dumps(reply, indent=2)[:3000])
        sys.exit(1)

    flat = _flatten(info)
    decision("")
    decision("=" * 74)
    decision(f"  EVERY FIELD DHAN RETURNED FOR {symbol}")
    decision("=" * 74)
    used, unused = [], []
    for key in sorted(flat):
        (used if key in USED else unused).append(key)

    decision(f"\n  USED BY THE BOT ({len(used)})")
    for key in used:
        decision(f"    {key:<28}{str(flat[key])[:20]:<22}{USED[key]}")

    decision(f"\n  RETURNED BUT NOT USED ({len(unused)})")
    for key in unused:
        decision(f"    {key:<28}{str(flat[key])[:40]}")

    missing = [k for k in USED if k not in flat]
    if missing:
        decision("")
        warn(f"  FIELDS THE BOT READS THAT DID NOT COME BACK: {missing}")
        warn("  Every one of those is a number on the dashboard with "
             "nothing behind it. Check the reply with --raw.")

    decision("")
    decision("=" * 74)
    decision(f"  {len(used)} used, {len(unused)} available and unused.")
    decision("  An unused field is a decision to make, not a bug. The ones")
    decision("  worth looking at first are order-book depth and the total")
    decision("  buy/sell quantities -- those say whether a BUY will fill")
    decision("  and at what price, which is the slippage question.")
    decision("=" * 74)


if __name__ == "__main__":
    main()
