"""
==========================================================
Does the bot agree with NSE?  -- run it while the market is open
==========================================================

    py tools/nse_check.py                # the comparison
    py tools/nse_check.py --all          # every symbol, not just the bad ones
    py tools/nse_check.py --symbol INFY  # one stock, in full detail

    "NSE & BOT are not synchronised ... do not deviate from NSE"
                                        -- operator, 2026-07-29

WHAT IT DOES
------------
Reads the bot's live prices from the running dashboard, reads NSE's own
live prices from nseindia.com, and puts them side by side.

It changes nothing. It cannot place, close or modify an order. The bot
does not need to be restarted, and nothing about its behaviour changes
while this runs -- it reads one read-only endpoint.

WHY THE ANSWER MATTERS
----------------------
Every other measurement in this system is computed from the bot's own
prices. If the percentage base is wrong, the shortlist ranking is
wrong, the sector heatmap is wrong, and any study of the exit rules is
tuned against a corrupted number.

WHAT THE OUTPUT MEANS
---------------------
Three different faults look different here, on purpose:

    PRICE matches, % differs
        -> prev_close is wrong. Usually a split or bonus where NSE
           adjusted the previous close and the bot's copy did not.

    PRICE differs too
        -> the feed is behind. The % is just inheriting that.

    Both off by a hair
        -> the two screens were read a second apart. Not a bug.

Run it at 09:20 -- early enough that a bad previous close is still
obvious, late enough that both sides have real trade prices.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.nse_quotes import NseQuotes, requests_fetcher      # noqa: E402
from config import DASHBOARD_HOST, DASHBOARD_PORT            # noqa: E402

BOT_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/api/price_check"

# Below these, the two sides agree for practical purposes -- two
# screens read a second apart will always differ slightly.
PRICE_TOLERANCE_PCT = 0.15
PCT_TOLERANCE = 0.10


def fetch_bot():
    """The bot's own numbers, from the running dashboard."""
    import requests
    response = requests.get(BOT_URL, timeout=15)
    response.raise_for_status()
    return response.json()


def classify(bot, nse):
    """Which of the three faults is this? Returns (verdict, detail)."""
    bot_last, nse_last = bot.get("last"), nse.get("last")
    bot_pct, nse_pct = bot.get("change_pct"), nse.get("pct")

    if bot_last is None or nse_last is None:
        return "NO PRICE", "one side has no price"

    price_gap_pct = abs(bot_last - nse_last) / nse_last * 100
    price_ok = price_gap_pct <= PRICE_TOLERANCE_PCT

    if bot_pct is None or nse_pct is None:
        return ("OK" if price_ok else "PRICE"), "no % on one side"

    pct_gap = abs(bot_pct - nse_pct)
    pct_ok = pct_gap <= PCT_TOLERANCE

    if price_ok and pct_ok:
        return "OK", ""
    if price_ok and not pct_ok:
        # The important one. Same price, different percentage, so the
        # base the bot divides by is not NSE's.
        bot_prev, nse_prev = bot.get("prev_close"), nse.get("prev_close")
        detail = "prev close differs"
        if bot_prev and nse_prev:
            detail = (f"prev close bot {bot_prev:,.2f} vs "
                      f"NSE {nse_prev:,.2f}")
        return "PREV CLOSE", detail
    if not price_ok and pct_ok:
        return "PRICE", f"price off {price_gap_pct:.2f}%"
    return "BOTH", f"price off {price_gap_pct:.2f}%, % off {pct_gap:.2f}"


def one_symbol(symbol, bot_rows, nse):
    row = next((r for r in bot_rows if r["symbol"] == symbol.upper()), None)
    quote = nse.get(symbol)
    print()
    print("=" * 72)
    print(f"  {symbol.upper()}")
    print("=" * 72)
    if row is None:
        print("\n  The bot has no price for this symbol at all.")
        print("  It may not be subscribed, or no tick has arrived yet.\n")
    else:
        print(f"\n  BOT   last {_n(row['last'])}   prev close "
              f"{_n(row['prev_close'])}   change {_n(row['change_pct'])}%")
        print(f"        live tick {_n(row['live_tick'])}   "
              f"REST quote {_n(row['rest_quote'])}")
        print(f"        open {_n(row['open'])}  high {_n(row['high'])}  "
              f"low {_n(row['low'])}")
        print(f"        circuit  upper {_n(row['upper_circuit'])}  "
              f"lower {_n(row['lower_circuit'])}")
    if quote is None:
        print("\n  NSE did not return this symbol in any index list.\n")
    else:
        print(f"\n  NSE   last {_n(quote['last'])}   prev close "
              f"{_n(quote['prev_close'])}   change {_n(quote['pct'])}%")
        print(f"        open {_n(quote['open'])}  high {_n(quote['high'])}  "
              f"low {_n(quote['low'])}")
    if row is not None and quote is not None:
        verdict, detail = classify(row, quote)
        print(f"\n  VERDICT: {verdict}" + (f" -- {detail}" if detail else ""))
    print()


def _n(value):
    return "--" if value is None else f"{value:,.2f}"


def main():
    show_all = "--all" in sys.argv
    symbol = None
    if "--symbol" in sys.argv:
        i = sys.argv.index("--symbol")
        if i + 1 < len(sys.argv):
            symbol = sys.argv[i + 1]

    print("=" * 72)
    print("  BOT  vs  NSE")
    print("=" * 72)

    try:
        bot = fetch_bot()
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  Could not read the bot: {exc}")
        print(f"  Is main.py running? Expected {BOT_URL}\n")
        return 1
    rows = bot.get("rows") or []
    print(f"  bot   : {len(rows)} symbols priced   (read {bot.get('at')})")

    nse = NseQuotes(fetcher=requests_fetcher())
    collected = nse.refresh()
    print(f"  NSE   : {collected} symbols returned")
    for index, n in nse.sources_ok:
        print(f"            {index} -- {n}")
    for index in nse.sources_failed:
        print(f"            {index} -- FAILED")
    if collected == 0:
        print("\n  NSE returned nothing. Nothing can be compared.\n")
        return 1

    if symbol:
        one_symbol(symbol, rows, nse)
        return 0

    buckets = {"OK": [], "PREV CLOSE": [], "PRICE": [], "BOTH": [],
               "NO PRICE": [], "NOT ON NSE": []}
    for row in rows:
        quote = nse.get(row["symbol"])
        if quote is None:
            buckets["NOT ON NSE"].append((row, None, ""))
            continue
        verdict, detail = classify(row, quote)
        buckets[verdict].append((row, quote, detail))

    compared = sum(len(v) for k, v in buckets.items() if k != "NOT ON NSE")
    print()
    print("-" * 72)
    print(f"  {compared} symbols compared against NSE")
    print("-" * 72)
    for name in ("OK", "PREV CLOSE", "PRICE", "BOTH", "NO PRICE",
                 "NOT ON NSE"):
        print(f"    {name:<12} {len(buckets[name]):>5}")

    for name in ("PREV CLOSE", "BOTH", "PRICE"):
        entries = buckets[name]
        if not entries:
            continue
        print()
        print(f"  {name}  ({len(entries)})")
        print(f"    {'symbol':<14}{'bot':>11}{'NSE':>11}"
              f"{'bot %':>9}{'NSE %':>9}   note")
        shown = entries if show_all else entries[:25]
        for row, quote, detail in shown:
            print(f"    {row['symbol']:<14}{_n(row['last']):>11}"
                  f"{_n(quote['last']):>11}{_n(row['change_pct']):>9}"
                  f"{_n(quote['pct']):>9}   {detail}")
        if len(entries) > len(shown):
            print(f"    ... {len(entries) - len(shown)} more (--all to see)")

    print()
    if not buckets["PREV CLOSE"] and not buckets["BOTH"] \
            and not buckets["PRICE"]:
        print("  The bot agrees with NSE on every symbol compared.\n")
    else:
        print("  PREV CLOSE rows are the ones that matter most -- the price")
        print("  is right and the percentage is not, which means the base")
        print("  the bot divides by is not NSE's.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
