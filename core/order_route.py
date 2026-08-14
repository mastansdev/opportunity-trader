"""
==========================================================
The one connection that must leave from the static IP
==========================================================

    "last time when deployed in railway - some rss not worked"
                                    -- operator, 31 July 2026

That sentence is the design.

SEBI requires API-placed orders to originate from a registered static
IP. The tempting fix is to run the whole bot on a cloud machine that
has one. The operator had already tried that shape and watched his
news feeds die, and the reason is in the code: this bot reads
www.nseindia.com, nsearchives.nseindia.com, moneycontrol,
economictimes and business-standard. Those sites block datacenter
addresses. Dhan requires a registered one.

    NSE and the news sites want a RESIDENTIAL address.
    Dhan wants a REGISTERED STATIC one.

No single address satisfies both. So the bot keeps its home
connection, and exactly one client -- the one that places orders --
goes out through the static IP.

WHY THIS IS SURGICAL AND NOT AN ENVIRONMENT VARIABLE
----------------------------------------------------
Setting HTTPS_PROXY would work, and would also silently route NSE and
the RSS feeds through a datacenter. That failure would appear at 09:12
on a Monday as an empty pre-open book, and it would look like NSE
being flaky rather than like something we did. A global switch that
can quietly break a morning is worse than a narrow one that cannot.

dhanhq builds a `requests.Session()` in dhan_http.py. Setting
`.proxies` on that one session affects that client and nothing else in
the process.

WHAT STILL GOES OUT OVER THE HOME LINE
--------------------------------------
    the tick feed          websockets, ignores proxies entirely
    circuit-monitor quotes reads, no static IP needed
    NSE, the pre-open book must look residential
    RSS, Telegram, OCR     unaffected

Only order placement, modification and cancellation change path --
which is precisely the set SEBI's rule covers.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import decision, warn


def _session_of(dhan_client):
    """The requests.Session inside a dhanhq client, or None.

    dhanhq nests it: client -> dhan_http -> session. The path has
    changed across versions, so every shape seen is tried rather than
    assuming one. Returning None is a real answer and the caller
    refuses on it -- silently failing to apply the proxy would mean
    orders leaving from the wrong address, which is the exact bug this
    module exists to prevent.
    """
    for attr in ("dhan_http", "_dhan_http", "dhan_context"):
        holder = getattr(dhan_client, attr, None)
        if holder is None:
            continue
        session = getattr(holder, "session", None)
        if session is not None:
            return session
        getter = getattr(holder, "get_dhan_http", None)
        if callable(getter):
            try:
                inner = getter()
            except Exception:                              # noqa: BLE001
                continue
            session = getattr(inner, "session", None)
            if session is not None:
                return session
    return getattr(dhan_client, "session", None)


def route_orders_through(dhan_client, proxy_url):
    """Point THIS client's HTTP session at the static IP.

    Returns True if the proxy was applied, False if it was not wanted.
    RAISES if a proxy was configured and could not be applied -- a
    half-applied proxy means orders go out from the home address and
    come back DH-905, and the operator would be debugging the broker
    instead of the wiring. Fail at startup, loudly.
    """
    if not proxy_url:
        return False

    session = _session_of(dhan_client)
    if session is None:
        raise RuntimeError(
            "config.ORDER_PROXY is set but the Dhan client's HTTP "
            "session could not be found, so orders would leave from "
            "this machine's own address and be refused DH-905. "
            "Refusing to start rather than place orders down a path "
            "nobody chose."
        )

    # Both schemes point at the same proxy. An https:// target is
    # tunnelled through an http:// proxy by CONNECT -- that is normal,
    # and it is what keeps the access token encrypted end to end,
    # unreadable by the proxy operator.
    session.proxies = {"http": proxy_url, "https": proxy_url}

    # Never print the credentials. The URL carries a username and
    # password, and this line goes into a log file that gets pasted
    # into chat windows.
    decision(f"[ROUTE] Orders will leave via the static IP "
             f"({safe_display(proxy_url)}). Everything else -- ticks, "
             f"NSE, the pre-open book, RSS, Telegram -- stays on this "
             f"connection.")
    return True


def safe_display(proxy_url):
    """host:port only. Never the username or password."""
    if not proxy_url:
        return "none"
    tail = proxy_url.split("@")[-1]
    return tail.split("//")[-1]


def describe(proxy_url):
    """One line for preflight and the startup banner."""
    if not proxy_url:
        warn("[ROUTE] No ORDER_PROXY set. Orders will leave from this "
             "machine's own address -- which SEBI requires to be a "
             "registered static IP. Expect DH-905 unless this "
             "connection's address is whitelisted at Dhan.")
        return "orders leave from this machine"
    return f"orders leave via {safe_display(proxy_url)}"
