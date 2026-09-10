"""
==========================================================
A stop that survives this process dying
==========================================================

    "yeah pick that one. - pick the broker-side stop"
                                    -- operator, 2 August 2026

WHAT WAS TRUE BEFORE THIS FILE
------------------------------
    trading/live_execution.py   places MARKET orders only
                                no GTT, no bracket, no super order
    core/trailing_stop.py       TrailingStopEngine._state = {} -- RAM

Every stop this bot has ever had lived inside the running Python
process. If the process died, the laptop slept, the network dropped or
the static-IP proxy failed, an open MTF position at up to 4X, held
overnight, had NO STOP ANYWHERE. Dhan did not know one was intended.

The watchdog in main.py restarts the FEED. It does not restart the
process, and it cannot help if the machine is off.

WHY A FOREVER ORDER (GTT) AND NOT A SUPER ORDER
-----------------------------------------------
Dhan offers both, and both accept productType MTF. Super Order is the
more powerful instrument -- entry, target and stop in one request,
with the trail managed at Dhan. It was rejected for two reasons:

1. It only exists at ENTRY. Half the positions on this book are opened
   by the operator clicking BUY on the dashboard, and a Super Order
   cannot be wrapped around a position that already exists. A safety
   net with a hole in it for his own trades is not a safety net.

2. targetPrice is REQUIRED. His stated method is

       "ride untill the momentum stays - exit once it gone ruthlessly"

   A fixed target caps the winners that method exists to catch. Faking
   one at +50% to satisfy a required field would be putting a number
   into a live order because an API asked for it, which is exactly the
   kind of thing that later turns out to have cost a trade.

A Forever Order is additive. It touches nothing in the entry path --
which, on the night before live trading, is most of the argument.

THIS IS A BACKSTOP. IT DOES NOT REPLACE THE LIVE STOP.
------------------------------------------------------
core/trailing_stop.py stays exactly as it is. It is faster, it
ratchets, and it knows things the exchange does not. The GTT sits
BELOW it and only ever fires when the process is not there to fire
first. Two stops racing at the same price is how a position gets sold
twice.

THE DANGEROUS FAILURE MODE, NAMED
---------------------------------
A GTT left behind after the position is closed will sell shares that
are no longer held. On MTF that is not a no-op -- it is a short.

So every exit cancels, `reconcile()` runs at startup against Dhan's
own list, and an order this module cannot account for is reported
rather than quietly cancelled. Getting OUT is never blocked by this
module; getting confused is always reported.

OFF BY DEFAULT
--------------
BROKER_STOP_ENABLED is False until the operator turns it on, same
pattern as the paper/real switch. One switch away from placing real
resting orders is not a switch this code gets to flip for him.

Author : H&M Opportunity Trader
==========================================================
"""

import threading

from core.logger import decision, diagnostic, warn

SELL = "SELL"
BUY = "BUY"
MARKET = "MARKET"
SINGLE = "SINGLE"
LONG = "LONG"
SHORT = "SHORT"

# Dhan's own words for "this order is no longer resting".
GONE = ("TRADED", "CANCELLED", "REJECTED", "EXPIRED")


class BrokerStop:
    """Resting stop orders at Dhan, one per open position.

    Every method is best-effort and never raises. A protective order
    that cannot be placed is LOUD; it is never a reason to block a
    trade, and never a reason to stop the engine.
    """

    def __init__(self, dhan_client, exchange_segment, product_type,
                 enabled=False, resync_pct=0.01, tag_prefix="OTSTOP",
                 is_live_position=None):
        self.dhan = dhan_client
        self.segment = exchange_segment
        self.product = product_type
        self.enabled = bool(enabled)
        # ---- WHICH POSITIONS ARE REAL. 10 September 2026. ----
        #
        # A resting order at Dhan is a live instruction and may only
        # protect a position that was itself opened for real. Until
        # today that was decided by config.TRADING_MODE, read at
        # placement time. TRADING_MODE is frozen at "PAPER" and the
        # switch does not move it, so this refused EVERY stop while the
        # switch was ON -- real positions with no broker backstop.
        #
        # THE SWITCH IS THE WHOLE ANSWER. The engine passes a predicate
        # that answers, per symbol, whether that position was opened for
        # real (trading/execution._who_opened). None means no predicate
        # was wired, and place() then FAILS CLOSED -- refuses -- because
        # the 19 August NILKAMAL fault is a real order resting against a
        # simulated position, and the safe direction when we cannot tell
        # is to place nothing. Cancelling is never gated: see cancel().
        self._is_live_position = is_live_position
        # How far the live stop must ratchet ABOVE the resting trigger
        # before the resting order is moved up to follow it. Every
        # modify is an API call on the order path; syncing on every
        # tick would be thousands a day for a protection that only
        # matters if the process dies.
        self.resync_pct = float(resync_pct)
        self.tag_prefix = tag_prefix
        self._lock = threading.Lock()
        # symbol -> {"order_id", "trigger", "qty", "direction"}
        self._resting = {}

    # ------------------------------------------------------------
    def _live(self):
        return self.enabled and self.dhan is not None

    def resting(self):
        """{symbol: dict} -- what this module believes is at Dhan."""
        with self._lock:
            return {s: dict(v) for s, v in self._resting.items()}

    # ---- TURNED ON AND OFF WHILE THE MARKET IS OPEN, 2 Aug 2026 ----
    #
    #     "we can do this at live market too?"
    #     "without stopping main.py?"
    #
    # It could not, and that was a real flaw. BROKER_STOP_ENABLED was
    # read once when the engine was built, so the only way to switch it
    # on was to restart -- and a mid-session restart is exactly the
    # thing you do NOT want to be doing at the moment you decide you
    # want more protection.
    #
    # So it is a runtime switch. config.py still decides what it is at
    # STARTUP; these decide what it is from here on.

    def enable(self, open_positions=None, hard_stop_for=None):
        """Switch on now, and protect what is already open.

        Turning it on with positions running and doing nothing about
        them would be the worst of both: the operator believes he is
        covered, and the trades opened before the click are not.
        """
        if self.dhan is None:
            warn("[BROKER_STOP] No broker connection -- cannot switch on.")
            return {"enabled": False, "error": "no broker connection"}
        was = self.enabled
        self.enabled = True
        decision("[BROKER_STOP] SWITCHED ON"
                 + ("" if not was else " (already on)"))
        if open_positions:
            return {"enabled": True,
                    "report": self.reconcile(open_positions,
                                             hard_stop_for=hard_stop_for)}
        return {"enabled": True, "report": None}

    def disable(self, cancel_resting=True):
        """Switch off, and by default PULL every resting order.

        Leaving them behind would be the dangerous half of this whole
        module: an order resting at Dhan with this module switched off
        is one nothing will ever cancel on the exit, and it will sell
        stock that is no longer held.

        cancel_resting=False exists for the deliberate case -- "stop
        managing these, but leave the protection in place" -- and it
        says so loudly, because those orders are then the operator's to
        watch.
        """
        self.enabled = False
        pulled, left = 0, []
        if cancel_resting:
            for symbol in list(self.resting()):
                if self.cancel(symbol, why="broker stop switched off"):
                    pulled += 1
                else:
                    left.append(symbol)
        else:
            left = sorted(self.resting())
            warn(f"[BROKER_STOP] SWITCHED OFF with {len(left)} order(s) "
                 f"still resting at Dhan: {', '.join(left[:8])}. Nothing "
                 f"will cancel them when those positions close -- they "
                 f"are yours to watch now.")
        decision(f"[BROKER_STOP] SWITCHED OFF. {pulled} resting order(s) "
                 f"cancelled.")
        return {"enabled": False, "cancelled": pulled, "left": left}

    @staticmethod
    def _order_id(reply):
        """Dhan's reply shapes differ between SDK versions and between
        the raw REST body and the wrapper. Read all of them rather than
        assume one -- an order id we fail to read is an order we cannot
        cancel."""
        if not isinstance(reply, dict):
            return None
        for key in ("orderId", "order_id"):
            if reply.get(key):
                return str(reply[key])
        data = reply.get("data")
        if isinstance(data, dict):
            for key in ("orderId", "order_id"):
                if data.get(key):
                    return str(data[key])
        return None

    # ------------------------------------------------------------
    # PLACE
    # ------------------------------------------------------------
    def place(self, symbol, security_id, qty, stop_price, direction=LONG):
        """Rest a protective stop at Dhan for one open position.

        `stop_price` is the HARD stop -- the level below which the
        trade was wrong when it was taken. Not the ratcheted live stop:
        see the class docstring for why this sits below it.

        Returns the order id, or None. Never raises.
        """
        if not self._live():
            return None

        # ---- A REAL ORDER MAY NOT PROTECT A PRETEND POSITION ----
        #      19 August 2026, re-keyed to the switch 10 September 2026.
        #
        # The second, independent check. On 19 August a PAPER buy of
        # NILKAMAL at 14:26:33 produced a REAL resting SELL at Dhan ten
        # seconds later, because one flag decided it and that flag knew
        # nothing about whether the rest of the system was simulating.
        #
        # It is now decided PER POSITION, by who opened it -- not by a
        # session-wide TRADING_MODE, which was frozen at "PAPER" and so
        # (once the switch became the whole answer) refused every real
        # stop instead. The predicate is the engine's, reading the
        # fill's own remembered provenance. No predicate wired -> refuse:
        # a real order resting against a position we cannot vouch for is
        # the one thing this must never do.
        if self._is_live_position is None or not self._is_live_position(symbol):
            warn(f"[BROKER_STOP] REFUSED to rest a stop for {symbol}: it "
                 f"was not opened for real (the switch was OFF when it was "
                 f"bought, or its origin is unknown). A resting order at "
                 f"the broker is a live instruction and must never protect "
                 f"a simulated position.")
            return None

        try:
            qty = int(qty)
            stop_price = round(float(stop_price), 2)
        except (TypeError, ValueError):
            warn(f"[BROKER_STOP] {symbol}: bad qty/price "
                 f"({qty!r}/{stop_price!r}) -- nothing placed.")
            return None
        if qty <= 0 or stop_price <= 0:
            warn(f"[BROKER_STOP] {symbol}: qty={qty} stop={stop_price} "
                 f"-- refusing to rest a nonsense order.")
            return None

        with self._lock:
            if symbol in self._resting:
                # Already protected. Placing a second would double the
                # sell quantity the moment it triggers.
                return self._resting[symbol].get("order_id")

        side = SELL if direction == LONG else BUY
        try:
            reply = self.dhan.place_forever(
                security_id=str(security_id),
                exchange_segment=self.segment,
                transaction_type=side,
                product_type=self.product,
                # ---- THIS CLAIM IS NOT WHAT DHAN DID. 19 Aug 2026 ----
                #
                # The comment here read: "MARKET on trigger,
                # deliberately. A LIMIT can go unfilled through a
                # gap-down." That is the right INTENT and it is not
                # what came back.
                #
                # On 19 August this sent orderType=MARKET, price=0,
                # triggerPrice=2023.75 to /forever/orders. Dhan booked
                # it as:
                #
                #     NILKAMAL   SELL 28 LIMIT MTF -> REJECTED
                #
                # A LIMIT, at 2027.20 -- a price this code never sent.
                # Dhan's Forever Order docs list price AND triggerPrice
                # as both REQUIRED, so price=0 is very likely why.
                #
                # It was rejected for an unrelated reason (no MTF
                # position to sell), so this is ONE observation and
                # not a proven mechanism. It is written down rather
                # than guessed at, and the guarantee above is
                # withdrawn until a real LIVE stop is placed and the
                # order book is read back.
                #
                # NOT redesigned on one data point. STOP_LOSS_MARKET
                # exists in the modify contract and may be the right
                # type here, and choosing it on this much evidence is
                # how the wrong comment got written in the first place.
                order_type=MARKET,
                quantity=qty,
                price=0,
                trigger_Price=stop_price,      # SDK spells it this way
                order_flag=SINGLE,
                validity="DAY",
                tag=f"{self.tag_prefix}{symbol}"[:30],
                symbol=symbol,
            )
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BROKER_STOP] {symbol}: could NOT rest a stop at "
                 f"Dhan ({exc}). The position is protected by this "
                 f"process ONLY -- if it stops, there is no stop.")
            return None

        order_id = self._order_id(reply)
        if not order_id:
            warn(f"[BROKER_STOP] {symbol}: Dhan accepted nothing "
                 f"readable ({reply!r}). Treating as NOT protected.")
            return None

        with self._lock:
            self._resting[symbol] = {"order_id": order_id,
                                     "trigger": stop_price,
                                     "qty": qty,
                                     "direction": direction}
        decision(f"[BROKER_STOP] {symbol}: {side} {qty} resting at Dhan, "
                 f"trigger {stop_price:.2f} (id {order_id}). This one "
                 f"survives a restart.")
        return order_id

    # ------------------------------------------------------------
    # MOVE
    # ------------------------------------------------------------
    def sync(self, symbol, live_stop):
        """Follow the live trail upward, but only when it is worth an
        API call.

        NEVER MOVES THE STOP DOWN. A protective order that loosens is
        worse than none, because it reads as protection. If the live
        stop somehow falls below the resting trigger, the resting one
        stays where it is and the disagreement is reported.
        """
        if not self._live():
            return False
        with self._lock:
            held = self._resting.get(symbol)
            if not held:
                return False
            current = float(held["trigger"])
            qty, order_id = held["qty"], held["order_id"]
            direction = held.get("direction", LONG)
        try:
            live_stop = round(float(live_stop), 2)
        except (TypeError, ValueError):
            return False

        if direction == LONG:
            better = live_stop > current * (1.0 + self.resync_pct)
        else:
            better = live_stop < current * (1.0 - self.resync_pct)
        if not better:
            return False

        try:
            self.dhan.modify_forever(
                order_id=order_id, order_flag=SINGLE, order_type=MARKET,
                leg_name="TARGET_LEG",     # SINGLE forever orders carry
                                           # one leg, and Dhan names it
                                           # TARGET_LEG regardless of
                                           # which side it protects
                quantity=qty, price=0, trigger_price=live_stop,
                disclosed_quantity=0, validity="DAY")
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BROKER_STOP] {symbol}: could not move the resting "
                 f"stop {current:.2f} -> {live_stop:.2f} ({exc}). The "
                 f"OLD trigger is still in force, which is safe.")
            return False

        with self._lock:
            if symbol in self._resting:
                self._resting[symbol]["trigger"] = live_stop
        diagnostic(f"[BROKER_STOP] {symbol}: resting stop moved "
                   f"{current:.2f} -> {live_stop:.2f}")
        return True

    # ------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------
    def cancel(self, symbol, why=""):
        """Pull the resting stop when the position is closed.

        THE ONE THAT MUST NOT BE MISSED. A GTT left behind after an
        exit sells stock that is no longer held -- on MTF that opens a
        SHORT. The local record is dropped whatever Dhan replies,
        because a stale local record would stop reconcile() from ever
        seeing the orphan.
        """
        # NOT gated on self.enabled, deliberately. Cancelling is always
        # safe and always correct, and the one moment it is most needed
        # is right after the switch has been turned OFF -- if this
        # refused to run then, every order resting at that moment would
        # be stranded with nothing left to clean it up.
        #
        # Same principle as the SELL endpoint on the dashboard: getting
        # OUT is never blocked by a switch.
        if self.dhan is None:
            return False
        with self._lock:
            held = self._resting.pop(symbol, None)
        if not held:
            return False
        try:
            self.dhan.cancel_forever(held["order_id"])
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BROKER_STOP] {symbol}: FAILED to cancel resting "
                 f"stop {held['order_id']} ({exc}). It may still be at "
                 f"Dhan with no position behind it -- CHECK THE "
                 f"TERMINAL. reconcile() will report it on next start.")
            return False
        decision(f"[BROKER_STOP] {symbol}: resting stop cancelled"
                 + (f" -- {why}" if why else ""))
        return True

    # ------------------------------------------------------------
    # RECONCILE
    # ------------------------------------------------------------
    def reconcile(self, open_positions, hard_stop_for=None):
        """Make Dhan's resting orders match the positions actually held.

        Run at startup, because that is exactly the moment this module
        cannot trust its own memory: `_resting` is empty after a
        restart while Dhan's orders are not.

        Returns a report dict. It CANCELS an orphan only when the order
        carries this module's own tag -- an unknown Forever Order might
        be one the operator placed by hand in the Dhan app, and
        cancelling that would be this bot reaching into his account and
        removing a protection he set himself.
        """
        report = {"at_broker": 0, "adopted": 0, "orphans_cancelled": 0,
                  "orphans_left": [], "missing": [], "errors": []}
        if self.dhan is None:
            report["errors"].append("no broker connection")
            return report
        if not self.enabled:
            report["errors"].append("broker stop is off")
            return report

        try:
            reply = self.dhan.get_forever()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BROKER_STOP] Could not read Dhan's resting orders "
                 f"({exc}). Cannot say whether anything is protected.")
            report["errors"].append(str(exc))
            return report

        rows = reply.get("data") if isinstance(reply, dict) else reply
        rows = [r for r in (rows or []) if isinstance(r, dict)]
        rows = [r for r in rows
                if str(r.get("orderStatus") or "").upper() not in GONE]
        report["at_broker"] = len(rows)

        held = {str(s).upper() for s in (open_positions or {})}
        seen = set()
        for row in rows:
            symbol = str(row.get("tradingSymbol") or "").upper()
            order_id = str(row.get("orderId") or "")
            ours = str(row.get("correlationId") or "").startswith(
                self.tag_prefix)
            if symbol and symbol in held:
                # Adopt it, so cancel() can pull it later.
                with self._lock:
                    self._resting.setdefault(symbol, {
                        "order_id": order_id,
                        "trigger": float(row.get("triggerPrice") or 0) or 0.0,
                        "qty": int(row.get("quantity") or 0),
                        "direction": (LONG if str(
                            row.get("transactionType") or "").upper() == SELL
                            else SHORT)})
                seen.add(symbol)
                report["adopted"] += 1
                continue
            # No position behind it.
            if ours:
                try:
                    self.dhan.cancel_forever(order_id)
                    report["orphans_cancelled"] += 1
                    warn(f"[BROKER_STOP] Cancelled an orphan stop on "
                         f"{symbol or order_id} -- no position is held.")
                except Exception as exc:                   # noqa: BLE001
                    report["errors"].append(f"{symbol}: {exc}")
            else:
                # Not ours. Say so; do not touch it.
                report["orphans_left"].append(symbol or order_id)

        for symbol in sorted(held - seen):
            report["missing"].append(symbol)
            if hard_stop_for is None:
                continue
            try:
                position = (open_positions or {})[symbol]
                stop = hard_stop_for(symbol, position)
                if stop:
                    self.place(symbol, position.get("security_id"),
                               position.get("qty"), stop,
                               direction=position.get("direction", LONG))
            except Exception as exc:                       # noqa: BLE001
                report["errors"].append(f"{symbol}: {exc}")

        if report["orphans_left"]:
            warn(f"[BROKER_STOP] {len(report['orphans_left'])} resting "
                 f"order(s) at Dhan are NOT this bot's and have no "
                 f"position here: {', '.join(report['orphans_left'][:8])}. "
                 f"Left alone on purpose -- they may be yours.")
        if report["missing"]:
            warn(f"[BROKER_STOP] {len(report['missing'])} open position(s) "
                 f"had NO resting stop at Dhan: "
                 f"{', '.join(report['missing'][:8])}.")
        decision(f"[BROKER_STOP] Reconciled: {report['at_broker']} at "
                 f"Dhan, {report['adopted']} adopted, "
                 f"{report['orphans_cancelled']} orphan(s) cancelled, "
                 f"{len(report['missing'])} were unprotected.")
        return report


def hard_stop_price(entry_price, direction, pct):
    """The level the trade was wrong at, from the entry.

    Deliberately NOT the ratcheted live stop. See BrokerStop's
    docstring: the resting order sits below the live one so the two
    cannot race for the same fill.
    """
    try:
        entry_price = float(entry_price)
        pct = float(pct)
    except (TypeError, ValueError):
        return None
    if entry_price <= 0 or pct <= 0:
        return None
    if direction == SHORT:
        return round(entry_price * (1.0 + pct), 2)
    return round(entry_price * (1.0 - pct), 2)
