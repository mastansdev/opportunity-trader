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

from config import TRADING_MODE, I_UNDERSTAND_THIS_PLACES_REAL_ORDERS
from core.logger import warn
from trading.paper_execution import PaperExecution


class Execution:

    def __init__(self, turnover_lookup=None, dhan_client=None,
                 price_lookup=None, open_position_count=None):
        if TRADING_MODE.upper() == "LIVE":
            if not I_UNDERSTAND_THIS_PLACES_REAL_ORDERS:
                raise RuntimeError(
                    "TRADING_MODE is LIVE but "
                    "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS is False. Both "
                    "are required. Refusing to start rather than quietly "
                    "paper-trading a session you believe is real."
                )
            if dhan_client is None:
                raise RuntimeError(
                    "TRADING_MODE is LIVE but no Dhan client was provided. "
                    "Refusing to start -- a bot you believe is live and "
                    "which is only pretending is the worse failure."
                )
            from trading.live_execution import LiveExecution
            self.executor = LiveExecution(
                dhan_client, price_lookup=price_lookup,
                open_position_count=open_position_count)
            self.mode = "LIVE"
            warn("=" * 62)
            warn("  LIVE TRADING. Orders placed from here are REAL.")
            warn("  MARKET orders, MTF product. A market order cannot be")
            warn("  cancelled once it fills.")
            warn("=" * 62)
        else:
            self.executor = PaperExecution(turnover_lookup=turnover_lookup)
            self.mode = "PAPER"

    def buy(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self.executor.buy(security_id, symbol, price, qty, reason,
                                 at_time)

    def sell(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self.executor.sell(security_id, symbol, price, qty, reason,
                                  at_time)
