"""
==========================================================
The stop that is still there when the process is not
==========================================================

    "yeah pick that one. - pick the broker-side stop"
                                    -- operator, 2 August 2026

Before this, every stop lived in core/trailing_stop.py's
`_state = {}` -- RAM, inside the running process. Kill the process and
an open MTF position at up to 4X, held overnight, had no stop anywhere.
Dhan did not know one was intended. The watchdog in main.py restarts
the FEED; it cannot help with a machine that is off.

WHY A FOREVER ORDER AND NOT A SUPER ORDER
-----------------------------------------
Both accept productType MTF. Super Order was rejected twice over:

1. It only exists at ENTRY, and half this book is opened by the
   operator clicking BUY on the dashboard. A net with a hole in it for
   his own trades is not a net.
2. targetPrice is REQUIRED, and his method is "ride untill the
   momentum stays". A fixed target caps the winners that method exists
   to catch.

THE FOUR THINGS THIS FILE IS ACTUALLY GUARDING
----------------------------------------------
1. A resting order left behind after an exit SELLS STOCK THAT IS NOT
   HELD. On MTF that opens a short. Cancel-on-exit, and reconcile at
   startup, are not tidiness.

2. TWO STOPS MUST NOT RACE. The resting one sits at the HARD stop from
   entry; the live one ratchets above it. If they were equal, both
   could fill and the position would be sold twice.

3. A PROTECTIVE ORDER MUST NEVER LOOSEN. sync() only ever moves a stop
   toward safety. A stop that quietly widened would read as protection
   while being worse than none.

4. AN ORDER THAT IS NOT OURS IS NOT OURS. reconcile() cancels only
   orders carrying our own tag. The operator may have placed a GTT by
   hand in the Dhan app, and this bot does not reach into his account
   and remove it.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from trading.broker_stop import BrokerStop, hard_stop_price


class FakeDhan:
    """Records what was asked of Dhan, and can be told to fail."""

    def __init__(self, fail=()):
        self.placed, self.modified, self.cancelled = [], [], []
        self.forever_rows = []
        self.fail = set(fail)
        self._next = 1000

    def place_forever(self, **kw):
        if "place" in self.fail:
            raise RuntimeError("network gone")
        self.placed.append(kw)
        self._next += 1
        return {"orderId": str(self._next), "orderStatus": "PENDING"}

    def modify_forever(self, **kw):
        if "modify" in self.fail:
            raise RuntimeError("rejected")
        self.modified.append(kw)
        return {"orderId": kw.get("order_id"), "orderStatus": "PENDING"}

    def cancel_forever(self, order_id):
        if "cancel" in self.fail:
            raise RuntimeError("could not cancel")
        self.cancelled.append(str(order_id))
        return {"orderId": str(order_id), "orderStatus": "CANCELLED"}

    def get_forever(self):
        if "list" in self.fail:
            raise RuntimeError("no reply")
        return {"data": list(self.forever_rows)}


def stop(dhan=None, enabled=True, resync=0.01):
    return BrokerStop(dhan or FakeDhan(), "NSE_EQ", "MTF",
                      enabled=enabled, resync_pct=resync)


# ---------------------------------------------------------------
# 1. OFF BY DEFAULT, AND OFF MEANS OFF
# ---------------------------------------------------------------
def test_nothing_is_sent_when_it_is_switched_off():
    d = FakeDhan()
    s = stop(d, enabled=False)
    assert s.place("TCS", "11536", 10, 3000.0) is None
    assert s.sync("TCS", 3100.0) is False
    assert s.cancel("TCS") is False
    assert d.placed == [] and d.modified == [] and d.cancelled == []


def test_the_config_switch_is_on():
    """---- HE TURNED IT ON. 12 August 2026. ----

    This test used to assert the switch was False, with the reasoning
    "it places REAL resting orders in a real account -- one switch away
    from that is not a switch this code flips for him". That was the
    right default to SHIP with and the wrong one to still be running a
    fortnight later.

    BROKER_STOP_ENABLED was False and FORCE_SQUARE_OFF_AT_CLOSE is also
    False. Together they meant an open MTF position had no stop
    anywhere between 15:30 and 09:15 -- not at Dhan, and not in this
    process if the machine was off. Six trades went straight through
    the 2.5% hard stop overnight (data/trade_memory.db records them as
    MISSED_STOP_RECONCILED: n=6, -Rs 20,133, an average of -Rs 3,355
    against a stop that should have cost -Rs 3,000 at most).

    Asked which way to close the gap, he chose the resting stop over
    forced square-off: the overnight hold is the strategy, so protect
    it rather than abolish it.

    This test now guards the ON state for the same reason it guarded
    OFF -- so the value is a decision somebody made, and never drifts
    quietly in either direction.
    """
    from config import BROKER_STOP_ENABLED
    assert BROKER_STOP_ENABLED is True


def test_forced_square_off_is_still_off_so_the_stop_is_load_bearing():
    """The two switches are one decision. If square-off is ever turned
    back on, the resting stop stops being the only overnight
    protection -- and if BOTH are off, the hole is back. This fails the
    build in the one combination that leaves a position unprotected."""
    from config import BROKER_STOP_ENABLED, FORCE_SQUARE_OFF_AT_CLOSE
    assert BROKER_STOP_ENABLED or FORCE_SQUARE_OFF_AT_CLOSE, (
        "Both are False. An MTF position carried overnight now has no "
        "stop at Dhan and no process guaranteed to be running. This is "
        "the exact configuration that cost -Rs 48,692 across six trades."
    )


# ---------------------------------------------------------------
# 2. PLACING
# ---------------------------------------------------------------
def test_a_long_rests_a_sell_stop_on_mtf():
    d = FakeDhan()
    s = stop(d)
    order_id = s.place("TCS", "11536", 10, 2925.0, direction="LONG")
    assert order_id == "1001"
    sent = d.placed[0]
    assert sent["transaction_type"] == "SELL"
    assert sent["product_type"] == "MTF", \
        "a protective order on the wrong product protects nothing"
    assert sent["trigger_Price"] == 2925.0
    assert sent["quantity"] == 10
    assert sent["order_flag"] == "SINGLE"


def test_it_triggers_into_a_market_order():
    """A LIMIT can go unfilled through a gap-down, and an unfilled
    protective order is the whole thing this exists to prevent. The
    price is not the point; being out is."""
    d = FakeDhan()
    stop(d).place("TCS", "11536", 10, 2925.0)
    assert d.placed[0]["order_type"] == "MARKET"
    assert d.placed[0]["price"] == 0


def test_a_short_rests_a_buy_stop():
    d = FakeDhan()
    stop(d).place("TCS", "11536", 10, 3075.0, direction="SHORT")
    assert d.placed[0]["transaction_type"] == "BUY"


def test_a_second_place_does_not_double_the_quantity():
    """Two resting orders on one position would sell twice the stock
    held the moment they trigger."""
    d = FakeDhan()
    s = stop(d)
    first = s.place("TCS", "11536", 10, 2925.0)
    again = s.place("TCS", "11536", 10, 2925.0)
    assert first == again
    assert len(d.placed) == 1


@pytest.mark.parametrize("qty,price", [(0, 100.0), (-5, 100.0),
                                       (10, 0.0), (10, -1.0),
                                       ("x", 100.0), (10, None)])
def test_nonsense_is_refused_rather_than_sent(qty, price):
    d = FakeDhan()
    assert stop(d).place("TCS", "11536", qty, price) is None
    assert d.placed == []


def test_a_failed_placement_is_loud_and_not_recorded():
    """If it is not at Dhan, this module must not believe it is --
    a false record would stop reconcile() from ever fixing it."""
    d = FakeDhan(fail={"place"})
    s = stop(d)
    assert s.place("TCS", "11536", 10, 2925.0) is None
    assert s.resting() == {}


def test_an_unreadable_reply_counts_as_not_placed():
    d = FakeDhan()
    d.place_forever = lambda **kw: {"status": "ok"}      # no order id
    s = stop(d)
    assert s.place("TCS", "11536", 10, 2925.0) is None
    assert s.resting() == {}


# ---------------------------------------------------------------
# 3. THE TWO STOPS MUST NOT RACE
# ---------------------------------------------------------------
def test_the_resting_stop_sits_below_the_live_one():
    """The hard stop from entry, never the ratcheted live level. Equal
    prices means both can fill and the position is sold twice."""
    entry = 3000.0
    hard = hard_stop_price(entry, "LONG", 0.025)
    assert hard == 2925.0
    assert hard < entry


def test_the_hard_stop_is_above_entry_for_a_short():
    assert hard_stop_price(3000.0, "SHORT", 0.025) == 3075.0


@pytest.mark.parametrize("entry,pct", [(0, 0.025), (-1, 0.025),
                                       (3000, 0), (None, 0.025),
                                       (3000, None)])
def test_a_nonsense_hard_stop_is_none_not_a_guess(entry, pct):
    assert hard_stop_price(entry, "LONG", pct) is None


# ---------------------------------------------------------------
# 4. IT MAY TIGHTEN, NEVER LOOSEN
# ---------------------------------------------------------------
def test_the_resting_stop_follows_the_trail_up():
    d = FakeDhan()
    s = stop(d, resync=0.01)
    s.place("TCS", "11536", 10, 2925.0)
    assert s.sync("TCS", 2990.0) is True          # +2.2%, worth a call
    assert d.modified[0]["trigger_price"] == 2990.0
    assert s.resting()["TCS"]["trigger"] == 2990.0


def test_a_small_move_is_not_worth_an_order_path_call():
    """Following every tick would be thousands of API calls a day for
    a protection that only matters once the process is already dead."""
    d = FakeDhan()
    s = stop(d, resync=0.01)
    s.place("TCS", "11536", 10, 2925.0)
    assert s.sync("TCS", 2930.0) is False         # +0.17%
    assert d.modified == []


def test_it_never_moves_the_stop_down():
    """THE ONE THAT MATTERS MOST HERE. A protective order that loosens
    reads as protection while being worse than none."""
    d = FakeDhan()
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    assert s.sync("TCS", 2800.0) is False
    assert d.modified == []
    assert s.resting()["TCS"]["trigger"] == 2925.0


def test_a_short_tightens_downward():
    d = FakeDhan()
    s = stop(d)
    s.place("TCS", "11536", 10, 3075.0, direction="SHORT")
    assert s.sync("TCS", 3000.0) is True
    assert s.sync("TCS", 3200.0) is False, "that would be looser"


def test_a_failed_modify_leaves_the_old_trigger_standing():
    d = FakeDhan(fail={"modify"})
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    assert s.sync("TCS", 2990.0) is False
    assert s.resting()["TCS"]["trigger"] == 2925.0, \
        "believing a move that did not happen is worse than the move"


def test_syncing_a_symbol_with_nothing_resting_does_nothing():
    d = FakeDhan()
    assert stop(d).sync("NOTHING", 100.0) is False


# ---------------------------------------------------------------
# 5. THE DANGEROUS ONE -- CANCEL ON EXIT
# ---------------------------------------------------------------
def test_the_exit_pulls_the_resting_order():
    d = FakeDhan()
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    assert s.cancel("TCS", why="TRAILING_STOP") is True
    assert d.cancelled == ["1001"]
    assert s.resting() == {}


def test_a_failed_cancel_still_forgets_it_locally():
    """A stale local record would make reconcile() skip the orphan
    forever. Better to have reconcile() find it at Dhan and deal with
    it there."""
    d = FakeDhan(fail={"cancel"})
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    assert s.cancel("TCS") is False
    assert s.resting() == {}


def test_cancel_still_works_after_the_switch_is_turned_off():
    """THE ONE THAT WOULD HAVE STRANDED ORDERS. cancel() used to be
    gated on `enabled`, so the instant the switch went off, every order
    resting at that moment had nothing left to clean it up -- and a
    stop resting against a closed position SELLS STOCK NOT HELD.

    Getting OUT is never blocked by a switch. Same rule as the SELL
    endpoint on the dashboard."""
    d = FakeDhan()
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    s.enabled = False
    assert s.cancel("TCS") is True
    assert d.cancelled == ["1001"]


# ---------------------------------------------------------------
# 5b. THE SWITCH, WITHOUT A RESTART
# ---------------------------------------------------------------
def test_switching_on_protects_what_is_already_open():
    """Turning it on with positions running and doing nothing about
    them is the worst of both worlds: he believes he is covered, and
    the trades opened before the click are not."""
    d = FakeDhan()
    s = stop(d, enabled=False)
    held = {"TCS": {"security_id": "11536", "qty": 10,
                    "entry_price": 3000.0, "direction": "LONG"}}
    out = s.enable(open_positions=held,
                   hard_stop_for=lambda _s, p: hard_stop_price(
                       p["entry_price"], p["direction"], 0.025))
    assert out["enabled"] is True
    assert s.enabled is True
    assert d.placed and d.placed[0]["trigger_Price"] == 2925.0


def test_switching_off_pulls_every_resting_order():
    """Leaving them would strand orders nothing will cancel at the
    exit."""
    d = FakeDhan()
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    s.place("INFY", "1594", 5, 1500.0)
    out = s.disable()
    assert s.enabled is False
    assert out["cancelled"] == 2
    assert sorted(d.cancelled) == ["1001", "1002"]
    assert s.resting() == {}


def test_switching_off_without_cancelling_says_so_loudly():
    """The deliberate case -- "stop managing these, leave the
    protection". Those orders become his to watch and the report names
    them."""
    d = FakeDhan()
    s = stop(d)
    s.place("TCS", "11536", 10, 2925.0)
    out = s.disable(cancel_resting=False)
    assert out["left"] == ["TCS"]
    assert d.cancelled == []


def test_switching_on_with_no_broker_is_refused():
    s = BrokerStop(None, "NSE_EQ", "MTF", enabled=False)
    out = s.enable()
    assert out["enabled"] is False and s.enabled is False


def test_the_dashboard_can_switch_it_without_a_restart():
    """BROKER_STOP_ENABLED is read once when the engine is built. The
    only way to switch it on used to be a restart -- exactly what you
    do not want to do at the moment you want more protection."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    assert '@app.post("/api/broker_stop/{state}")' in src
    block = src[src.find('@app.post("/api/broker_stop/{state}")'):]
    block = block[:block.find('@app.websocket("/ws")')]
    assert "_require_operator(request)" in block, "operator only"
    assert "stop.enable(" in block and "stop.disable(" in block
    assert "cancel_resting=True" in block, \
        "switching off must not strand resting orders"
    assert "hard_stop_for=" in block, \
        "switching on must protect what is already open"


def test_the_panel_shows_the_state_rather_than_assuming_it():
    """"I thought it was on" is how a safety net fails."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find("function renderBrokerStop"):]
    block = block[:block.find("function renderBrokerSync")]
    assert "STOP AT BROKER: OFF" in block and "STOP AT BROKER: ON" in block
    assert "bstop-warn" in block, "OFF must read as a warning, not neutral"
    assert "unprotected" in block


def test_switching_off_is_confirmed_and_switching_on_is_not():
    """Adding protection is never the dangerous direction. Removing it
    cancels live orders at the broker."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find('const bst = e.target.closest("[data-bstop]")'):]
    block = block[:block.find('const b = e.target.closest("[data-buy]")')]
    assert 'want === "off" && !confirm(' in block


def test_the_state_layer_reports_which_positions_are_uncovered():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "def build_broker_stop(self, open_positions):" in src
    block = src[src.find("def build_broker_stop"):]
    block = block[:block.find("def build_results_today")]
    assert "unprotected" in block
    assert "except Exception" in block, \
        "a panel must not be able to take the snapshot down"


def test_the_engine_cancels_before_it_forgets_the_position():
    src = open("core/engine.py", encoding="utf-8").read()
    block = src[src.find("self.broker_stop.cancel(symbol"):]
    assert block.find("del self.open_positions[symbol]") > 0
    head = src[:src.find("del self.open_positions[symbol]")]
    assert "self.broker_stop.cancel(symbol" in head, \
        "the resting order must be pulled before the local teardown"


# ---------------------------------------------------------------
# 6. RECONCILE -- THE RESTART CASE
# ---------------------------------------------------------------
def test_a_position_with_no_resting_stop_gets_one():
    d = FakeDhan()
    s = stop(d)
    held = {"TCS": {"security_id": "11536", "qty": 10,
                    "entry_price": 3000.0, "direction": "LONG"}}
    report = s.reconcile(held, hard_stop_for=lambda _s, p: hard_stop_price(
        p["entry_price"], p["direction"], 0.025))
    assert report["missing"] == ["TCS"]
    assert d.placed and d.placed[0]["trigger_Price"] == 2925.0


def test_an_orphan_of_ours_is_cancelled():
    """No position behind it. Left alone it would sell stock that is
    not held -- on MTF, a short."""
    d = FakeDhan()
    d.forever_rows = [{"orderId": "77", "tradingSymbol": "OLDSTOCK",
                       "correlationId": "OTSTOPOLDSTOCK",
                       "orderStatus": "PENDING", "transactionType": "SELL",
                       "triggerPrice": 100.0, "quantity": 5}]
    report = stop(d).reconcile({})
    assert report["orphans_cancelled"] == 1
    assert d.cancelled == ["77"]


def test_an_order_that_is_not_ours_is_reported_and_left_alone():
    """He may have placed a GTT by hand in the Dhan app. Cancelling it
    would be this bot removing a protection he set himself."""
    d = FakeDhan()
    d.forever_rows = [{"orderId": "88", "tradingSymbol": "HISOWN",
                       "correlationId": "", "orderStatus": "PENDING",
                       "transactionType": "SELL", "triggerPrice": 50.0,
                       "quantity": 1}]
    report = stop(d).reconcile({})
    assert report["orphans_left"] == ["HISOWN"]
    assert d.cancelled == []


def test_a_resting_order_on_a_held_position_is_adopted():
    """After a restart the local record is empty while Dhan's is not.
    Without adoption, cancel() at the next exit would do nothing."""
    d = FakeDhan()
    d.forever_rows = [{"orderId": "99", "tradingSymbol": "TCS",
                       "correlationId": "OTSTOPTCS",
                       "orderStatus": "PENDING", "transactionType": "SELL",
                       "triggerPrice": 2925.0, "quantity": 10}]
    s = stop(d)
    report = s.reconcile({"TCS": {"security_id": "11536", "qty": 10,
                                  "entry_price": 3000.0,
                                  "direction": "LONG"}})
    assert report["adopted"] == 1
    assert s.resting()["TCS"]["order_id"] == "99"
    assert s.cancel("TCS") is True and d.cancelled == ["99"]


def test_a_dead_order_is_not_treated_as_resting():
    d = FakeDhan()
    d.forever_rows = [{"orderId": "5", "tradingSymbol": "TCS",
                       "correlationId": "OTSTOPTCS",
                       "orderStatus": "TRADED", "transactionType": "SELL"}]
    report = stop(d).reconcile({})
    assert report["at_broker"] == 0
    assert d.cancelled == []


def test_a_failed_read_says_so_rather_than_assuming_all_is_well():
    d = FakeDhan(fail={"list"})
    report = stop(d).reconcile({})
    assert report["errors"]
    assert report["orphans_cancelled"] == 0


def test_the_startup_reconcile_is_wired_into_main():
    src = open("main.py", encoding="utf-8").read()
    assert "engine.broker_stop.reconcile(" in src
    assert "hard_stop_for=" in src
    block = src[src.find("engine.broker_stop.reconcile("):]
    block = block[:block.find("# Mutable holder")]
    assert "except Exception" in block, \
        "a failed reconcile must not stop the bot starting"


# ---------------------------------------------------------------
# 7. IT CAN NEVER BLOCK A TRADE
# ---------------------------------------------------------------
def test_the_entry_hook_cannot_undo_a_fill():
    """An entry that has already filled cannot be un-filled because a
    protective order failed. The failure is loud; the trade stands."""
    src = open("core/engine.py", encoding="utf-8").read()
    start = src.find("if self.broker_stop is not None:\n            try:\n"
                     "                from trading.broker_stop import "
                     "hard_stop_price")
    assert start > 0, "the entry hook is not where this test expects it"
    block = src[start:start + 1400]
    assert "except Exception" in block
    assert "HARD_STOP_FROM_ENTRY_PCT" in block


def test_it_rests_at_the_hard_stop_not_at_the_seeded_live_stop():
    """stop_seed is the level THIS PROCESS manages and ratchets. The
    resting order must sit below it."""
    src = open("core/engine.py", encoding="utf-8").read()
    start = src.find("resting = hard_stop_price(price, direction,")
    assert start > 0
    assert "stop_seed" not in src[start:start + 200]
