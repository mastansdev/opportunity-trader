"""
Manual override control. Structural breakouts (core/strategy.py)
still fire on their own -- this is for OPERATOR-initiated
actions on top of that: manual exit (console, or now the
dashboard's SELL button) and manual buy (dashboard's BUY
button -- see core/engine.py's docstring for why that's a
deliberate, scoped addition, not the strategy silently
changing).

Requests are just flags/sets here -- thread-safe by
construction (GIL-protected set/bool ops), no lock needed.
The actual action happens on the engine's own tick thread,
picked up in Engine.process_tick, using whatever price that
next real tick brings -- never a price the requester invented.
"""


class TradeController:

    def __init__(self):
        self._exit_all = False
        self._exit_symbols = set()
        self._buy_symbols = set()

    # --------------------------------------------------

    def request_exit_all(self):
        self._exit_all = True

    def is_exit_all_requested(self):
        return self._exit_all

    def clear_exit_all(self):
        self._exit_all = False

    # --------------------------------------------------

    def request_exit(self, symbol):
        self._exit_symbols.add(symbol)

    def is_exit_requested(self, symbol):
        return symbol in self._exit_symbols

    def clear_exit(self, symbol):
        self._exit_symbols.discard(symbol)

    # --------------------------------------------------

    def request_buy(self, symbol):
        self._buy_symbols.add(symbol)

    def is_buy_requested(self, symbol):
        return symbol in self._buy_symbols

    def clear_buy(self, symbol):
        self._buy_symbols.discard(symbol)
