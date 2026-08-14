"""
==========================================================
A BUY button that cannot buy
==========================================================

    "done, i agree with you. i can trade manually from dashboard."
                                    -- operator, 2 August 2026

He said that about the 235 names the turnover bar keeps out, having
just agreed to leave the automatic bar strict on the strength of it.
It was not true, and I had let him believe it in the message before.

THE CHAIN, ALL THE WAY DOWN
---------------------------
    main.py            subscribes to master_loader.all_symbols()
                       -- SUBSCRIBE = YES rows ONLY

    /api/buy           checked only "is this symbol in the master file"
                       -- a blocked row passes that

    trade_controller   request_buy() puts the symbol in a set

    core/engine.py     is_buy_requested() is checked INSIDE the
                       per-symbol tick handler

A stock with no feed produces no ticks. So the request would have sat
in that set until the process restarted:

    the screen says     "BUY requested: SKFINDIA"   success
    what actually       nothing, ever, and no error anywhere

THIS EXACT FAILURE HAS HAPPENED BEFORE
--------------------------------------
The endpoint's own comment, from 28 July:

    "two BUY clicks vanished with no trace anywhere -- the operator
     searched the terminal for SUPREMEIND and found nothing, because
     nothing had been written. A silent failure and a silent success
     looked identical."

It came back through a door nobody had opened yet -- until he said he
would start using it.

THE FIX IS A REFUSAL, NOT A SUBSCRIPTION
----------------------------------------
Subscribing on demand would put an unmeasured stock on a live feed
mid-session, which is the opposite of what the bar is for. So the
click is refused at the API, in the same second, carrying the REAL
reason off the master -- "turnover Rs 2.58cr median of 10 sessions
below Rs 5cr". If he wants the stock tradeable the answer is the
SUBSCRIBE column, not this button.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

SERVER = "dashboard/server.py"
MAIN = "main.py"
ENGINE = "core/engine.py"


def src(path):
    return open(path, encoding="utf-8").read()


# ---------------------------------------------------------------
# 1. THE FACTS THAT MAKE IT BREAK
# ---------------------------------------------------------------
def test_the_feed_carries_subscribed_symbols_only():
    """If this ever changes to include_blocked=True the refusal below
    becomes wrong -- and this test is where that gets noticed."""
    body = src(MAIN)
    assert "master_loader.all_symbols()" in body
    assert "all_symbols(include_blocked=True)" not in body


def test_the_manual_buy_only_fires_on_a_tick():
    """The reason no feed means no order. is_buy_requested() is read
    inside the per-symbol handler, not on a timer."""
    body = src(ENGINE)
    assert "self.trade_controller.is_buy_requested(symbol)" in body


# ---------------------------------------------------------------
# 2. THE REFUSAL
# ---------------------------------------------------------------
def test_a_blocked_symbol_is_refused_at_the_api():
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    assert "master_loader.blocked_symbols()" in block
    assert "if symbol in blocked:" in block


def test_it_is_refused_before_anything_is_queued():
    """Queueing and THEN reporting failure would leave the request in
    the set, to fire days later if the stock is ever subscribed."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    # request_buy grew a qty argument on 2 August; match the call, not
    # its exact signature.
    assert block.find("if symbol in blocked:") < \
        block.find("trade_controller.request_buy(symbol")


def test_the_operator_is_told_why_not_just_no():
    """A bare "refused" sends him hunting through the terminal. The
    master's own SUBSCRIBE_REASON says "turnover Rs 2.58cr median of 10
    sessions below Rs 5cr", which answers the question in the same
    breath."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    assert "blocked[symbol]" in block
    assert '"success": False' in block


def test_the_refusal_is_written_to_the_log_as_well_as_the_screen():
    """28 July's lesson. A refusal that only exists in an HTTP response
    is invisible the moment the toast fades."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    assert re.search(r"warn\(f?\"\[DASHBOARD\] BUY REFUSED: \{symbol\} is not "
                     r"subscribed", block)
    assert "note_action(" in block


def test_an_unknown_symbol_is_still_refused():
    """The older check must survive alongside the new one."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    assert "master_loader.get_by_symbol(symbol) is None" in block


def test_a_subscribed_symbol_still_goes_through():
    """The refusal must be narrow. Everything on today's feed still
    reaches request_buy()."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    assert "trade_controller.request_buy(symbol" in block
    assert '"success": True' in block


def test_it_does_not_quietly_subscribe_the_stock_instead():
    """Putting an unmeasured name on a live feed mid-session is the
    opposite of what the liquidity bar is for -- and it would make the
    bar something the operator could bypass by accident."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/buy/{symbol}")'):]
    block = block[:block.find('@app.post("/api/sell/{symbol}")')]
    assert "subscribe(" not in block
    assert "add_symbol" not in block


# ---------------------------------------------------------------
# 3. SELL IS DELIBERATELY NOT TOUCHED
# ---------------------------------------------------------------
def test_sell_is_not_gated_by_the_subscribe_list():
    """An OPEN POSITION must always be closeable. If a stock is blocked
    while it is held -- turnover drops, a band tightens, GSM lands --
    refusing the exit would trap it. Getting out is never blocked."""
    body = src(SERVER)
    block = body[body.find('@app.post("/api/sell/{symbol}")'):]
    block = block[:block.find("\n    @app.post", 10)]
    assert "blocked_symbols" not in block
