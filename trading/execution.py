"""
Single gateway all buy/sell requests pass through. The Engine never
knows whether it is PAPER or LIVE.

2026-07-28: LIVE is now implemented (trading/live_execution.py), for a
first real order on 30 July and live trading on 3 August.

IT TAKES TWO SWITCHES, NOT ONE.

    TRADING_MODE = "LIVE"
    I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True

Both must be set. One switch is one typo away from spending real money
by accident; two is a decision.

If TRADING_MODE says LIVE and the second flag does not, this RAISES
rather than quietly falling back to paper. A bot the operator believes
is live but which is only pretending is the worse of the two failures --
he would sit watching fills that never happened.

Same for a missing client: LIVE without a Dhan client refuses to start.
"""

from config import I_UNDERSTAND_THIS_PLACES_REAL_ORDERS
# TRADING_MODE is NOT imported here. _route() below never reads it
# -- the switch alone decides paper or Dhan -- and the one place
# that does check it reads it at call time, so a module binding
# could only ever be a stale copy of a dial that moves.

# ---- THE THIRD MODE IS GONE. 31 August 2026. ----
#
#     "i asked you to create two modes paper & real trading . all
#      common in both with only distinct is real uses dhan path with
#      real money & paper do not use dhan real money. remaining all
#      same."                                        -- the operator
#
# There were three. Two of them he asked for; the third,
# LIVE_ALLOW_BOT_ENTRIES, was mine. It said: even with the switch ON,
# the bot's OWN trades stay on paper and only his dashboard clicks are
# real. That is a third mode wearing a disguise, and it showed -- with
# it in place, "what happens when I click ON" could not be answered in
# one sentence. It needed a table.
#
# It also caused the bug fixed directly below. Entries filling on paper
# while their exits went live is a state that can only exist if entries
# and exits are allowed to disagree about which money they are, and
# they could only disagree because of that flag.
#
# The safety it was meant to add is in the switch already, and always
# was. The switch starts OFF. It moves only when he clicks it. The
# process still refuses to go live without a Dhan client and without
# I_UNDERSTAND_THIS_PLACES_REAL_ORDERS. Nothing about a trade the bot
# thought of needed a permission that the same trade, clicked by hand,
# did not.
#
# OPERATOR_CLICKS goes with it. Nothing asks whose idea a trade was any
# more, because with two modes it cannot matter: in PAPER nothing
# reaches Dhan, in REAL everything does.
from core.logger import warn
from trading.broker_view import BrokerView
from trading.paper_execution import PaperExecution


class Execution:

    # ==========================================================
    # ONE SWITCH: OFF = PAPER, ON = REAL.  31 August 2026.
    # ==========================================================
    #
    #     "keep simple ON = REAL TRADES . OFF = PAPER TRADES . all
    #      same entry, exits, capital allotted & everything same"
    #     "by default OFF PAPER TRADE"        -- the operator
    #
    # The old switch meant TRADE / DO NOT TRADE, and that third state
    # is what produced 65 alerts and 0 trades on 31 August -- a day
    # with no record of whether any of them were right.
    #
    # Both executors are built up front and the switch chooses between
    # them per order. Nothing else differs: same entries, same exits,
    # same sizing, same capital. Only whose money.
    #
    # It starts OFF on every restart, whatever config says. A process
    # that comes back while he is away from the desk must come back on
    # paper.
    live = False

    def __init__(self, turnover_lookup=None, dhan_client=None,
                 price_lookup=None, open_position_count=None,
                 range_lookup=None):
        # PAPER is always built. It is what the switch returns to, and
        # what every order takes while the switch is OFF.
        # range_lookup lets the paper fill be capped at a price the
        # stock actually traded -- see trading/slippage.fill_price().
        # None means uncapped, exactly as before.
        self.executor = PaperExecution(turnover_lookup=turnover_lookup,
                                       range_lookup=range_lookup)
        self.mode = "PAPER"

        # LIVE is built too, when this process is capable of it, so the
        # switch has something to route to without a restart. Building
        # it is not using it -- self.live is False until he turns it on.
        self._live = None
        self._live_refused = None
        if not I_UNDERSTAND_THIS_PLACES_REAL_ORDERS:
            self._live_refused = ("I_UNDERSTAND_THIS_PLACES_REAL_ORDERS "
                                  "is False")
        elif dhan_client is None:
            self._live_refused = "no Dhan client in this process"
        else:
            try:
                from trading.live_execution import LiveExecution
                self._live = LiveExecution(
                    dhan_client, price_lookup=price_lookup,
                    open_position_count=open_position_count)
            except Exception as exc:                       # noqa: BLE001
                self._live_refused = str(exc)[:120]

        # ---- THE OLD RULE, KEPT AS A REFUSAL. 31 August 2026. ----
        #
        # TRADING_MODE=LIVE used to pick the live executor here and
        # RAISE if the acknowledgement or the client were missing --
        # "refusing to start rather than quietly paper-trading a
        # session you believe is real". That instinct is right and it
        # is kept: if the config says LIVE and this process cannot do
        # it, that is still a refusal to start, not a quiet fallback.
        #
        # What changed is that LIVE is no longer chosen AT STARTUP. It
        # is chosen per order, by the switch, and the switch begins
        # OFF -- so the ordinary path now starts on paper and stays
        # there until he presses ON.
        from config import TRADING_MODE as _mode   # at call time
        if str(_mode).upper() == "LIVE" and self._live is None:
            raise RuntimeError(
                "TRADING_MODE is LIVE but this process cannot place real "
                "orders (%s). Refusing to start -- a bot you believe is "
                "live and which is only pretending is the worse failure."
                % self._live_refused)
        if self._live is not None:
            warn("=" * 62)
            warn("  REAL ORDERS ARE POSSIBLE IN THIS PROCESS.")
            warn("  The switch starts OFF -- everything is PAPER until")
            warn("  you press ON. MARKET orders, MTF product; a market")
            warn("  order cannot be cancelled once it fills.")
            warn("=" * 62)


        # ---- SIMULATED ORDERS, REAL BOOK. 21 August 2026. ----
        #
        #   "why bot is unable to see dhan account complete
        #    holdings? ... none of them were happening then whats
        #    the use of the bot trading?"
        #
        # He held nine real positions at Dhan and the dashboard
        # showed a phantom NILKAMAL. The client was here the whole
        # time -- main.py passes it in BOTH modes -- and this
        # branch threw it away, because one line decided both
        # "may we place orders" and "may we look".
        #
        # Those are different questions. Simulating a fill must
        # never touch his account; READING what he already holds
        # touches nothing at all. BrokerView has no order method
        # of any kind, so this cannot become the NILKAMAL fault
        # a second time.
        view = BrokerView(dhan_client, price_lookup=price_lookup)
        if view.available:
            self.executor.broker_book = view.broker_book
            self.executor.holdings = view.holdings
            self.executor.positions = view.positions
        self.broker_view = view

    def _live_executor(self):
        """The live executor, or None if this process cannot place a
        real order at all."""
        return getattr(self, "_live", None)

    def _route(self, reason, selling=False, symbol=None):
        """Which executor takes this order. Two answers, one question.

            switch OFF  ->  paper.  Nothing reaches Dhan.
            switch ON   ->  Dhan.

        That is the whole rule and there is no third branch. `reason` is
        still accepted because every caller passes it, but nothing here
        reads it any more: it used to decide whether a trade was his
        idea or the bot's, and with two modes that cannot matter.

        The one thing that is not a mode is below -- an exit follows the
        entry that opened it. That is not a third state, it is the same
        two states remembered: a position opened on paper is closed on
        paper even if he flips the switch while it is open.
        """
        if not self.live:
            return self.executor
        live = self._live_executor()
        if live is None:
            self._say_once("no-live",
                           "The switch is ON but this process cannot place "
                           "real orders (no Dhan client, or "
                           "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS is off). "
                           "Trading on PAPER.")
            return self.executor
        if selling:
            # ---- AN EXIT FOLLOWS ITS OWN ENTRY. 31 August 2026. ----
            #
            # This was `return live` with the comment "a real position,
            # a real exit". That comment states something the code had
            # not established, and on 31 August it stopped being true.
            #
            # It matters for one situation, and it is one he will hit:
            # he flips the switch with a position already open. A stock
            # bought on paper this morning must be sold on paper this
            # afternoon. Selling it for real would place a real SELL for
            # stock he never bought, and in NSE cash intraday that is
            # not a harmless no-op -- it opens a real short the bot does
            # not know it is carrying.
            #
            # Every fill is stamped PAPER or LIVE in data/fills.db and
            # this process remembers its own besides, so this is a
            # lookup, not a guess.
            #
            # Nothing on record goes live, unchanged: a real position
            # with no stop is the worse of the two mistakes.
            if self._who_opened(symbol) == "paper":
                return self.executor
        return live

    def _say_once(self, key, message):
        seen = getattr(self, "_said", None)
        if seen is None:
            seen = self._said = set()
        if key in seen:
            return
        seen.add(key)
        warn("[EXECUTION] " + message)

    def buy(self, security_id, symbol, price, qty, reason="", at_time=None):
        chosen = self._route(reason, symbol=symbol)
        # Remembered here, at the moment of the decision, so the exit
        # never has to re-derive it from settings that may have moved.
        opened = getattr(self, "_opened_by", None)
        if opened is None:
            opened = self._opened_by = {}
        opened[str(symbol).upper()] = ("live" if chosen is self._live
                                       else "paper")
        return chosen.buy(security_id, symbol, price, qty, reason, at_time)

    def sell(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self._route(reason, selling=True, symbol=symbol).sell(
            security_id, symbol, price, qty, reason, at_time)

    # ------------------------------------------------------------

    def _who_opened(self, symbol):
        """"paper", "live", or None when nothing is on record.

        In-process memory first -- it is exact and cannot be stale. The
        fills log second, for the case that matters most: a restart in
        the middle of a session, when the dictionary is empty and there
        are still open positions to look after.
        """
        key = str(symbol or "").upper()
        if not key:
            return None
        remembered = getattr(self, "_opened_by", None) or {}
        if key in remembered:
            return remembered[key]
        import sqlite3
        # Read from the module at CALL time, not bound at import. The
        # fill log makes the same point about itself in its own
        # comments: a path captured at import is the production one
        # forever, which is how a test ends up writing to data/.
        try:
            import core.fill_log as _log
            _fills = _log.DB_PATH
        except Exception:                                  # noqa: BLE001
            _fills = "data/fills.db"
        try:
            conn = sqlite3.connect(f"file:{_fills}?mode=ro", uri=True)
            row = conn.execute(
                "SELECT mode FROM fills WHERE upper(symbol) = ? "
                "AND upper(side) = 'BUY' ORDER BY id DESC LIMIT 1",
                (key,)).fetchone()
            conn.close()
        except Exception:                                  # noqa: BLE001
            return None
        if not row:
            return None
        return "paper" if str(row[0]).upper() == "PAPER" else "live"
