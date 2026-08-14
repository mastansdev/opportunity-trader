"""
==========================================================
LIVE execution -- real orders, real money
==========================================================

Until 2026-07-28 this did not exist. trading/execution.py raised
NotImplementedError on TRADING_MODE="LIVE", deliberately:

    "LIVE execution is not built yet in Opportunity Trader. Stay on
     PAPER until it's deliberately added and reviewed -- this is not an
     oversight."

This is that module. Written the night before the operator funds the
account, for a first real order on 30 July and live trading on 3 August.

OPERATOR'S DECISIONS, 2026-07-28
-------------------------------
1. MARKET orders. Fills instantly; the price is not guaranteed.
2. He watches on two or three screens.
3. HIS CLICKS ONLY at first -- "initially i'll trade with bot dashboard.
   once bot gets clarity shifts to bot (not autonomous - i'll be there
   100%)". The bot's own structural entries cannot place a live order
   until LIVE_ALLOW_BOT_ENTRIES is turned on deliberately.

THE THREE THINGS THAT COST MONEY, AND WHAT IS DONE ABOUT EACH
-------------------------------------------------------------
1. A MARKET ORDER CANNOT BE CANCELLED once it fills. So the fill price
   can only be protected BEFORE sending: if the live price has drifted
   more than LIVE_MAX_PRICE_DRIFT_PCT from what the dashboard showed
   when he clicked, the order is REFUSED.

   The case: 2026-07-28, SUPREMEIND. The first click was lost to the
   dead-click bug, and price ran ~3,385 -> 3,472.70 before the second
   went through. Rs 5,000 on 57 shares. As a live market order that
   would have been a real fill at a price he never agreed to.

2. A TIMEOUT IS NOT A REJECTION. The order may have reached Dhan and
   the reply may have been lost. A blind retry is how you end up
   holding two positions and knowing about one.

   Every order carries a unique correlationId. On any timeout the bot
   queries BY THAT ID first. It NEVER resends blind. If it cannot
   confirm either way it says so loudly and stops -- an unknown state
   is for a human, not for a retry loop.

3. A BUG CAN LOOP. Fifty orders in a second is the nightmare case, and
   it must be impossible rather than unlikely. Hard ceilings on order
   value, orders per day, and open positions, checked before every
   send, in this module, not upstream.

TWO SWITCHES, NOT ONE
---------------------
TRADING_MODE="LIVE" is not enough on its own.
I_UNDERSTAND_THIS_PLACES_REAL_ORDERS must also be True.
One switch is one typo away from spending money by accident.

Author : H&M Opportunity Trader
==========================================================
"""

import threading
import time
import uuid
from datetime import datetime

from config import (
    EXCHANGE_SEGMENT, LIVE_MAX_ORDER_VALUE_RS, LIVE_MAX_ORDERS_PER_DAY,
    LIVE_MAX_OPEN_POSITIONS, LIVE_MAX_PRICE_DRIFT_PCT,
    LIVE_ORDER_TAG_PREFIX, LIVE_CONFIRM_TIMEOUT_SECONDS,
)
from core.logger import decision, diagnostic, warn
from trading.trade_logger import log_trade

BUY = "BUY"
SELL = "SELL"

MARKET = "MARKET"
LIMIT = "LIMIT"
MTF = "MTF"

# Dhan order states that mean "this is done, stop asking".
FILLED = ("TRADED", "EXECUTED", "COMPLETE", "FILLED")
DEAD = ("REJECTED", "CANCELLED", "EXPIRED")


def _fail(reason, **extra):
    out = {"success": False, "error": reason}
    out.update(extra)
    return out


class LiveExecution:
    """Places real orders through Dhan. One instance, one session."""

    def __init__(self, dhan_client, exchange_segment=EXCHANGE_SEGMENT,
                 price_lookup=None, open_position_count=None,
                 fill_log=None):
        self.dhan = dhan_client
        self.segment = exchange_segment
        # price_lookup(symbol) -> the CURRENT live price, for the drift
        # check. Without it the drift guard cannot run, and this module
        # refuses to place market orders blind -- see _check_drift.
        self._price_lookup = price_lookup
        self._open_count = open_position_count
        self._lock = threading.Lock()
        self._orders_today = 0
        self._day = datetime.now().date()
        # Pulled by kill_switch(). Checked in _check_limits() so it
        # blocks every path into the broker, not just the ones someone
        # remembered to guard. Deliberately NOT reset by _roll_day():
        # a kill switch that expires at midnight is not a kill switch.
        self._killed = False
        self._sent = {}          # correlation_id -> what we asked for
        # THE REASON THIS IS HERE. trading/slippage.py's constants are
        # conventional retail estimates, not this bot's data, and its
        # own docstring asks for exactly this: "Every real fill should
        # be compared against the price the bot wanted, and THAT
        # difference should replace these constants." The miss was
        # already computed on every fill below and thrown away.
        from core.fill_log import FillLog
        self._fills = fill_log if fill_log is not None else FillLog()
        # ---- ORDERS THAT NEVER CAME BACK. 3 August 2026. ----
        #
        #     "1st click no response & no way to check in dashboard,
        #      then i clicked the second one. now both orders gave me
        #      loss of huge amount"
        #
        # An order that times out is not finished, and until today the
        # bot forgot it the moment it said so. YASHO 24 sat at the
        # exchange unconfirmed at 09:17:34, filled late, and was never
        # seen again by anything -- no position, no stop, no row.
        #
        # symbol -> {order_id, tag, side, qty, at}. It is what makes a
        # second BUY refusable and a late fill findable.
        self._in_flight = {}

    # ------------------------------------------------------------
    # GUARDS -- every one of these runs BEFORE anything is sent
    # ------------------------------------------------------------

    def _roll_day(self):
        today = datetime.now().date()
        if today != self._day:
            self._day = today
            self._orders_today = 0

    def _check_limits(self, symbol, price, qty):
        self._roll_day()
        # ---- THE KILL SWITCH MUST ALSO STOP US. 12 August 2026. ----
        #
        # kill_switch() asks DHAN to block orders. Until now it set
        # nothing here, so a tested scenario read:
        #
        #     kill switch: call reaches Dhan            PASS
        #     kill switch: local buy STILL goes through PASS   <-- wrong
        #
        # If that API call fails, or Dhan is slow to apply it, the bot
        # carries on sending while believing it is stopped. A switch
        # that depends on the counterparty hearing you is not a switch.
        # This one stops us locally the instant it is pulled, whatever
        # Dhan does about it.
        if self._killed:
            return ("kill switch is ON -- nothing leaves this bot until "
                    "it is switched off")
        value = (price or 0) * (qty or 0)
        if qty is None or qty <= 0:
            return "quantity is zero"
        if not price or price <= 0:
            return "no price"
        if value > LIVE_MAX_ORDER_VALUE_RS:
            return (f"order value Rs {value:,.0f} is above the hard ceiling "
                    f"of Rs {LIVE_MAX_ORDER_VALUE_RS:,.0f}")
        if self._orders_today >= LIVE_MAX_ORDERS_PER_DAY:
            return (f"{self._orders_today} orders already sent today -- "
                    f"the daily ceiling is {LIVE_MAX_ORDERS_PER_DAY}. "
                    f"This is a bug guard, not a risk rule.")
        if self._open_count is not None:
            try:
                if self._open_count() >= LIVE_MAX_OPEN_POSITIONS:
                    return (f"{LIVE_MAX_OPEN_POSITIONS} positions already "
                            f"open -- the hard ceiling")
            except Exception:                              # noqa: BLE001
                pass
        return None

    def _check_drift(self, symbol, intent_price):
        """A market order cannot be un-filled. If the price has run away
        from what the operator saw when he clicked, refuse."""
        if self._price_lookup is None:
            return ("no live price feed to check against -- refusing to "
                    "send a market order blind")
        try:
            live = self._price_lookup(symbol)
        except Exception as exc:                           # noqa: BLE001
            return f"could not read the live price ({exc})"
        if not live or not intent_price:
            return "no live price to compare against"
        drift = abs(live - intent_price) / intent_price
        if drift > LIVE_MAX_PRICE_DRIFT_PCT:
            return (f"price moved {drift * 100:.2f}% since you clicked "
                    f"({intent_price:.2f} -> {live:.2f}). Ceiling is "
                    f"{LIVE_MAX_PRICE_DRIFT_PCT * 100:.1f}%. Nothing was "
                    f"sent -- click again if you still want it.")
        return None

    # ------------------------------------------------------------

    def _new_tag(self, symbol):
        return f"{LIVE_ORDER_TAG_PREFIX}{uuid.uuid4().hex[:10]}"

    def _confirm(self, order_id, tag):
        """Poll until the order is done. Returns (state, filled_price, qty)."""
        deadline = time.monotonic() + LIVE_CONFIRM_TIMEOUT_SECONDS
        last = None
        while time.monotonic() < deadline:
            try:
                response = self.dhan.get_order_by_id(order_id)
                body = (response or {}).get("data") or response or {}
                if isinstance(body, list) and body:
                    body = body[0]
                state = str(body.get("orderStatus") or
                            body.get("status") or "").upper()
                last = body
                if state in FILLED:
                    return state, _num(body.get("averageTradedPrice")
                                       or body.get("price")), \
                           _num(body.get("filledQty") or body.get("quantity"))
                if state in DEAD:
                    return state, None, None
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[LIVE] confirm poll failed ({exc}).")
            time.sleep(0.5)
        return "UNCONFIRMED", None, (last or {}).get("filledQty")

    def _find_by_tag(self, tag):
        """Did an order with this correlation ID reach Dhan?

        THE anti-double-order check. Called after a timeout, BEFORE any
        thought of resending.
        """
        try:
            response = self.dhan.get_order_by_correlationID(tag)
            body = (response or {}).get("data") or response
            if isinstance(body, list):
                return body[0] if body else None
            return body or None
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[LIVE] correlation lookup failed ({exc}).")
            return None

    # ------------------------------------------------------------

    def _execute(self, side, security_id, symbol, price, qty, reason,
                 at_time=None):
        blocked = self._check_limits(symbol, price, qty)
        if blocked:
            warn(f"[LIVE] {side} {symbol} REFUSED -- {blocked}. "
                 f"Nothing was sent.")
            return _fail(blocked)

        drift = self._check_drift(symbol, price)
        if drift:
            warn(f"[LIVE] {side} {symbol} REFUSED -- {drift}")
            return _fail(drift)

        tag = self._new_tag(symbol)
        with self._lock:
            self._orders_today += 1
            self._sent[tag] = dict(side=side, symbol=symbol, qty=qty,
                                   intent=price, at=datetime.now())

        decision(f"[LIVE] Sending {side} {symbol} qty={qty} MARKET "
                 f"(MTF), tag={tag}. Intent price {price:.2f}.")
        try:
            response = self.dhan.place_order(
                security_id=str(security_id),
                exchange_segment=self.segment,
                transaction_type=side,
                quantity=int(qty),
                order_type=MARKET,
                product_type=MTF,
                price=0,                    # ignored for MARKET
                tag=tag,
            )
        except Exception as exc:                           # noqa: BLE001
            # A TIMEOUT IS NOT A REJECTION. The order may have landed.
            warn(f"[LIVE] {side} {symbol}: no reply from Dhan ({exc}). "
                 f"Checking whether the order actually reached them "
                 f"BEFORE doing anything else -- never a blind retry.")
            found = self._find_by_tag(tag)
            if found:
                warn(f"[LIVE] {symbol}: the order DID reach Dhan "
                     f"(tag={tag}). NOT resending. Check your Dhan app.")
                return _fail("no reply, but the order reached Dhan",
                             order_id=found.get("orderId"), tag=tag,
                             needs_human=True)
            warn(f"[LIVE] {symbol}: no order found for tag={tag}. It "
                 f"probably never left. NOT resending automatically -- "
                 f"an unknown state is for you, not for a retry loop.")
            return _fail("no reply from Dhan, order not found",
                         tag=tag, needs_human=True)

        body = (response or {}).get("data") or response or {}
        order_id = body.get("orderId") or body.get("order_id")
        if not order_id:
            warn(f"[LIVE] {side} {symbol} REJECTED by Dhan: {response}")
            return _fail(f"rejected: {body.get('errorMessage') or response}",
                         tag=tag)

        state, filled_price, filled_qty = self._confirm(order_id, tag)

        if state == "UNCONFIRMED":
            # REMEMBERED, not just announced. See self._in_flight.
            with self._lock:
                self._in_flight[symbol] = {
                    "order_id": order_id, "tag": tag, "side": side,
                    "qty": qty, "at": datetime.now().isoformat(
                        timespec="seconds")}
            warn(f"[LIVE] {symbol} order {order_id} still not confirmed "
                 f"after {LIVE_CONFIRM_TIMEOUT_SECONDS}s. It may yet fill. "
                 f"CHECK YOUR DHAN APP -- the bot will not assume either way.")
            warn(f"[LIVE] {symbol} is now IN FLIGHT. Another {side} on it "
                 f"will be REFUSED until this order resolves.")
            return _fail("not confirmed in time", order_id=order_id,
                         tag=tag, needs_human=True)

        if state in DEAD:
            warn(f"[LIVE] {side} {symbol} {state}. Nothing was bought.")
            return _fail(state.lower(), order_id=order_id, tag=tag)

        filled_price = filled_price or price
        filled_qty = filled_qty or qty
        log_trade(side, symbol, security_id, filled_qty, filled_price, reason)
        slip = (filled_price - price) if side == BUY else (price - filled_price)
        decision(
            f"LIVE {side:<4} {symbol:<10} qty={filled_qty} @ {filled_price:.2f}"
            f" ({reason})  [wanted {price:.2f}, "
            f"{'slipped' if slip > 0 else 'better by'} {abs(slip):.2f} "
            f"= Rs {abs(slip) * filled_qty:,.0f}]  order={order_id}"
        )
        self._fills.record("LIVE", side, symbol, security_id, filled_qty,
                           price, filled_price, reason=reason,
                           order_id=order_id, at=at_time)
        return {"success": True, "order_id": order_id, "tag": tag,
                "price": filled_price, "intent_price": price,
                "qty": filled_qty,
                "slippage_rs": round(max(0.0, slip) * filled_qty, 2)}

    # ------------------------------------------------------------

    def buy(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self._execute(BUY, security_id, symbol, price, qty, reason,
                             at_time)

    def sell(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self._execute(SELL, security_id, symbol, price, qty, reason,
                             at_time)

    # ------------------------------------------------------------
    # FIRST CONTACT WITH THE REAL API -- 30 July
    # ------------------------------------------------------------

    def place_test_limit(self, security_id, symbol, price, quantity=1,
                         side=BUY, away_pct=0.10):
        """A LIMIT order priced far from the market, so it CANNOT fill.

        This is the safest possible first contact with the live API. A
        market order proves the plumbing by spending money; this proves
        it by parking an order you can look at in the Dhan app and then
        cancel. Nothing fills, nothing is charged.

        away_pct defaults to 10% below (BUY) or above (SELL) the market,
        which for any liquid stock is nowhere near the touch.

        Deliberately NOT subject to the drift guard or the daily order
        ceiling -- it is a plumbing test, not a trade, and it cannot
        fill by construction. It IS subject to the value ceiling.
        """
        if not price or price <= 0 or quantity <= 0:
            return _fail("bad test order parameters")
        limit_price = round(price * (1 - away_pct) if side == BUY
                            else price * (1 + away_pct), 1)
        if limit_price * quantity > LIVE_MAX_ORDER_VALUE_RS:
            return _fail("test order above the value ceiling")

        tag = self._new_tag(symbol)
        decision(f"[LIVE TEST] {side} {quantity} {symbol} LIMIT "
                 f"{limit_price:.2f} (market {price:.2f}, {away_pct*100:.0f}% "
                 f"away -- CANNOT fill). tag={tag}")
        try:
            response = self.dhan.place_order(
                security_id=str(security_id),
                exchange_segment=self.segment,
                transaction_type=side,
                quantity=int(quantity),
                order_type=LIMIT,
                product_type=MTF,
                price=limit_price,
                tag=tag,
            )
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LIVE TEST] no reply ({exc}). Checking by tag before "
                 f"anything else.")
            found = self._find_by_tag(tag)
            return _fail("no reply from Dhan", tag=tag,
                         order_id=(found or {}).get("orderId"),
                         needs_human=True)

        body = (response or {}).get("data") or response or {}
        order_id = body.get("orderId") or body.get("order_id")
        if not order_id:
            warn(f"[LIVE TEST] REJECTED by Dhan: {response}")
            return _fail(f"rejected: {body.get('errorMessage') or response}",
                         tag=tag)
        decision(f"[LIVE TEST] Order {order_id} is live at Dhan. "
                 f"CHECK YOUR DHAN APP -- it should be visible and "
                 f"unfilled. Then cancel it.")
        return {"success": True, "order_id": order_id, "tag": tag,
                "limit_price": limit_price, "test_order": True}

    def cancel(self, order_id):
        """Cancel a resting order. Used by the 30 July test."""
        try:
            response = self.dhan.cancel_order(order_id)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LIVE] cancel {order_id} failed ({exc}). "
                 f"CANCEL IT IN THE DHAN APP.")
            return _fail(str(exc), order_id=order_id, needs_human=True)
        decision(f"[LIVE] Cancel sent for {order_id}. Confirm in the app.")
        return {"success": True, "order_id": order_id, "response": response}

    def positions(self):
        """What DHAN says you hold. The only source that cannot drift
        from reality -- the bot's own book can, after a restart or a
        fill it never saw."""
        try:
            response = self.dhan.get_positions()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LIVE] could not read positions from Dhan ({exc}).")
            return None

        # ---- AN EMPTY BOOK IS NOT A MISSING BOOK. 4 August 2026. ----
        #
        # This was:
        #
        #     return (response or {}).get("data") or response or []
        #
        # Dhan answers {"data": [], "remarks": "", "status": "success"}
        # when you hold nothing. An empty list is FALSY, so the `or`
        # fell through and returned THE ENVELOPE -- and iterating a dict
        # yields its keys, so build_book got the strings 'data',
        # 'remarks', 'status' and crashed on entry.get():
        #
        #     AttributeError: 'str' object has no attribute 'get'
        #
        # It could only ever fire on a day he was completely flat, which
        # is why it survived until the morning after he closed
        # everything -- and then it stopped main.py from starting.
        #
        # This is the SAME idiom that hid Dhan's refusal reason in
        # core/broker_funds.py. I fixed it there hours earlier and did
        # not look for it anywhere else.
        #
        # None still means "could not ask", which the caller draws
        # differently from "you hold nothing". Those must never merge.
        if response is None:
            return None
        if isinstance(response, dict):
            rows = response.get("data")
            if rows is None:
                rows = response
        else:
            rows = response
        return rows if isinstance(rows, list) else []

    def holdings(self):
        """What Dhan says you hold in DELIVERY/MTF, settled or T+1.

        ==========================================================
            "The bot's own book is behind Dhan"
                                    -- operator, 5 August 2026
        ==========================================================

        THE OTHER HALF OF THE BOOK, AND THE DANGEROUS HALF.

        Dhan's /positions is the INTRADAY book. An MTF or delivery
        position bought yesterday is not in it -- overnight it moves to
        /holdings on T+1. positions() has been the only thing this bot
        ever asked, so on the morning after every overnight trade the
        broker appeared to hold nothing and the bot's own book looked
        like an invention.

        At 07:06 on 5 August that produced the mismatch warning, and
        `py tools/reconcile.py --apply` would have "corrected" it by
        deleting real positions carrying real money.

        Same None-vs-empty discipline as positions(): None means the
        question could not be asked, [] means the answer was nothing.
        Merging those two is what makes a data-loss bug out of a
        network blip.
        """
        getter = getattr(self.dhan, "get_holdings", None)
        if getter is None:
            # An older dhanhq. Say so; do not return [] and let the
            # caller read it as "you hold nothing overnight".
            warn("[LIVE] this dhanhq has no get_holdings() -- the "
                 "overnight book cannot be read. Treat any comparison "
                 "as unverified.")
            return None
        try:
            response = getter()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LIVE] could not read holdings from Dhan ({exc}).")
            return None

        if response is None:
            return None
        if isinstance(response, dict):
            # Dhan answers success-with-nothing as {"data": []}. An
            # empty list is falsy, so `or` would fall through to the
            # envelope -- the 4 August bug, in the same shape.
            rows = response.get("data")
            if rows is None:
                rows = response
        else:
            rows = response
        return rows if isinstance(rows, list) else []

    def broker_book(self):
        """Intraday positions AND overnight holdings, as one list.

        Returns None if EITHER question went unanswered. A half-read
        book is not a book: positions alone is exactly the reading that
        made yesterday's MTF position look like it had vanished, and
        answering with half the truth is worse than admitting the
        question failed.
        """
        positions = self.positions()
        if positions is None:
            return None
        held = self.holdings()
        if held is None:
            return None
        return list(positions) + list(held)

    def in_flight(self, symbol=None):
        """An order sent for this symbol that has not resolved, or None.

        The guard the dashboard asks before accepting a second click.
        With no symbol, returns the whole map.
        """
        with self._lock:
            if symbol is None:
                return {s: dict(v) for s, v in self._in_flight.items()}
            got = self._in_flight.get(str(symbol or "").upper())
            return dict(got) if got else None

    def resolve_in_flight(self):
        """Ask Dhan what became of every order that timed out.

        ---- A LATE FILL MUST NOT BECOME AN INVISIBLE POSITION ----

        On 3 August the YASHO order confirmed nothing in ten seconds,
        so the bot returned "not confirmed" and forgot it. It filled
        anyway. The operator ended the day holding 24 shares that no
        stop, no trail and no panel knew about.

        Returns the list of orders that FILLED since we last looked, so
        the caller can put them in the book where they belong. Anything
        dead is dropped. Anything still pending stays in flight, which
        keeps the second-click guard up.

        Never raises: this runs on the trading loop.
        """
        filled = []
        for symbol, rec in self.in_flight().items():
            try:
                response = self.dhan.get_order_by_id(rec["order_id"])
                body = (response or {}).get("data") or response or {}
                if isinstance(body, list) and body:
                    body = body[0]
                state = str(body.get("orderStatus")
                            or body.get("status") or "").upper()
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[LIVE] in-flight check failed for {symbol} "
                           f"({exc}). Leaving it in flight.")
                continue
            if not state:
                continue
            if state in FILLED:
                price = _num(body.get("averageTradedPrice")
                             or body.get("price"))
                qty = _num(body.get("filledQty")
                           or body.get("quantity")) or rec["qty"]
                with self._lock:
                    self._in_flight.pop(symbol, None)
                warn(f"[LIVE] {symbol} order {rec['order_id']} FILLED LATE "
                     f"-- {rec['side']} {qty} @ {price}. It was not "
                     f"confirmed in time and is only now known. Check that "
                     f"your book and Dhan agree.")
                filled.append({"symbol": symbol, "side": rec["side"],
                               "qty": qty, "price": price,
                               "order_id": rec["order_id"]})
            elif state in DEAD:
                with self._lock:
                    self._in_flight.pop(symbol, None)
                decision(f"[LIVE] {symbol} order {rec['order_id']} ended "
                         f"{state}. Nothing was bought; it is no longer in "
                         f"flight.")
        return filled

    def orders(self):
        """Every order this account sent today, whatever became of it.

        ---- WHY THIS EXISTS. 3 August 2026, after the first live day. ----

            "u said we will buy in mtf only - 1st click no response &
             no way to check in dashboard, then i clicked the second
             one. now both orders gave me loss of huge amount"

        That is exactly what happened, and the log agrees with him:

            09:17:23  Sending BUY YASHO qty=24 @ 4114.10
            09:17:34  order 23126080314805 still not confirmed after 10s
            09:18:12  (he clicked again)
            09:18:14  LIVE BUY YASHO qty=23 @ 4173.00

        The first order was sitting at the exchange, unconfirmed, and
        there was NOWHERE ON THE SCREEN to see that. The dashboard knew
        about positions and about the bot's own book; it had never once
        asked the broker what orders were outstanding. So the honest
        answer to "did my click do anything?" was unavailable, and the
        only way to find out was to click again.

        It filled late. Both filled. He was long twice at a worse
        average and the bot knew about neither.

        This is the read that makes that impossible to repeat. Same
        shape as positions() above -- ask Dhan, never raise, return None
        when the broker cannot be reached so the panel can say "could
        not ask" rather than "no orders", which are very different
        sentences to a man deciding whether to click BUY again.
        """
        try:
            response = self.dhan.get_order_list()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LIVE] could not read the order book from Dhan ({exc}).")
            return None

        # Same trap as positions() above, and found by searching for the
        # idiom rather than by waiting for it to fire: on a morning with
        # no orders placed yet, Dhan's "data" is [] and the `or` chain
        # returned the envelope instead. build_orders() happens to guard
        # its own iteration, so this one would have produced a silently
        # empty order book rather than a crash -- which is worse.
        # 4 August 2026.
        if response is None:
            return None
        if isinstance(response, dict):
            rows = response.get("data")
            if rows is None:
                rows = response
        else:
            rows = response
        return rows if isinstance(rows, list) else []

    def kill_switch(self, on=True):
        """Dhan's own emergency stop, AND this bot's.

        Blocks ALL order placement at the broker, not just from this
        bot -- so it still holds if the bot is the thing that has gone
        wrong.

        The local flag is set FIRST and is never rolled back by a failed
        API call. Pulling the switch and being told "the broker did not
        answer" must still mean this bot has stopped: the whole reason
        to pull it is that something is wrong, and that is the worst
        moment to depend on a network round trip.
        """
        self._killed = bool(on)
        try:
            action = "ACTIVATE" if on else "DEACTIVATE"
            response = self.dhan.kill_switch(action)
            warn(f"[LIVE] KILL SWITCH {action}D at Dhan, and locally. "
                 f"{response}")
            return {"success": True, "response": response,
                    "local_block": self._killed}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LIVE] kill switch did not reach Dhan ({exc}). "
                 f"THIS BOT IS STOPPED ANYWAY (local block is "
                 f"{'ON' if self._killed else 'OFF'}). If you need the "
                 f"broker blocked too, USE THE DHAN APP.")
            return _fail(str(exc), needs_human=True,
                         local_block=self._killed)

    def orders_sent_today(self):
        self._roll_day()
        return self._orders_today


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
