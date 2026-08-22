"""
==========================================================
Does the bot's book match the broker's?
==========================================================

    "Both dhan platform & our dashboard must be in synchronization no
     data mismatch & lag"                -- operator, 30 July 2026

trading/live_execution.py has had a positions() method since it was
written. Nothing has ever called it. So the bot's book and Dhan's book
have never once been compared, and the dashboard has been reporting the
bot's opinion of what is held as though it were a fact.

They drift for ordinary reasons, none of them exotic:

    a fill the bot never saw     restarted mid-order, or a websocket gap
    a manual trade               placed in the Dhan app, not by the bot
    a broker square-off          Dhan RMS closing a position on margin
    a partial fill               the bot books 500, the broker filled 300

WHAT THIS DOES NOT DO
---------------------
It does not correct anything. It REPORTS. Silently rewriting the bot's
book to match the broker would hide the very event worth knowing about,
and silently sending orders to make the broker match the bot could
double a position. Both are the kind of automatic fix that turns a
discrepancy into a loss.

In PAPER mode there is no broker book to compare against, so this
reports "not applicable" rather than a clean bill of health. Those are
different statements and the panel must not confuse them -- a green tick
that only means "we did not look" is worse than no tick at all.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

from core.logger import decision, diagnostic, warn


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _qty_of(row):
    """Net quantity from a Dhan position row.

    Dhan reports buy and sell legs separately on some accounts and a
    net quantity on others, so both shapes are handled. A long is
    positive, a short negative -- matching the bot's own convention.
    """
    for key in ("netQty", "net_qty", "netQuantity", "quantity", "qty"):
        if key in row:
            value = _num(row.get(key))
            if value is not None:
                return value

    # ---- A HOLDINGS ROW COUNTS ITS SHARES DIFFERENTLY. 5 Aug 2026 ----
    #
    #     "bot is printing WARNING: [BOOK] The bot's own book is behind
    #      Dhan"                          -- operator, 5 August 2026
    #
    # Dhan's /holdings rows carry totalQty / availableQty / t1Qty, not
    # netQty. Read with the position spellings alone they came back
    # zero, which compare() reads as "the broker does not have this" --
    # the exact reading that made reconcile.py --apply one keystroke
    # away from deleting a real overnight MTF book at 07:06.
    #
    # totalQty first: it is the whole holding. availableQty excludes
    # shares already pledged or blocked against a sell, and t1Qty is
    # the part not yet settled. Summing them would double-count.
    for key in ("totalQty", "total_qty", "totalQuantity"):
        if key in row:
            value = _num(row.get(key))
            if value is not None:
                return value
    available = _num(row.get("availableQty"))
    t1 = _num(row.get("t1Qty"))
    if available is not None or t1 is not None:
        return (available or 0.0) + (t1 or 0.0)

    buy = _num(row.get("buyQty")) or 0.0
    sell = _num(row.get("sellQty")) or 0.0
    return buy - sell


def _cost_of(row):
    """What the position was opened at, per share.

    31 July 2026. The panel listed a hand-placed ABCAPITAL and the
    operator's first question was the only one that matters: "no
    tracking of the position?"

    Fair. Knowing a position EXISTS is not knowing how it is doing.
    Dhan sends the average cost on every position row and compare()
    was discarding it.

    Field name varies by account and product, so every spelling seen
    in Dhan's docs and responses is tried. Returns None rather than 0
    -- a zero cost would compute an infinite return.
    """
    for key in ("costPrice", "cost_price", "buyAvg", "buyAvgPrice",
                "averagePrice", "avgPrice", "netAvgPrice",
                # /holdings spells it differently again.
                "avgCostPrice", "avg_cost_price"):
        if key in row:
            value = _num(row.get(key))
            if value:
                return value
    return None


def _product_of(row):
    """CNC / INTRADAY / MTF. Worth showing: an MTF position carries
    interest and a delivery one does not, and they are square-off'd
    under different rules."""
    for key in ("productType", "product_type", "product"):
        value = row.get(key)
        if value:
            return str(value).upper()
    return None


def _symbol_of(row):
    for key in ("tradingSymbol", "trading_symbol", "symbol",
                "securityId", "security_id"):
        value = row.get(key)
        if value:
            return str(value).upper().strip()
    return None


def compare(bot_positions, broker_rows, price_lookup=None):
    """The two books, side by side.

    Returns a dict the dashboard renders directly. `in_sync` is only
    True when there is genuinely nothing to report.

    price_lookup(symbol) -> the live price, so a position the bot did
    not open can still be MARKED TO MARKET. Optional, and None is
    handled everywhere: no feed means no P&L shown, never a P&L of
    zero. A position quietly reported as flat when it is down 3% is
    worse than one reported as unknown.
    """
    ours = {}
    for symbol, position in (bot_positions or {}).items():
        qty = _num(position.get("qty")) or 0.0
        if (position.get("direction") or "LONG").upper() == "SHORT":
            qty = -abs(qty)
        ours[str(symbol).upper()] = qty

    theirs = {}
    detail = {}
    for row in (broker_rows or []):
        if not isinstance(row, dict):
            continue
        symbol = _symbol_of(row)
        if not symbol:
            continue
        qty = _qty_of(row)
        if qty:
            theirs[symbol] = theirs.get(symbol, 0.0) + qty
            detail[symbol] = {"avg_price": _cost_of(row),
                              "product": _product_of(row)}

    only_ours, only_theirs, different = [], [], []
    for symbol in sorted(set(ours) | set(theirs)):
        mine = ours.get(symbol, 0.0)
        yours = theirs.get(symbol, 0.0)
        if mine and not yours:
            only_ours.append({"symbol": symbol, "bot_qty": mine})
        elif yours and not mine:
            # MARK IT TO MARKET.
            #
            # These are the hand-placed positions. The bot does not
            # manage them and must not pretend to -- but "we cannot see
            # your P&L" and "we choose not to tell you" are different
            # things, and only the first is honest. The tick feed is
            # already subscribed to this symbol; using it costs nothing.
            info = detail.get(symbol) or {}
            entry = info.get("avg_price")
            live = None
            if price_lookup is not None:
                try:
                    live = price_lookup(symbol)
                except Exception:                          # noqa: BLE001
                    live = None
            pnl = pct = None
            if entry and live:
                # Signed by direction: a short profits when price falls.
                pnl = (live - entry) * yours
                pct = ((live - entry) / entry) * 100.0
                if yours < 0:
                    pct = -pct
            only_theirs.append({
                "symbol": symbol, "broker_qty": yours,
                "avg_price": entry, "product": info.get("product"),
                "cmp": live, "pnl": pnl, "pnl_pct": pct,
            })
        elif round(mine, 2) != round(yours, 2):
            different.append({"symbol": symbol, "bot_qty": mine,
                              "broker_qty": yours})

    return {
        "available": True,
        "checked_at": datetime.now().strftime("%H:%M:%S"),
        "bot_count": len([q for q in ours.values() if q]),
        "broker_count": len(theirs),
        "only_in_bot": only_ours,
        "only_at_broker": only_theirs,
        "quantity_differs": different,
        "in_sync": not (only_ours or only_theirs or different),
    }


class BrokerSync:
    """Asks the broker what it holds, on a throttle.

    Throttled because it is a REST call on the same account the orders
    go through, and hammering it during a session is a good way to get
    rate-limited at the worst possible moment.
    """

    def __init__(self, execution=None, min_seconds=60,
                 price_lookup=None, engine=None, security_id_of=None,
                 adopt_with_stops=False, adopt_stop_pct=None):
        self.execution = execution
        self.min_seconds = min_seconds
        # Adoption is OFF unless main.py hands over an engine and turns
        # it on. Default-off so nothing that constructs a BrokerSync
        # for a report quietly starts writing positions into a book.
        self.engine = engine
        self.security_id_of = security_id_of
        self.adopt_with_stops = bool(adopt_with_stops and engine is not None)
        from core.adopt_positions import DEFAULT_STOP_PCT
        self.adopt_stop_pct = (DEFAULT_STOP_PCT if adopt_stop_pct is None
                               else adopt_stop_pct)
        # Symbols Dhan already held the first time we looked. Never
        # adopted. None until the first check, so an empty set and
        # "not looked yet" stay different things.
        self._pre_existing = None
        # Live price for marking hand-placed positions to market.
        # See compare() -- optional, and its absence shows as
        # "unknown" rather than as a P&L of zero.
        self.price_lookup = price_lookup
        self._last_at = 0.0
        self._last_result = None

    def _reader(self):
        """The callable that returns THE WHOLE broker book.

        ---- POSITIONS ALONE IS HALF THE BOOK. 5 August 2026. ----

        This used to return positions() and nothing else. Dhan's
        /positions is the INTRADAY book; an MTF or delivery position
        moves to /holdings overnight on T+1. So every morning after an
        overnight trade the broker looked empty, the bot's own book
        looked wrong, and reconcile.py --apply would have deleted real
        positions to "fix" it.

        broker_book() asks both and returns None if either fails. The
        positions() fallback is kept for PAPER and for any executor
        that has not got the new method, but it is second choice, not
        first.

        Paper execution has neither, and that is not an error -- there
        is no broker book in a simulation.
        """
        executor = getattr(self.execution, "executor", self.execution)
        return (getattr(executor, "broker_book", None)
                or getattr(executor, "positions", None))

    def _drop_closed_fn(self):
        """How to remove a position Dhan no longer has, or None.

        Only wired when an Engine was handed over, and it only ever
        DELETES from the bot's own book -- it places no order and
        touches nothing at the broker.

        ---- NEVER IN PAPER. 21 August 2026. ----

        A PAPER position does not exist at Dhan and never will. That
        is not a discrepancy, it is the definition of a simulation.

        On 21 August the bot was given a read-only broker view in
        PAPER for the first time (trading/broker_view.py, so it could
        finally see his nine real holdings). Ninety seconds after the
        restart:

            11:19:09  NCC: the bot still holds 230, Dhan has none --
                      it was closed elsewhere.
            11:19:09  NCC: removed from the bot's book. It will not be
                      managed or exited.
            11:19:09  URBANCO: ... removed from the bot's book.

        Two live paper positions, deleted for the crime of being
        simulated. Before the view existed this could not fire in
        PAPER because there was no reader at all, so the reconciler
        had never once been asked this question outside LIVE.

        READING the broker is safe in every mode. RECONCILING against
        it is only meaningful when the two books are supposed to
        describe the same money. Read at call time -- the mode is
        edited between sessions.
        """
        try:
            from config import TRADING_MODE
            live = str(TRADING_MODE).upper() == "LIVE"
        except Exception:                                   # noqa: BLE001
            live = False
        if not live:
            return None

        engine = getattr(self, "engine", None)
        if engine is None:
            return None
        book = getattr(engine, "open_positions", None)
        if book is None:
            return None

        def drop(symbol):
            book.pop(symbol, None)
            book.pop(str(symbol).upper(), None)

        return drop

    def check(self, bot_positions, force=False):
        import time
        reader = self._reader()
        if reader is None:
            return {"available": False, "in_sync": None,
                    "note": "PAPER mode -- there is no broker book to "
                            "compare against. This is not a clean bill "
                            "of health; nothing was checked."}
        now = time.monotonic()
        if (not force and self._last_result is not None
                and now - self._last_at < self.min_seconds):
            return self._last_result
        try:
            rows = reader()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[SYNC] Could not read the broker's positions: {exc}")
            return {"available": False, "in_sync": None,
                    "note": f"could not reach the broker: {exc}"}
        if rows is None:
            return {"available": False, "in_sync": None,
                    "note": "the broker did not answer -- treat the book "
                            "below as unverified"}
        result = compare(bot_positions, rows,
                         price_lookup=self.price_lookup)
        self._last_at = now
        self._last_result = result

        # ---- A TRADE HE PLACED IS NOT A FAULT. 3 August 2026. ----
        #
        #   "why bot is concerned on user trading - thats his choice -
        #    make all work towards one goal thats it. i told u all
        #    trades must show in dashboard , it does not concern from
        #    where user is trading - he had multiple options , dhan -
        #    app, website, direct charts, Dext3 terminal & dashboard."
        #
        # This used to WARN, every sixty seconds, that the book and Dhan
        # "DO NOT MATCH" -- because he had bought something from the
        # Dhan app. That is not a mismatch, it is a position. The bot
        # was treating the dashboard as the only legitimate place to
        # trade from and flagging its owner for using his own broker.
        #
        # The distinction that actually matters is much narrower:
        #
        #   Dhan has something the bot does not   NORMAL. His trade.
        #                                         Noted once, quietly.
        #   The bot has something Dhan does not   The BOT'S book is
        #                                         stale. Worth a warning,
        #                                         because the bot may act
        #                                         on a position that is
        #                                         not there.
        #
        # Only the second is a problem, and it is the bot's problem.
        stale = result["only_in_bot"] or result["quantity_differs"]
        theirs = result["only_at_broker"]

        # THE FIRST LOOK DEFINES WHAT IS "OLD". Everything Dhan reports
        # at startup is his own, from before this session.
        if self._pre_existing is None:
            self._pre_existing = {str(r.get("symbol") or "").upper()
                                  for r in theirs}
            if self._pre_existing:
                decision(f"[BOOK] {len(self._pre_existing)} position(s) "
                         f"already at Dhan when this session started: "
                         f"{', '.join(sorted(self._pre_existing))}. "
                         f"These are YOURS -- the bot will show them and "
                         f"will not stop, exit or manage them.")

        if theirs:
            # ---- SHOWN IS NOT PROTECTED. 5 August 2026. ----
            #
            #   "my goal is to stop manual trading & let the bot trade"
            #
            # This used to print a quiet note and stop. On the evening
            # of 5 August that note appeared three times -- BERGEPAINT
            # 100, DEEPAKNTR 100, MOREPENLAB 2000, about Rs 2 lakh on
            # MTF carried overnight with no stop and nothing watching.
            #
            # The old rule ("thats his choice", 3 August) was about the
            # bot NAGGING him for using the Dhan app. It was never
            # about leaving his money unmanaged, and he has since asked
            # for the opposite in as many words.
            #
            # core/adopt_positions.py takes them into the book with a
            # stop, so the trailing stop, the circuit guard and
            # MOVE_DIED start working on them. It places no order and
            # changes nothing at the broker.
            # ---- OFF MEANS OFF. 8 August 2026. ----
            #
            #     "i stopped trading button of the bot still it traded
            #      (even though it saved me today but thats not right
            #      if button is OFF it must not participate along with
            #      me, it only book keep my manual trades for learning
            #      purpose)"                          -- operator
            #
            # On 7 August he turned bot trading OFF at the open and
            # then bought KALYANKJIL, AUROPHARMA and HEROMOTOCO in the
            # Dhan app himself. Those positions APPEARED during the
            # session, so this adopted them, armed a trailing stop on
            # each, and sold all three out from under him.
            #
            # The skip_symbols guard below only ever protected what was
            # already open at STARTUP. Anything he opened after that
            # was fair game, and alert_only was never consulted here --
            # not once in the whole path.
            #
            # The switch is his statement of intent. OFF means the bot
            # observes and records; it does not reach into his account.
            # The positions still appear in the book for book-keeping,
            # they simply get no stop and no management.
            _off = bool(getattr(self.engine, "alert_only", True)) \
                if self.engine is not None else True
            if _off and self.adopt_with_stops:
                if not getattr(self, "_adopt_off_logged", False):
                    self._adopt_off_logged = True
                    decision(
                        "[ADOPT] Bot trading is OFF -- positions opened "
                        "in the Dhan app are recorded but NOT adopted. "
                        "The bot will not place a stop on them and will "
                        "not sell them.")
            if self.adopt_with_stops and self.engine is not None and not _off:
                try:
                    from core import adopt_positions
                    adopt_positions.adopt(
                        theirs, self.engine,
                        security_id_of=self.security_id_of,
                        stop_pct=self.adopt_stop_pct,
                        register=self.engine.adopt_position,
                        say=decision, warn_about=warn,
                        # compare() already marked each row to market
                        # via price_lookup, so row["cmp"] is normally
                        # there. This is the fallback for a row that
                        # had no price at the time.
                        price_of=self.price_lookup,
                        # ---- ONLY WHAT OPENS FROM NOW ON. 6 Aug 2026 ----
                        #
                        #   "i told you too not track my old positions."
                        #   "only fresh from tomorrow"
                        #
                        # Everything already at Dhan when the session
                        # starts is HIS, opened before the bot existed
                        # in this form, and he has said twice it must
                        # not be touched. The first startup records
                        # those symbols and they are never adopted --
                        # only a position that APPEARS during the
                        # session is taken into the book.
                        #
                        # It also removes the pre-open stop problem
                        # entirely: at 08:00 there is no live price, so
                        # every stop fell back to his cost and three
                        # were armed ABOVE the market.
                        skip_symbols=self._pre_existing)
                except Exception as exc:                   # noqa: BLE001
                    warn(f"[ADOPT] Could not adopt broker positions "
                         f"({exc}). They are shown but NOT protected.")
            else:
                for row in theirs:
                    diagnostic(
                        f"[BOOK] {row['symbol']}: {row['broker_qty']:.0f} "
                        f"at Dhan, opened outside the bot. Shown on the "
                        f"panel; the bot will not stop or exit it.")

        drop_closed = self._drop_closed_fn()
        if stale:
            warn("[BOOK] The bot's own book is behind Dhan:")
            # ---- IT KNEW, AND DID NOTHING. 6 August 2026. ----
            #
            #     "none of them were carried. all closed . right now
            #      only 3 stocks"                      -- operator
            #     "i did"        (he closed them in the Dhan app)
            #
            # He closed nine positions himself. The bot went on holding
            # all nine in its book, every one with stop: None, and
            # saved them to session_state.json at shutdown. On the next
            # start it would have believed it owned BASF, AWL, VGUARD,
            # GMDCLTD, RHIM, BELRISE, SHRIRAMFIN, NAVINFLUOR and
            # MOTHERSON -- and could have sent a SELL for stock that is
            # not there.
            #
            # This code SAW it. It printed "it was closed elsewhere"
            # and then said "Nothing is corrected automatically."
            # Detecting a fault and declining to fix it is not caution,
            # it is just a slower way of being wrong.
            #
            # Dropping a position the broker does not have can only
            # PREVENT an order; it can never cause one. That is the
            # safe direction, and it is the same Dhan -> bot rule this
            # module already follows everywhere else. So it is done
            # now, loudly, one line per position.
            for row in result["only_in_bot"]:
                warn(f"  {row['symbol']}: the bot still holds "
                     f"{row['bot_qty']:.0f}, Dhan has none -- it was "
                     f"closed elsewhere.")
                if drop_closed is not None:
                    try:
                        drop_closed(row["symbol"])
                        warn(f"  {row['symbol']}: removed from the bot's "
                             f"book. It will not be managed or exited.")
                    except Exception as exc:               # noqa: BLE001
                        warn(f"  {row['symbol']}: could NOT be removed "
                             f"({exc}). Check it in the Dhan app.")
            for row in result["quantity_differs"]:
                warn(f"  {row['symbol']}: bot {row['bot_qty']:.0f} vs "
                     f"Dhan {row['broker_qty']:.0f}. Dhan is right.")
            if drop_closed is None:
                warn("  Nothing is corrected automatically. "
                     "py tools/reconcile.py --apply adopts Dhan's version.")
        return result
