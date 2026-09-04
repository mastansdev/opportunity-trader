"""
Paper fills. Equity only -- no segment parameter exists anywhere in this
bot, so there is no way to accidentally route an order to F&O.

2026-07-28: fills are no longer at the exact intent price. This module
used to log a line and return success, filling perfectly every time --
no spread, no partial fill, no rejection. Six months of paper results
were built on that, and paper results are the yardstick every rule here
is measured against.

A buy now lifts the offer and a sell hits the bid, sized by the symbol's
own liquidity and the time of day (see trading/slippage.py). Both the
intent price and the fill price are logged, so the gap is visible rather
than assumed -- and so the estimate can be replaced with the operator's
real fills once live orders start on 30 July.
"""

from core.logger import decision
from trading.slippage import BUY, SELL, fill_price, slippage_cost
from core.fill_log import FillLog
from trading.trade_logger import log_trade


class PaperExecution:

    def __init__(self, turnover_lookup=None, fill_log=None,
                 range_lookup=None):
        # turnover_lookup(symbol) -> day turnover in crores, or None.
        # Injected rather than imported so this module stays testable
        # and so a missing lookup degrades to "assume thin" (the
        # expensive assumption, which is the safe one) instead of
        # crashing an order.
        self._turnover_lookup = turnover_lookup
        # range_lookup(symbol) -> (day_low, day_high), or None. Injected
        # for the same reason turnover_lookup is: this module must not
        # reach into a live store, and a test must be able to hand it
        # any range it likes. Without it the fill is uncapped, exactly
        # as before -- see fill_price().
        self._range_lookup = range_lookup
        # Every fill is kept. Injected so tests get their own file.
        self._fills = fill_log if fill_log is not None else FillLog()

    def _turnover(self, symbol):
        if self._turnover_lookup is None:
            return None
        try:
            return self._turnover_lookup(symbol)
        except Exception:                                  # noqa: BLE001
            return None

    def _range(self, symbol):
        """(low, high) for today, or (None, None). Never raises."""
        if self._range_lookup is None:
            return None, None
        try:
            got = self._range_lookup(symbol) or {}
            if isinstance(got, dict):
                return got.get("low"), got.get("high")
            return got[0], got[1]
        except Exception:                                  # noqa: BLE001
            return None, None

    def _execute(self, side, security_id, symbol, price, qty, reason,
                 at_time=None):
        low, high = self._range(symbol)
        filled = fill_price(price, side, self._turnover(symbol), at_time,
                            day_high=high, day_low=low)
        cost = slippage_cost(price, filled, qty, side)

        # The TRADE LOG records the price actually paid, not the price
        # wanted -- otherwise the P&L is a fiction and the whole point
        # of modelling slippage is lost.
        log_trade(side, symbol, security_id, qty, filled, reason)

        suffix = f" ({reason})" if reason else ""
        slip = ""
        if cost > 0:
            slip = (f"  [wanted {price:.2f}, slipped "
                    f"{abs(filled - price):.2f} = Rs {cost:,.0f}]")
        decision(
            f"PAPER {side:<4} {symbol:<10} qty={qty} @ {filled:.2f}"
            f"{suffix}{slip}"
        )
        # Recorded so a modelled cost can later be compared against
        # the real ones, side by side but never in the same column.
        self._fills.record("PAPER", side, symbol, security_id, qty,
                           price, filled, reason=reason,
                           order_id=f"PAPER_{symbol}",
                           turnover_cr=self._turnover(symbol), at=at_time)
        return {
            "success": True,
            "order_id": f"PAPER_{symbol}",
            "price": filled,
            "intent_price": price,
            "slippage_rs": round(cost, 2),
        }

    def buy(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self._execute(BUY, security_id, symbol, price, qty, reason,
                             at_time)

    def sell(self, security_id, symbol, price, qty, reason="", at_time=None):
        return self._execute(SELL, security_id, symbol, price, qty, reason,
                             at_time)
