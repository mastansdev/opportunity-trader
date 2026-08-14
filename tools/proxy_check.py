"""
==========================================================
Is the static IP actually carrying our orders?
==========================================================
    py tools/proxy_check.py

READ ONLY. Places nothing, spends nothing.

WHY
---
31 July 2026. Three orders refused DH-905 Invalid IP, and the whole
day went into finding out why. The answer was that nothing was
whitelisted -- but it took hours because there was no way to ask "what
address does Dhan see us arriving from?" without placing an order and
reading the rejection.

This asks it directly, three ways:

    1. what this machine's own address is        (the home line)
    2. what address the proxy presents           (the static IP)
    3. whether Dhan accepts the proxied client   (a READ, not an order)

If (2) is not the number whitelisted at Dhan, orders will be refused,
and this says so in one line instead of one rejected order.

WHY IT ALSO CHECKS THE HOME ADDRESS
-----------------------------------
Because the split matters. NSE, the pre-open book and the RSS feeds
must keep leaving from the residential connection -- they block
datacenter addresses, which is why running the whole bot on a cloud
machine broke the news feeds when it was tried. If (1) and (2) are the
same number, the proxy is not doing anything and one of the two halves
is about to break.

Author : H&M Opportunity Trader
==========================================================
"""

import sys
import urllib.request

sys.path.insert(0, ".")

from config import (                                       # noqa: E402
    DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, ORDER_PROXY,
)
from core.logger import decision, warn                     # noqa: E402
from core.order_route import route_orders_through, safe_display  # noqa: E402

WHOAMI = "https://api.ipify.org"


def _line():
    decision("-" * 68)


def home_ip():
    try:
        with urllib.request.urlopen(WHOAMI, timeout=10) as response:
            return response.read().decode().strip()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  could not read this machine's own address: {exc}")
        return None


def proxy_ip(proxy_url):
    """The address the world sees when we go through the proxy.

    Deliberately uses the SAME question asked of the home line, so the
    two numbers are directly comparable. If they match, the proxy is
    not in the path.
    """
    if not proxy_url:
        return None
    try:
        handler = urllib.request.ProxyHandler(
            {"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        with opener.open(WHOAMI, timeout=20) as response:
            return response.read().decode().strip()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  the proxy did not answer: {exc}")
        warn("  Check the address, port, username and password exactly "
             "as the provider sent them.")
        return None


def try_both_schemes(host_port, user, password):
    """WHICH SCHEME DOES THIS PROXY WANT?

    31 July 2026. The provider gave host dc-mum-005.staticip.in on port
    443. Port 443 is ambiguous on purpose -- providers use it because
    firewalls never block it. It may be a plain HTTP CONNECT proxy that
    merely LISTENS on 443, or a proxy that expects TLS to itself.

    Guessing costs a confusing failure at the worst moment, and today
    already had enough of those. So try both and report which one
    actually carries traffic.
    """
    results = {}
    for scheme in ("http", "https"):
        url = f"{scheme}://{user}:{password}@{host_port}"
        decision(f"    trying {scheme}://...")
        try:
            handler = urllib.request.ProxyHandler({"http": url,
                                                   "https": url})
            opener = urllib.request.build_opener(handler)
            with opener.open(WHOAMI, timeout=20) as response:
                seen = response.read().decode().strip()
            decision(f"      WORKS -- arrives as {seen}")
            results[scheme] = seen
        except Exception as exc:                           # noqa: BLE001
            decision(f"      no: {str(exc)[:90]}")
    return results


def main():
    decision("=" * 68)
    decision("  ORDER ROUTE CHECK -- read only, nothing is placed")
    decision("=" * 68)

    _line()
    decision("  ADDRESSES")
    mine = home_ip()
    decision(f"    this machine (home line)  {mine or '(unknown)'}")

    if not ORDER_PROXY:
        decision("    static IP proxy           NOT CONFIGURED")
        _line()
        warn("  config.ORDER_PROXY is None.")
        warn("  Orders will leave from this machine's own address. That")
        warn("  address must be whitelisted at Dhan, and a home")
        warn("  connection is not static -- expect DH-905.")
        warn("")
        warn("  Set it in config.py once your provider sends the details:")
        warn('      ORDER_PROXY = "http://USER:PASS@1.2.3.4:8080"')
        return

    through = proxy_ip(ORDER_PROXY)
    decision(f"    static IP proxy           {through or '(no answer)'}")
    decision(f"    proxy host                {safe_display(ORDER_PROXY)}")

    _line()
    if not through:
        warn("  VERDICT: the proxy is not working. Do not start a live")
        warn("  session against it -- every order would be refused.")
        return

    if mine and through == mine:
        warn("  VERDICT: the proxy returned THIS MACHINE'S OWN address.")
        warn("  It is not actually routing anything. Orders would leave")
        warn("  from the home line and be refused.")
        return

    decision(f"  VERDICT: orders will arrive at Dhan from {through}")
    decision("")
    decision(f"  WHITELIST EXACTLY THIS AT DHAN:   {through}")
    decision("")
    decision("  Everything else -- the tick feed, circuit-monitor quotes,")
    decision("  NSE, the pre-open book, RSS, Telegram -- still leaves from")
    decision(f"  {mine or 'this machine'}, which is what those sites need.")

    # ---- does the proxied client actually reach Dhan? ----------------
    # A READ, not an order. Proves auth and the network path in one go.
    # If this fails, the proxy cannot reach api.dhan.co at all and the
    # problem is the provider, not the whitelist.
    _line()
    decision("  DOES THE PROXIED CLIENT REACH DHAN?  (a read, not an order)")
    try:
        from dhanhq import DhanContext, dhanhq as DhanRestClient
        client = DhanRestClient(
            DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN))
        route_orders_through(client, ORDER_PROXY)
        funds = client.get_fund_limits()
        body = (funds or {}).get("data") or funds or {}
        balance = None
        if isinstance(body, dict):
            for key in ("availabelBalance", "availableBalance"):
                if key in body:
                    balance = body[key]
                    break
        if balance is None:
            warn(f"    Dhan replied, but with no balance: {str(body)[:160]}")
        else:
            decision(f"    Dhan answered through the proxy. Balance "
                     f"Rs {balance}")
            decision("    Auth and network path are both good.")
    except Exception as exc:                               # noqa: BLE001
        warn(f"    the proxied client could not reach Dhan: {exc}")
        warn("    The provider's proxy may not allow api.dhan.co.")
        return

    _line()
    decision("  NEXT, IN THIS ORDER:")
    decision(f"    1. whitelist {through} at Dhan (primary)")
    decision("    2. REGENERATE the access token -- a token issued before")
    decision("       the IP was added does not carry the permission")
    decision("    3. paste the new token into .env")
    decision("    4. py main.py, wait for the [FUNDS] LIVE line")
    decision("    5. one BUY from the dashboard")
    decision("")
    decision("  Nothing was placed. Nothing was spent.")


def detect(host_port, user, password):
    decision("=" * 68)
    decision("  WHICH PROXY SCHEME WORKS?  (read only, nothing placed)")
    decision("=" * 68)
    mine = home_ip()
    decision(f"    home line arrives as     {mine or '(unknown)'}")
    decision("")
    works = try_both_schemes(host_port, user, password)
    decision("")
    _line()
    if not works:
        warn("  NEITHER scheme worked. The host, port, username or")
        warn("  password is wrong, or the provider has not activated it.")
        return
    for scheme, seen in works.items():
        if mine and seen == mine:
            warn(f"  {scheme}:// connected but returned YOUR OWN address "
                 f"-- it is not routing.")
            continue
        decision(f"  USE THIS IN config.py:")
        decision("")
        decision(f'      ORDER_PROXY = "{scheme}://USER:PASS@{host_port}"')
        decision("")
        decision(f"  WHITELIST THIS AT DHAN:   {seen}")
        return


if __name__ == "__main__":
    if "--detect" in sys.argv:
        i = sys.argv.index("--detect")
        detect(sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3])
    else:
        main()
