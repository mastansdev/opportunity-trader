"""
==========================================================
READ-ONLY: what does Dhan actually say about this account?
==========================================================
    py tools/dhan_account_check.py
    py tools/dhan_account_check.py --symbol REDINGTON

PLACES NOTHING. SPENDS NOTHING. CANCELS NOTHING.

Every call here is a GET. There is no place_order in this file and
there never should be -- the whole point is that it can be run at any
hour, in any mood, without a decision attached.

WHY, 30 July 2026
-----------------
    "no need to wait till market open. we can try right now from our
     dashboard. pls try shift from paper mode to live mode. dhan has
     facility of after market trades. may be we will get data of ID,
     security & all"

Two things stop the dashboard BUY button working after hours, and
neither is a setting:

  1. The manual BUY is TICK-DRIVEN. core/engine.py acts on it inside
     process_tick(), so the request sits in trade_controller until a
     price arrives. After the close the feed is shut and no tick ever
     comes -- the click would be silently swallowed, which is the worst
     possible outcome because it looks like nothing happened.

  2. trading/live_execution.py sends ordinary MARKET and LIMIT orders.
     There is no AMO field anywhere in it. Dhan's after-market facility
     needs the order flagged as AMO; a plain market order outside
     session hours gets rejected by the exchange, not queued.

But the ACCOUNT half of the question -- the ID, the security, the funds,
whether the token even works -- is all readable right now. That is what
this does. It answers "is the plumbing real" without answering it by
spending money.

Author : H&M Opportunity Trader
==========================================================
"""

import sys

sys.path.insert(0, ".")

from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN     # noqa: E402
from core.logger import decision, warn                   # noqa: E402
from core.master_loader import MasterLoader              # noqa: E402


def _line():
    decision("-" * 66)


def _show(label, value):
    decision(f"  {label:26} {value}")


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


def main(symbol=None):
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        warn("DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing from .env.")
        return

    decision("=" * 66)
    decision("  DHAN ACCOUNT CHECK -- read only, nothing is placed")
    decision("=" * 66)
    _show("client id", str(DHAN_CLIENT_ID)[:4] + "..." + str(DHAN_CLIENT_ID)[-3:])
    _show("token length", f"{len(DHAN_ACCESS_TOKEN)} chars")

    try:
        from dhanhq import DhanContext, dhanhq as DhanRestClient
    except Exception as exc:                              # noqa: BLE001
        warn(f"dhanhq is not installed: {exc}")
        return

    try:
        context = DhanContext(DHAN_CLIENT_ID, _live_token())
        client = DhanRestClient(context)
    except Exception as exc:                              # noqa: BLE001
        warn(f"Could not build the Dhan client: {exc}")
        return
    decision("  client built OK")

    # ---- 1. does the token actually authenticate? --------------------
    _line()
    decision("  FUNDS  (proves the token is live -- this is the call that")
    decision("          fails first if it has expired)")
    try:
        funds = client.get_fund_limits()
        data = (funds or {}).get("data") or funds or {}
        if isinstance(data, dict):
            for key in ("availabelBalance", "availableBalance",
                        "sodLimit", "collateralAmount", "utilizedAmount",
                        "withdrawableBalance"):
                if key in data:
                    _show(key, data[key])
            if not any(k in data for k in ("availabelBalance",
                                           "availableBalance")):
                _show("raw", str(data)[:200])
        else:
            _show("raw", str(data)[:200])
    except Exception as exc:                              # noqa: BLE001
        warn(f"  get_fund_limits failed: {exc}")
        warn("  If this says 'Invalid token', regenerate it in the Dhan "
             "app -- everything below will fail for the same reason.")

    # ---- 2. what does Dhan think we hold? ----------------------------
    _line()
    decision("  POSITIONS  (this is what core/broker_sync.py compares the")
    decision("              bot's own book against)")
    try:
        positions = client.get_positions()
        rows = (positions or {}).get("data") or []
        if not rows:
            decision("  none open at the broker")
        for row in rows if isinstance(rows, list) else []:
            _show(str(row.get("tradingSymbol") or row.get("securityId")),
                  f"net {row.get('netQty')} | product "
                  f"{row.get('productType')} | avg {row.get('costPrice')}")
    except Exception as exc:                              # noqa: BLE001
        warn(f"  get_positions failed: {exc}")

    _line()
    decision("  HOLDINGS  (delivery stock, separate from intraday/MTF)")
    try:
        holdings = client.get_holdings()
        rows = (holdings or {}).get("data") or []
        if not rows:
            decision("  none")
        for row in (rows if isinstance(rows, list) else [])[:15]:
            _show(str(row.get("tradingSymbol") or row.get("securityId")),
                  f"qty {row.get('totalQty')} | avg {row.get('avgCostPrice')}")
    except Exception as exc:                              # noqa: BLE001
        warn(f"  get_holdings failed: {exc}")

    # ---- 3. today's orders -------------------------------------------
    _line()
    decision("  ORDERS TODAY")
    try:
        orders = client.get_order_list()
        rows = (orders or {}).get("data") or []
        if not rows:
            decision("  none -- this account has sent no orders today")
        for row in (rows if isinstance(rows, list) else [])[:15]:
            _show(str(row.get("tradingSymbol")),
                  f"{row.get('transactionType')} {row.get('quantity')} "
                  f"{row.get('orderType')} {row.get('productType')} -> "
                  f"{row.get('orderStatus')}")
    except Exception as exc:                              # noqa: BLE001
        warn(f"  get_order_list failed: {exc}")

    # ---- 4. the security id the bot would send ------------------------
    if symbol:
        _line()
        decision(f"  SECURITY ID FOR {symbol}")
        loader = MasterLoader()
        loader.load()
        security_id = loader.security_id(symbol.upper())
        record = loader.get_by_symbol(symbol.upper()) or {}
        _show("security id (our master)", security_id or "NOT FOUND")
        _show("company", record.get("COMPANY NAME"))
        _show("tradeable (SUBSCRIBE)", record.get("SUBSCRIBE"))
        if security_id:
            decision("  asking Dhan for a quote on that id...")
            try:
                from config import EXCHANGE_SEGMENT
                quote = client.quote_data({EXCHANGE_SEGMENT: [int(security_id)]})
                payload = (quote or {}).get("data") or quote
                _show("Dhan replied", str(payload)[:220])
                decision("  If the price above is this stock's real price, "
                         "the id is right and an order would reach the "
                         "right instrument.")
            except Exception as exc:                      # noqa: BLE001
                warn(f"  quote_data failed: {exc}")

    _line()
    decision("  Nothing was placed. Nothing was cancelled. Nothing was spent.")
    decision("")
    decision("  WHY THE DASHBOARD BUY WOULD DO NOTHING RIGHT NOW:")
    decision("    1. the manual BUY is handled inside process_tick(), and")
    decision("       with the feed closed no tick ever arrives -- the")
    decision("       request would sit unread rather than fail loudly")
    decision("    2. trading/live_execution.py has no AMO field, so an")
    decision("       after-hours order is rejected by the exchange, not")
    decision("       queued for the morning")
    decision("")
    decision("  Both are fixable. Neither is a config switch.")


if __name__ == "__main__":
    wanted = None
    if "--symbol" in sys.argv:
        index = sys.argv.index("--symbol")
        if len(sys.argv) > index + 1:
            wanted = sys.argv[index + 1]
    main(wanted)
