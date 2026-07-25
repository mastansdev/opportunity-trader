"""
Paper fills, instantly, at intent price. Equity only -- no
segment parameter exists anywhere in this bot, so there is
no way to accidentally route an order to F&O.
"""

from core.logger import decision
from trading.trade_logger import log_trade


class PaperExecution:

    def buy(self, security_id, symbol, price, qty, reason=""):
        log_trade("BUY", symbol, security_id, qty, price, reason)
        suffix = f" ({reason})" if reason else ""
        decision(
            f"PAPER BUY  {symbol:<10} qty={qty} @ {price:.2f}{suffix}"
        )
        return {"success": True, "order_id": f"PAPER_{symbol}"}

    def sell(self, security_id, symbol, price, qty, reason=""):
        log_trade("SELL", symbol, security_id, qty, price, reason)
        suffix = f" ({reason})" if reason else ""
        decision(
            f"PAPER SELL {symbol:<10} qty={qty} @ {price:.2f}{suffix}"
        )
        return {"success": True, "order_id": f"PAPER_{symbol}"}
