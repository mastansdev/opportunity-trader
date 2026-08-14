"""
==========================================================
How many, not just which
==========================================================

    "yes pls complete now."          -- operator, 2 August 2026

Every request through the dashboard used to be a bare symbol in a set.
So every BUY was exactly the Rs 1 lakh margin rule, and every SELL was
the WHOLE position. That second one contradicted his own method:

    "ride untill the momentum stays - exit once it gone ruthlessly"

Riding a move usually means trimming into strength, and the dashboard
could only ever sell all of it.

WHAT IS DELIBERATELY UNCHANGED
------------------------------
qty is optional on every endpoint, and absent means what it has always
meant: the standard size on an entry, the whole position on an exit.
Every existing caller -- the exit-all batch, the bot's own entries,
every test written before today -- goes down the identical path.

THE FOUR TRAPS
--------------
1. A BAD NUMBER MUST NOT FALL BACK TO THE DEFAULT. On a sell, quietly
   ignoring an unparseable qty would close the ENTIRE position when he
   meant to trim half. It is refused instead, and the refusal names the
   reason.

2. READ THE SIZE BEFORE CLEARING THE REQUEST. clear_buy() drops the
   remembered quantity with the request. Reading it afterwards would
   silently give every dashboard buy the default size again -- this
   whole change undone by the order of two lines.

3. MANUAL_TEST_QTY STILL WINS. That switch exists to make the first
   real orders one share regardless of what anything else believes. A
   typo in a quantity box must not defeat it.

4. THE RESTING STOP IS SIZED FOR THE WHOLE POSITION. After a trim it
   would sell more than is held -- on MTF the surplus is a short. It is
   re-rested for what is left.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from trading.trade_controller import TradeController


# ---------------------------------------------------------------
# 1. THE CONTROLLER REMEMBERS A SIZE
# ---------------------------------------------------------------
def test_no_size_means_what_it_always_meant():
    c = TradeController()
    c.request_exit("TCS")
    c.request_buy("INFY")
    assert c.is_exit_requested("TCS") and c.is_buy_requested("INFY")
    assert c.exit_qty("TCS") is None
    assert c.buy_qty("INFY") is None


def test_a_size_is_carried_beside_the_request():
    c = TradeController()
    c.request_exit("TCS", qty=35)
    c.request_buy("INFY", qty=10)
    c.request_short("WIPRO", qty=5)
    assert c.exit_qty("TCS") == 35
    assert c.buy_qty("INFY") == 10
    assert c.short_qty("WIPRO") == 5


@pytest.mark.parametrize("bad", [0, -5, "x", None, ""])
def test_a_size_that_is_not_a_positive_number_is_forgotten(bad):
    c = TradeController()
    c.request_exit("TCS", qty=bad)
    assert c.is_exit_requested("TCS"), "the request itself still stands"
    assert c.exit_qty("TCS") is None


def test_clearing_a_request_forgets_its_size():
    """A leftover size would apply to the NEXT request for the same
    symbol -- an exit that trims when he meant to close."""
    c = TradeController()
    c.request_exit("TCS", qty=35)
    c.clear_exit("TCS")
    assert c.exit_qty("TCS") is None
    c.request_exit("TCS")
    assert c.exit_qty("TCS") is None


def test_a_later_request_replaces_the_earlier_size():
    c = TradeController()
    c.request_buy("TCS", qty=10)
    c.request_buy("TCS")
    assert c.buy_qty("TCS") is None, "the second click asked for the default"


# ---------------------------------------------------------------
# 2. THE API
# ---------------------------------------------------------------
def _client():
    from tests.test_dashboard_server import _client as make
    return make(known_symbols=("TCS", "RELIANCE"))


def test_a_sell_can_name_a_size():
    client, controller = _client()
    res = client.post("/api/sell/tcs?qty=35")
    assert res.json() == {"success": True, "qty": 35}
    assert controller.exits == ["TCS"]
    assert controller.exit_qty_seen == [35]


def test_a_buy_can_name_a_size():
    client, controller = _client()
    res = client.post("/api/buy/tcs?qty=7")
    assert res.json() == {"success": True, "qty": 7}
    assert controller.buy_qty_seen == [7]


@pytest.mark.parametrize("raw", ["abc", "3.5", "-2", "0"])
def test_a_bad_size_is_refused_rather_than_ignored(raw):
    """THE ONE THAT WOULD COST MONEY. Falling back to the default on a
    SELL closes the whole position when he meant to trim."""
    client, controller = _client()
    res = client.post(f"/api/sell/tcs?qty={raw}")
    body = res.json()
    assert body["success"] is False
    assert raw.strip("-") in body["error"] or "positive" in body["error"]
    assert controller.exits == [], "nothing may be queued"


def test_an_empty_size_is_not_an_error():
    """The blank box is the normal case, not a mistake."""
    client, controller = _client()
    assert client.post("/api/sell/tcs?qty=").json()["success"] is True
    assert controller.exit_qty_seen == [None]


# ---------------------------------------------------------------
# 3. THE ENGINE HONOURS IT
# ---------------------------------------------------------------
def test_the_buy_size_is_read_before_the_request_is_cleared():
    """TRAP 2. clear_buy() drops the size with the request, so reading
    it afterwards silently restores the old behaviour -- this whole
    change undone by the order of two lines."""
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("if self.trade_controller.is_buy_requested(symbol):"):]
    block = block[:block.find("ENTRY_REASON_MANUAL_DASHBOARD")]
    assert block.find("buy_qty(symbol)") < block.find("clear_buy(symbol)")


def test_the_short_size_is_read_before_the_request_is_cleared():
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("if self.trade_controller.is_short_requested(symbol):"):]
    block = block[:block.find("ENTRY_REASON_MANUAL_SHORT_DASHBOARD")]
    assert block.find("short_qty(symbol)") < block.find("clear_short(symbol)")


def test_a_named_size_beats_the_sizing_rule():
    from core.engine import Engine
    got = Engine._manual_qty(object(), 70, asked=10)
    assert got == 10


def test_manual_test_qty_still_beats_a_named_size(monkeypatch):
    """TRAP 3. That switch makes the first real orders one share
    regardless of what anything else believes."""
    import core.engine as eng
    monkeypatch.setattr(eng, "MANUAL_TEST_QTY", 1)
    assert eng.Engine._manual_qty(object(), 70, asked=500) == 1


def test_no_named_size_leaves_the_sizing_rule_alone():
    from core.engine import Engine
    assert Engine._manual_qty(object(), 70, asked=None) == 70
    assert Engine._manual_qty(object(), 70) == 70


# ---------------------------------------------------------------
# 4. THE PARTIAL EXIT
# ---------------------------------------------------------------
def test_the_exit_path_trims_when_a_smaller_size_is_asked_for():
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("want = self.trade_controller.exit_qty(pending_symbol)"):]
    block = block[:block.find("self.trade_controller.clear_exit(pending_symbol)")]
    assert "if want and 0 < want < held:" in block
    assert "self._trim(" in block
    assert "EXIT_REASON_MANUAL_PARTIAL" in block


def test_asking_for_the_whole_position_is_a_full_exit_not_a_trim():
    """want >= held is not an error. It is "sell all of it", which is
    what he means by typing the full size."""
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("want = self.trade_controller.exit_qty(pending_symbol)"):]
    block = block[:block.find("self.trade_controller.clear_exit(pending_symbol)")]
    assert "self._exit(pending_symbol, exit_price," in block


def test_the_automatic_trim_and_the_manual_one_share_one_path():
    """Two code paths that both reduce a position and both write a
    closed_positions row is how the two start disagreeing about what is
    still held."""
    src = open("core/engine.py", encoding="utf-8").read()
    assert src.count("def _trim(self, symbol, position, trim_qty") == 1
    block = src[src.find("def _maybe_partial_exit"):]
    block = block[:block.find("def _trim(")]
    assert "self._trim(" in block, \
        "the ATR trim must go through the shared path too"


def test_the_two_trims_are_logged_under_different_reasons():
    """One is the bot's rule firing, the other is his judgement. The
    trade log has to be able to tell them apart when either is
    measured."""
    from core.engine import (EXIT_REASON_MANUAL_PARTIAL,
                             EXIT_REASON_PARTIAL_PROFIT)
    assert EXIT_REASON_MANUAL_PARTIAL != EXIT_REASON_PARTIAL_PROFIT


def test_a_trim_resizes_the_resting_stop_at_the_broker():
    """TRAP 4. The resting order is sized for the WHOLE position. After
    a trim it would sell more than is held, and on MTF the surplus is a
    short."""
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("def _trim(self, symbol, position, trim_qty"):]
    block = block[:block.find("def _check_fixed_bracket")]
    assert "self.broker_stop.cancel(symbol" in block
    assert "self.broker_stop.place(" in block
    assert "except Exception" in block, \
        "a bookkeeping failure must never break an exit"


def test_the_trim_leaves_the_stop_level_alone():
    """Re-seeding a stop on a trim would move risk on a position he did
    not re-enter."""
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("def _trim(self, symbol, position, trim_qty"):]
    block = block[:block.find("def _check_fixed_bracket")]
    assert "trailing_stop.start(" not in block
    assert "trailing_stop.clear(" not in block


# ---------------------------------------------------------------
# 5. THE SCREEN
# ---------------------------------------------------------------
def test_the_box_sits_beside_its_own_button():
    """     "on top is not ideal place to keep qty as per my thinking.
             how about nxt to BUY , [qty] button & while selling the
             open position next to SELL [qty]"

    It started in the top bar because a per-row <input> is destroyed
    and recreated by every render -- roughly every two seconds -- which
    wipes what is being typed. That is a problem to SOLVE, not a reason
    to put the control somewhere he does not want it. See
    QTY_BY_SYMBOL and restoreQtyBoxes()."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    assert 'id="qtyBox"' not in page, "the top-bar box is gone"
    # one beside every BUY, SHORT and EXIT
    assert page.count("qtyInput(") >= 8


def test_the_typed_value_lives_outside_the_dom():
    """Held in the DOM it would last one keystroke. Keyed by SYMBOL it
    also survives a re-sort -- the number follows the stock, not the
    row position."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "const QTY_BY_SYMBOL = {}" in page
    block = page[page.find("function qtyInput"):]
    block = block[:block.find("function restoreQtyBoxes")]
    assert 'data-qtyfor="${escapeHtml(symbol)}"' in block


def test_the_focus_is_captured_before_the_tables_are_torn_down():
    """     "while i try to keep some number 55 or 48 its not working,
             & got struck"

    MY BUG, and the operator hit it in the first minute. The first
    version read document.activeElement INSIDE the restore, which runs
    AFTER render() has replaced the table's innerHTML -- by which point
    the focused element is gone and activeElement is <body>. There was
    nothing left to restore focus TO.

    The capture has to happen at the TOP of render(). If these two ever
    swap order again, the box goes back to eating keystrokes."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    body = page[page.find("function render(snap) {"):]
    body = body[:body.find("\nsetInterval(")]
    assert body.find("rememberQtyFocus();") < body.find("restoreQtyBoxes();")


def test_it_is_a_text_input_not_a_number_input():
    """Chrome refuses setSelectionRange() on type=number -- it throws
    InvalidStateError -- so the caret could never be restored. That was
    the other half of "got struck"."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find("function qtyInput(symbol, hint)"):]
    block = block[:block.find("// ---- CAPTURE BEFORE")]
    assert 'type="text"' in block
    assert 'inputmode="numeric"' in block
    assert 'type="number"' not in block


def test_the_boxes_are_restored_after_every_render():
    """If this call is dropped, the boxes clear themselves every two
    seconds and the feature silently stops working."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "restoreQtyBoxes();" in page
    tail = page[page.rfind("restoreQtyBoxes();"):]
    assert tail.find("}") < tail.find("setInterval"), \
        "it must run at the END of render(), after the tables are rebuilt"


def test_the_placeholder_says_what_empty_means():
    """Rs 1L on an entry, "all N" on an exit. The default is never
    something he has to remember."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    assert 'qtyInput(r.symbol, "Rs 1L")' in page
    block = page[page.find("function exitCell"):]
    block = block[:block.find("function sell(")]
    assert 'held ? `all ${held}` : "all"' in block


def test_the_size_is_named_in_the_confirm_dialog():
    """A number left in the box from a previous order would otherwise
    size the next one silently."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find("function confirmOrder"):]
    block = block[:block.find("function clearQtyBox")]
    assert "${size}" in block
    assert "standard Rs 1 lakh size" in block


def test_the_box_is_cleared_after_every_order():
    """A size left behind would apply to the NEXT click on the same
    stock. Sliced to the NEXT function, not to the next "}" -- a
    template literal like `${symbol}` closes a brace long before the
    function does, and the first version of this test cut there and
    asserted nothing."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    for fn in ("function manualBuy", "function manualShort",
               "function sell("):
        start = page.find(fn)
        assert start > 0, f"{fn} is gone"
        block = page[start:page.find("function ", start + len(fn))]
        assert "clearQtyFor(symbol)" in block, f"{fn} leaves the size behind"


def test_a_partial_sell_is_confirmed_and_a_full_exit_is_not():
    """Selling 35 of 70 by accident on a row that has just re-sorted is
    the click worth a second look. A bare EXIT is the same button doing
    the same thing it always has."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find("function sell(symbol) {"):]
    block = block[:block.find("function mktCell")]
    assert "if (raw && !window.confirm(" in block, \
        "the confirm must be conditional on a typed size"
    assert "SELL ${raw} of ${symbol}" in block
    assert "stop unchanged" in block
