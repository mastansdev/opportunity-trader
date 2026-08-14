"""
==========================================================
FIRST REAL ORDER -- the 30 July five-step test
==========================================================

    py tools/live_order_test.py --symbol COFORGE

Places real orders in your real Dhan account. Every step is confirmed
by YOU before it runs, and every step tells you what to check in the
Dhan app before the next one.

THE SEQUENCE, and why it is in this order
-----------------------------------------
    1  LIMIT order, 1 share, 10% away    can it PLACE?     no fill, no cost
    2  cancel it                         can it CANCEL?    no cost
    3  MARKET order, 1 share, MTF        can it FILL?      ~Rs 1,700 spent
    4  read the contract note            settles the STT question
    5  exit that 1 share                 can it CLOSE?

Steps 1 and 2 cost nothing. A limit order parked 10% below the market
cannot fill on any liquid stock, so it proves the plumbing -- auth,
security ID, MTF product, correlation ID, the response shape -- without
spending a rupee. Only step 3 buys anything, and it buys ONE share.

Step 4 is not a code test. Buy one share, hold it overnight or check
the contract note, and read the STT line. Public sources contradict
each other on whether a same-day MTF exit is charged intraday (0.025%)
or delivery (0.1% both sides) STT, and nobody here has seen a real one.
That single line settles what the whole cost model rests on.

WHAT THIS DOES NOT DO
---------------------
It does not touch the trading engine, the dashboard, or any strategy.
It is a plumbing test for the order path and nothing else.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ask(question):
    answer = input(f"\n  {question} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="COFORGE")
    parser.add_argument("--qty", type=int, default=1)
    args = parser.parse_args()

    from config import (
        TRADING_MODE, I_UNDERSTAND_THIS_PLACES_REAL_ORDERS, EXCHANGE_SEGMENT,
    )
    from core.master_loader import MasterLoader
    from trading.live_execution import LiveExecution

    print("=" * 70)
    print("  FIRST REAL ORDER TEST -- this places REAL orders")
    print("=" * 70)

    if TRADING_MODE.upper() != "LIVE" or not I_UNDERSTAND_THIS_PLACES_REAL_ORDERS:
        print(f"\n  TRADING_MODE            = {TRADING_MODE}")
        print(f"  I_UNDERSTAND_...        = {I_UNDERSTAND_THIS_PLACES_REAL_ORDERS}")
        print("\n  Both must be set in config.py before this can run.")
        print("  That is deliberate -- one switch is one typo away from")
        print("  spending money by accident.")
        return

    # ---- connect ----
    from dhanhq import DhanContext, dhanhq
    client_id = os.environ.get("DHAN_CLIENT_ID")
    token = os.environ.get("DHAN_ACCESS_TOKEN")
    if not client_id or not token:
        print("\n  DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set.")
        return
    dhan = dhanhq(DhanContext(client_id, token))

    master = MasterLoader()
    # Explicit, though get_by_symbol() now loads on demand. 31 July
    # 2026: this line was missing and the tool reported "REDINGTON not
    # found in the master database" about a stock sitting on row 560.
    master.load()
    record = master.get_by_symbol(args.symbol.upper())
    if not record:
        print(f"\n  {args.symbol} not found in the master database.")
        return
    security_id = record.get("SECURITY ID")

    # ---- live price ----
    quote = dhan.quote_data({EXCHANGE_SEGMENT: [int(security_id)]})
    try:
        body = quote["data"]["data"][EXCHANGE_SEGMENT][str(security_id)]
        price = float(body["last_price"])
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  could not read a live price ({exc}). Stopping.")
        return

    print(f"\n  symbol      {args.symbol.upper()}")
    print(f"  security id {security_id}")
    print(f"  live price  Rs {price:,.2f}")
    print(f"  quantity    {args.qty}")
    print(f"  worst case  Rs {price * args.qty:,.2f} of real money")

    execution = LiveExecution(dhan, price_lookup=lambda s: price)

    # ---- 1. place a limit order that cannot fill ----
    print("\n" + "-" * 70)
    print("  STEP 1  LIMIT order 10% below the market. It CANNOT fill.")
    print("-" * 70)
    if not ask("Place it?"):
        return
    result = execution.place_test_limit(security_id, args.symbol.upper(),
                                        price, quantity=args.qty)
    print(f"\n  {result}")
    if not result.get("success"):
        print("\n  STOP. Placing failed. Nothing else should run until this "
              "is understood.")
        return
    order_id = result["order_id"]
    print(f"\n  >>> CHECK YOUR DHAN APP NOW. Order {order_id} should be "
          f"visible, OPEN, and unfilled.")

    # ---- 2. cancel it ----
    print("\n" + "-" * 70)
    print("  STEP 2  Cancel that order.")
    print("-" * 70)
    if not ask("Cancel it?"):
        print(f"  Leaving {order_id} open. CANCEL IT YOURSELF in the app.")
        return
    print(f"\n  {execution.cancel(order_id)}")
    print("\n  >>> CHECK THE APP. It should be gone.")

    # ---- 3. a real market order ----
    print("\n" + "-" * 70)
    print(f"  STEP 3  MARKET order, {args.qty} share, MTF product.")
    print(f"          THIS SPENDS REAL MONEY -- about Rs {price * args.qty:,.0f}.")
    print("-" * 70)
    if not ask("Buy for real?"):
        print("\n  Stopped before spending anything. Steps 1 and 2 already "
              "proved the order path works.")
        return
    bought = execution.buy(security_id, args.symbol.upper(), price, args.qty,
                           "LIVE_ORDER_TEST")
    print(f"\n  {bought}")
    if not bought.get("success"):
        print("\n  Buy did not confirm. CHECK THE APP before doing anything "
              "else -- do not re-run this script.")
        return

    print("\n  >>> CHECK THE APP: position open, and note the MARGIN BLOCKED.")
    print("  >>> Then open the CONTRACT NOTE and read the STT line.")
    print("      That answers whether a same-day MTF exit is charged")
    print("      intraday (0.025%) or delivery (0.1% both sides) STT --")
    print("      the one number the whole cost model rests on.")

    # ---- 5. close it ----
    print("\n" + "-" * 70)
    print("  STEP 5  Sell it back.")
    print("-" * 70)
    print("  (Or hold it overnight if you want the interest line on the")
    print("   contract note too. Sell from the app in that case.)")
    if not ask("Sell it now?"):
        print(f"\n  Holding {args.qty} share of {args.symbol.upper()}. "
              f"Close it yourself when ready.")
        return
    print(f"\n  {execution.sell(security_id, args.symbol.upper(), price, args.qty, 'LIVE_ORDER_TEST_EXIT')}")

    print("\n" + "=" * 70)
    print("  Done. The order path is proven end to end with real money.")
    print("=" * 70)


if __name__ == "__main__":
    main()
