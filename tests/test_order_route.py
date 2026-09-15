"""
==========================================================
Only the ORDER path leaves via the static IP
==========================================================

31 July 2026. SEBI requires API-placed orders to come from a
registered static IP. The obvious fix is to move the bot to a cloud
machine that has one. The operator had already tried that shape:

    "last time when deployed in railway - some rss not worked"

He was right, and the reason is in our own imports. This bot fetches
www.nseindia.com, nsearchives.nseindia.com, moneycontrol,
economictimes and business-standard. Those block datacenter
addresses. Dhan requires a registered one.

    NSE and the news sites want a RESIDENTIAL address.
    Dhan wants a REGISTERED STATIC one.

No single address does both. So the proxy goes on exactly one client.

WHAT THESE TESTS PROTECT
------------------------
That the split stays a split. The failure mode is not a crash -- it is
a Monday where the pre-open book comes back empty at 09:12 because
somebody applied the proxy globally, and it looks like NSE being
flaky. A test is the only thing that notices.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.order_route import (
    describe, route_orders_through, safe_display, _session_of,
)

PROXY = "http://user:s3cret@103.21.5.9:8080"


def _client():
    """A real dhanhq client. Constructing one is offline -- no request
    leaves until a method is called, and none is called here."""
    from dhanhq import DhanContext, dhanhq as DhanRestClient
    return DhanRestClient(DhanContext("1000000001", "token"))


# ---------------------------------------------------------------
# 1. THE PROXY REACHES THE CLIENT THAT PLACES ORDERS
# ---------------------------------------------------------------
def test_the_proxy_is_applied_to_the_real_dhan_client():
    """Against the actual library, not a stand-in. dhanhq nests its
    session (client -> dhan_http -> session) and that path has moved
    between versions -- a mock would keep passing after a version bump
    that silently stopped applying the proxy."""
    client = _client()
    assert route_orders_through(client, PROXY) is True
    assert _session_of(client).proxies == {"http": PROXY, "https": PROXY}


# ---------------------------------------------------------------
# 2. NOTHING ELSE IS TOUCHED  -- the Railway lesson
# ---------------------------------------------------------------
def test_a_second_client_is_left_on_the_home_connection():
    """THE WHOLE POINT.

    main.py builds two clients: one for orders (proxied) and one for
    funds, quotes and the circuit monitor (not). If applying the proxy
    leaked to the second, NSE and the news feeds would start arriving
    from a datacenter and get blocked -- the Railway failure, rebuilt.
    """
    orders = _client()
    everything_else = _client()
    route_orders_through(orders, PROXY)
    assert _session_of(everything_else).proxies == {}


def test_it_does_not_set_environment_variables():
    """HTTPS_PROXY would work and would also route NSE, the pre-open
    book and every RSS feed through the datacenter. That breaks at
    09:12 on a Monday and looks like NSE being down."""
    import os
    before = dict(os.environ)
    route_orders_through(_client(), PROXY)
    assert dict(os.environ) == before


# ---------------------------------------------------------------
# 3. NO PROXY = NOTHING CHANGES
# ---------------------------------------------------------------
def test_none_leaves_the_client_exactly_as_it_was():
    """A paper day, and a live day before the IP arrives, must behave
    precisely as they did before this module existed."""
    client = _client()
    assert route_orders_through(client, None) is False
    assert _session_of(client).proxies == {}


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_blank_values_are_treated_as_no_proxy(empty):
    assert route_orders_through(_client(), empty.strip() if empty else empty) \
        is False


# ---------------------------------------------------------------
# 4. A HALF-APPLIED PROXY MUST NEVER BE SILENT
# ---------------------------------------------------------------
def test_it_raises_rather_than_place_orders_down_the_wrong_path():
    """If the session cannot be found, the proxy is not applied -- and
    orders would leave from the home address and come back DH-905. The
    operator would then be debugging the broker instead of the wiring,
    which is exactly how 31 July was spent. Fail at startup, loudly."""

    class NoSession:
        pass

    with pytest.raises(RuntimeError) as raised:
        route_orders_through(NoSession(), PROXY)
    assert "Refusing to start" in str(raised.value)


# ---------------------------------------------------------------
# 5. CREDENTIALS MUST NOT REACH THE LOGS
# ---------------------------------------------------------------
def test_the_password_never_appears_in_any_message():
    """The proxy URL carries a username and password, and these lines
    go into a log file that gets pasted into chat windows."""
    shown = safe_display(PROXY)
    assert "s3cret" not in shown
    assert "user" not in shown
    assert shown == "103.21.5.9:8080"
    assert "s3cret" not in describe(PROXY)


def test_safe_display_handles_a_proxy_with_no_credentials():
    assert safe_display("http://103.21.5.9:8080") == "103.21.5.9:8080"


def test_describe_says_plainly_when_there_is_no_proxy():
    assert "this machine" in describe(None)


# ---------------------------------------------------------------
# 6. MAIN.PY MUST ACTUALLY USE TWO CLIENTS
# ---------------------------------------------------------------
def test_main_gives_the_engine_the_proxied_client():
    """The module existing is worth nothing if main.py hands the Engine
    the un-proxied client. Read as text: importing main.py opens
    sockets."""
    with open("main.py", encoding="utf-8") as handle:
        source = handle.read()
    stripped = "\n".join(line.split("#")[0] for line in source.splitlines())
    assert "dhan_client=dhan_order_client" in stripped, (
        "the Engine is being given the un-proxied client, so orders "
        "would leave from the home address")
    assert "order_route.route_orders_through(dhan_order_client" in stripped


def test_main_keeps_a_separate_unproxied_client_for_reads():
    """The circuit monitor and the funds call must stay on the home
    line, or NSE-adjacent traffic starts looking like a datacenter."""
    with open("main.py", encoding="utf-8") as handle:
        stripped = "\n".join(l.split("#")[0] for l in handle.read().splitlines())
    assert "spaced(dhan_rest_client.quote_data)" in stripped
    assert "CircuitMonitor(quote_data" in stripped
    assert "broker_funds.starting_capital(dhan_rest_client)" in stripped
    assert "route_orders_through(dhan_rest_client" not in stripped
