"""
==========================================================
Why did Dhan refuse the balance?
==========================================================

    py tools/dhan_funds_probe.py

Asks Dhan for the balance TWICE -- once over the home connection, once
through the static IP -- and prints exactly what came back each time.

WHY THIS EXISTS
---------------
main.py refused to start on 4 August 2026:

    WARNING: [FUNDS] No balance field in Dhan's reply.
             Keys: ['data', 'remarks', 'status']
    RuntimeError: TRADING_MODE is LIVE but Dhan's available balance
    could not be read.

The token was NOT the problem, though that is where I sent him first.
Read straight out of the JWT in .env: issued 00:50 UTC, expiring 00:50
UTC the next day, client id matching, twenty-three hours left. I had
guessed, he regenerated a working token for nothing, and it failed
again.

What those keys actually mean is that `data` came back EMPTY -- Dhan
refused the request -- and the reason is sitting in `remarks`.

THE HYPOTHESIS THIS TESTS
-------------------------
main.py builds two clients on purpose (see its own comment):

    dhan_rest_client   funds, quotes, circuit monitor -- HOME line,
                       "because reads need no static IP"
    dhan_order_client  orders only -- through the static IP SEBI
                       requires

That was true when it was written. If Dhan has since begun enforcing
the registered static IP on every authenticated call rather than only
on order placement, then the ONE call that bypasses the proxy is
exactly the one being refused -- which is what we are seeing.

tools/reconcile.py already routes its get_positions() through the
proxy, with the comment "Through the static IP, same as orders", so
the codebase half-believes this already.

This tool does not guess. It runs both and shows both.

NOTHING SECRET IS PRINTED. Not the token, not the proxy password.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID,      # noqa: E402
                    ORDER_PROXY, TRADING_MODE)
from core import order_route                                # noqa: E402
from core.logger import decision, warn                      # noqa: E402


def _line():
    decision("=" * 68)


def _describe(response):
    """What Dhan said, without inventing anything."""
    if response is None:
        return "no response object at all"
    if not isinstance(response, dict):
        return f"unexpected shape: {str(response)[:160]}"
    data = response.get("data")
    out = [f"status={response.get('status')!r}"]
    if response.get("remarks"):
        out.append(f"remarks={str(response.get('remarks'))[:220]!r}")
    if isinstance(data, dict) and data:
        for key in ("availabelBalance", "availableBalance", "sodLimit"):
            if key in data:
                out.append(f"{key}={data[key]}")
        if len(out) == 1:
            out.append(f"data keys={sorted(data)[:10]}")
    else:
        out.append(f"data={data!r}  <-- EMPTY means the call was refused")
    return "  ".join(out)


def _live_token():
    """The token main.py ACTUALLY uses, not the one in .env.

    ---- THIS TOOL WAS DIAGNOSING ITSELF. 18 August 2026. ----

        "BOT IS NOT CHECKING THE DHAN ACCOUNT. WHY?"

    Both probes built their client from DHAN_ACCESS_TOKEN, the static
    value in .env. main.py has not used that as its FIRST choice since
    core/dhan_auth.py arrived: it mints over TOTP, caches the result in
    data/dhan_token.json, and only falls back to .env --

        dhan_token = dhan_auth.access_token() or DHAN_ACCESS_TOKEN

    So with a healthy minted token in the cache, twenty hours from
    expiry, and a long-dead one in .env, these tools reported

        DH-901 Invalid_Authentication -- invalid or expired

    about a bot that was reading MTF margins off Dhan in the next
    window. This file's own docstring records the last time a wrong
    guess had him regenerate a working token for nothing; it was then
    doing the same thing in code.

    access_token() reads the cache and mints only when it must, so
    calling it from a diagnostic costs no quota.
    """
    try:
        from core import dhan_auth
        return dhan_auth.access_token() or DHAN_ACCESS_TOKEN
    except Exception:                                      # noqa: BLE001
        return DHAN_ACCESS_TOKEN


def _ask(use_proxy):
    from dhanhq import DhanContext, dhanhq as DhanRestClient

    client = DhanRestClient(DhanContext(DHAN_CLIENT_ID, _live_token()))
    if use_proxy:
        if not ORDER_PROXY:
            return "ORDER_PROXY is not configured -- nothing to test"
        order_route.route_orders_through(client, ORDER_PROXY)
    try:
        return _describe(client.get_fund_limits())
    except Exception as exc:                               # noqa: BLE001
        return f"the call itself raised: {type(exc).__name__}: {exc}"


def main():
    _line()
    decision("  WHY DID DHAN REFUSE THE BALANCE?")
    decision(f"  mode={TRADING_MODE}  client={DHAN_CLIENT_ID}")
    host = "not configured"
    if ORDER_PROXY:
        # Host only. The proxy carries a password.
        host = str(ORDER_PROXY).rsplit("@", 1)[-1]
    decision(f"  static IP route: {host}")
    _line()

    decision("  1. HOME connection  (what main.py uses for funds today)")
    decision(f"     {_ask(use_proxy=False)}")
    decision("")
    decision("  2. STATIC IP route  (what main.py uses for orders)")
    decision(f"     {_ask(use_proxy=True)}")
    _line()

    decision("  READ IT LIKE THIS")
    decision("    both show a balance      -> the route is not the problem;"
             " send me both lines.")
    decision("    only 2 shows a balance   -> Dhan now wants the static IP"
             " for reads too.")
    decision("    neither, same remarks    -> it is the account or the"
             " token, and remarks says which.")
    _line()
    return 0


if __name__ == "__main__":
    sys.exit(main())
