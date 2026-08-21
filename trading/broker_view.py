"""A read-only window on the real Dhan book. Safe in every mode.

==========================================================
    "why bot is unable to see dhan account complete holdings?
     i'm expecting that bot must see the positions holding &
     update me about those stocks updates & reasons to hold /
     add / sell completely"
                            -- operator, 21 August 2026
==========================================================

He was holding nine real positions at Dhan that morning -- CORONA,
SBIN, AARTIPHARM, NEOGEN, TNPETRO, PANAMAPET, SOLARINDS, DEEPAKFERT,
KABRAEXTRU -- and the bot's book showed one phantom NILKAMAL and
nothing else.

The endpoint was fine. The token was fine. The reading worked on the
first try when it was finally asked. The bot simply never asked,
because trading/execution.py drops the Dhan client on the floor in
PAPER:

    self.executor = PaperExecution(turnover_lookup=turnover_lookup)

main.py has always PASSED the client in both modes, with a comment
saying PAPER ignores it on purpose. That was right for ORDERS and
wrong for READS, and the two got decided by the same line.

WHY THIS IS A SEPARATE CLASS AND NOT A FLAG

On 19 August a PAPER position grew a REAL protective sell, because
one flag decided whether a live order could leave. The lesson was
that mode checks are not enough on their own -- the safe thing is to
not have the capability at all.

So this exposes THREE methods and no others. There is no place_order
here, no place_forever, no modify, no cancel. It is not that this
class refuses to trade; it is that it has no way to. A future edit
cannot accidentally re-open the door, because the door was never
built.

It delegates the parsing to LiveExecution rather than re-implementing
it. This suite has been bitten more than once by a second copy that
drifted from the first -- the /positions vs /holdings split alone
took a morning to find -- and the answer the panel shows must be the
same answer the live path would have got.

Author : H&M Opportunity Trader
"""

from core.logger import warn


class BrokerView:
    """Reads Dhan. Cannot write to it.

    Every method answers None when the question could not be asked and
    [] when the answer was genuinely nothing. Merging those two is what
    turns a network blip into "your positions vanished".
    """

    def __init__(self, dhan_client, price_lookup=None):
        self.dhan = dhan_client
        self._live = None
        if dhan_client is None:
            return
        try:
            from trading.live_execution import LiveExecution
            # Inert: LiveExecution.__init__ sets attributes and opens
            # no connection. Checked before relying on it.
            self._live = LiveExecution(dhan_client,
                                       price_lookup=price_lookup)
        except Exception as exc:                            # noqa: BLE001
            warn(f"[BROKER_VIEW] Could not open a read-only view: {exc}")
            self._live = None

    @property
    def available(self):
        return self._live is not None

    def _ask(self, what):
        if self._live is None:
            return None
        try:
            return getattr(self._live, what)()
        except Exception as exc:                            # noqa: BLE001
            warn(f"[BROKER_VIEW] Could not read {what} from Dhan: {exc}")
            return None

    def positions(self):
        """Dhan's INTRADAY book, or None if it could not be read."""
        return self._ask("positions")

    def holdings(self):
        """Dhan's DELIVERY/MTF book -- what he is carrying."""
        return self._ask("holdings")

    def broker_book(self):
        """Both halves as one list, or None if either went unanswered."""
        return self._ask("broker_book")
