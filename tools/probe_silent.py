"""
==========================================================
py tools/probe_silent.py -- ask Dhan about the silent stocks
==========================================================

    "we have dhan library to check right? whats the issue to resolve"
                                -- operator, 8 August 2026

He is right. tools/silent_subscriptions.py found thirteen stocks that
are subscribed, carry a security id Dhan itself confirms, and have
never produced a single candle -- MOTHERSON among them, which he holds
2,000 shares of. That tool could only say "unexplained", because it
reads the local stores and nothing else.

The dhanhq client can settle it in one call. quote_data() takes the
same security ids the feed subscribes to and returns what Dhan has for
them RIGHT NOW. Three outcomes, and each one names a different fault:

    a quote comes back
        The instrument is fine and Dhan is willing to serve it. The
        fault is in the WebSocket path -- either the subscription is
        not reaching the feed, or the packet is arriving and being
        dropped before it is stored.

    the id is rejected / returns nothing
        The id is wrong for the segment we are asking on, whatever the
        scrip master says. NSE_EQ vs NSE_FNO vs BSE matters here.

    the whole call errors
        Token, static IP, or entitlement -- and it will say which.

WHY IT IS A SEPARATE FILE HE RUNS
---------------------------------
This has to talk to Dhan, and the environment I develop in has no
network route to them: fetching their public scrip master returns
"403 Forbidden". So the diagnosis cannot be run where the code is
written. It runs on his machine, against his token, and prints an
answer he can read without me.

It places no orders and modifies nothing. Read-only, one REST call.

    py tools/probe_silent.py                the 13 unexplained
    py tools/probe_silent.py MOTHERSON      just one
    py tools/probe_silent.py --all          every silent symbol

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANDLES_DB = "data/backtest_candles.db"
PROOF_PATH = os.path.join("data", "scrip_verified.json")
SESSIONS = 5

# A known-good control. If MOTHERSON returns nothing and this returns
# nothing too, the fault is the CALL, not the instrument -- and every
# other conclusion on the page would have been wrong.
CONTROL = "HINDALCO"


def _silent_symbols(loader):
    con = sqlite3.connect(CANDLES_DB)
    days = [r[0] for r in con.execute(
        "select distinct date from candles order by date desc limit ?",
        (SESSIONS,))]
    ever = set()
    for day in days:
        ever |= {r[0] for r in con.execute(
            "select distinct symbol from candles where date = ?", (day,))}
    con.close()
    return sorted(s for s in loader.all_symbols() if s not in ever), days


def _known_bad():
    try:
        with open(PROOF_PATH, encoding="utf-8") as handle:
            proof = json.load(handle) or {}
    except Exception:                                      # noqa: BLE001
        return set()
    bad = {str(s).upper() for s in (proof.get("not_found") or [])}
    for line in proof.get("mismatches") or []:
        bad.add(str(line).split(":", 1)[0].strip().upper())
    return bad


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_all = "--all" in sys.argv

    from core.master_loader import MasterLoader
    loader = MasterLoader()
    loader.load()

    if args:
        symbols = [a.strip().upper() for a in args]
        days = []
    else:
        silent, days = _silent_symbols(loader)
        symbols = silent if want_all else [s for s in silent
                                           if s not in _known_bad()]

    if CONTROL not in symbols:
        symbols = symbols + [CONTROL]

    print("=" * 72)
    print("  ASKING DHAN ABOUT THE SILENT STOCKS")
    if days:
        print(f"  silent across {days[-1]} to {days[0]}")
    print(f"  {len(symbols)} symbol(s), {CONTROL} included as a control")
    print("=" * 72)

    # ---- THE NAMES, READ NOT GUESSED. 8 August 2026. ----
    # config exports DHAN_CLIENT_ID, not CLIENT_ID. This is the fourth
    # identifier I have written from memory in this project and the
    # fourth that was wrong. Copied from tools/dhan_account_check.py,
    # which already talks to Dhan successfully.
    try:
        from config import (DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID,
                            EXCHANGE_SEGMENT)
        from dhanhq import DhanContext, dhanhq as DhanRestClient
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  Cannot load the client: {exc}")
        return 1

    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        print("\n  DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN are not set in the")
        print("  environment. Generate today's token first.")
        return 1

    try:
        client = DhanRestClient(DhanContext(DHAN_CLIENT_ID,
                                            DHAN_ACCESS_TOKEN))
    except Exception:                                      # noqa: BLE001
        # Older dhanhq took the two values directly.
        try:
            client = DhanRestClient(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        except Exception as exc:                           # noqa: BLE001
            print(f"\n  Cannot build the client: {exc}")
            return 1

    ids = {}
    for symbol in symbols:
        raw = loader.security_id(symbol)
        if raw is None:
            print(f"  {symbol:<14} no security id in the master")
            continue
        try:
            ids[symbol] = int(str(raw).strip())
        except ValueError:
            print(f"  {symbol:<14} security id {raw!r} is not a number")

    if not ids:
        print("\n  Nothing to ask about.")
        return 1

    print(f"\n  one quote_data() call on segment {EXCHANGE_SEGMENT} "
          f"for {len(ids)} id(s)...\n")
    try:
        reply = client.quote_data({EXCHANGE_SEGMENT: list(ids.values())})
    except Exception as exc:                               # noqa: BLE001
        print(f"  THE CALL ITSELF FAILED: {exc}")
        print("\n  That is a token / static-IP / entitlement problem, not")
        print("  an instrument problem. Nothing below can be trusted until")
        print("  this call succeeds -- try py tools/dhan_account_check.py")
        return 1

    # ---- dhanhq SWALLOWS ITS OWN FAILURES. 8 August 2026. ----
    #
    # It does not raise on a network or auth failure. It returns
    # {"status": "failure", "remarks": "...", "data": ""} and the
    # first version of this tool read that as "replied but carried no
    # quotes" -- which reads like an instrument problem and is not.
    #
    # Measured: from a machine with no route to Dhan the call comes
    # back as a plain dict with status=failure and a proxy error in
    # remarks. He must never be sent hunting an instrument fault when
    # the call never left the building.
    if isinstance(reply, dict) and str(reply.get("status", "")).lower() \
            in ("failure", "error", "false"):
        print(f"  THE CALL FAILED -- Dhan did not answer.\n")
        print(f"    {str(reply.get('remarks') or reply)[:400]}\n")
        print("  This is a network / token / static-IP problem, NOT an")
        print("  instrument problem. Nothing about MOTHERSON can be")
        print("  concluded from this run.")
        print("  Next: py tools/dhan_account_check.py")
        return 1

    # The reply shape has moved between dhanhq versions, so walk it
    # rather than assuming. Printing the raw keys once is cheaper than
    # a wrong reading of it.
    payload = reply.get("data") if isinstance(reply, dict) else None
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    quotes = {}
    if isinstance(payload, dict):
        for _segment, rows in payload.items():
            if isinstance(rows, dict):
                for security_id, row in rows.items():
                    quotes[str(security_id)] = row

    if not quotes:
        print(f"  Dhan replied but carried no quotes. Raw reply:\n")
        print(f"    {str(reply)[:600]}")
        return 1

    print(f"  {'SYMBOL':<14}{'ID':>9}  {'LTP':>11}  VERDICT")
    print("  " + "-" * 62)
    served, silent_at_dhan = [], []
    for symbol, security_id in ids.items():
        row = quotes.get(str(security_id))
        ltp = None
        if isinstance(row, dict):
            for key in ("last_price", "ltp", "LTP", "lastTradedPrice"):
                if row.get(key) is not None:
                    ltp = row.get(key)
                    break
        if ltp:
            served.append(symbol)
            verdict = "Dhan HAS it -- fault is in the feed path"
        else:
            silent_at_dhan.append(symbol)
            verdict = "Dhan returns nothing for this id"
        star = " *" if symbol == CONTROL else ""
        print(f"  {symbol:<14}{security_id:>9}  "
              f"{('%.2f' % ltp) if ltp else '--':>11}  {verdict}{star}")

    print("  " + "-" * 62)
    print(f"  * {CONTROL} is the control -- it must appear above with a "
          f"price.")
    print()
    if CONTROL in silent_at_dhan:
        print("  THE CONTROL CAME BACK EMPTY. The call is not working")
        print("  (market closed, wrong segment, or no data entitlement).")
        print("  Ignore every other line -- run this during market hours.")
        return 1

    if served:
        print(f"  {len(served)} instrument(s) Dhan serves happily:")
        print(f"     {', '.join(s for s in served if s != CONTROL)}")
        print("     -> the ids are right and Dhan has the data, so the")
        print("        break is between the subscription and the store.")
        print("        Next: one live session logging what on_message()")
        print("        actually receives for these ids.")
    if silent_at_dhan:
        print(f"\n  {len(silent_at_dhan)} that Dhan will not serve on "
              f"{EXCHANGE_SEGMENT}:")
        print(f"     {', '.join(silent_at_dhan)}")
        print("     -> wrong segment or a stale id. These cannot be")
        print("        traded and should leave the universe until fixed.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
