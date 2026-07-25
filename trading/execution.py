"""
Single gateway all buy/sell requests pass through. The
Engine never knows whether it's PAPER or LIVE. LIVE mode
is not implemented yet in Layer 1 -- placing that requires
its own reviewed, tested module, not a quiet stub.
"""

from config import TRADING_MODE
from trading.paper_execution import PaperExecution


class Execution:

    def __init__(self):
        if TRADING_MODE.upper() == "LIVE":
            raise NotImplementedError(
                "LIVE execution is not built yet in Opportunity "
                "Trader. Stay on PAPER until it's deliberately "
                "added and reviewed -- this is not an oversight."
            )

        self.executor = PaperExecution()
        self.mode = "PAPER"

    def buy(self, security_id, symbol, price, qty, reason=""):
        return self.executor.buy(security_id, symbol, price, qty, reason)

    def sell(self, security_id, symbol, price, qty, reason=""):
        return self.executor.sell(security_id, symbol, price, qty, reason)
