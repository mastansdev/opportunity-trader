"""
Manual override control. Structural breakouts (core/strategy.py)
still fire on their own -- this is for OPERATOR-initiated
actions on top of that: manual exit (console, or now the
dashboard's SELL button), manual buy (dashboard's BUY button,
per-row on the Top 50 Gainers table), and manual short (dashboard's
SHORT button, per-row on the Top 50 Losers table, added 2026-07-23
evening -- operator's own trading philosophy is to enter the day's
top gainers/losers directly, in either direction, for PAPER-mode
testing -- see core/engine.py's docstring for why that's a
deliberate, scoped addition, not the strategy silently changing).

Requests are just flags/sets here -- thread-safe by
construction (GIL-protected set/bool ops), no lock needed.
The actual action happens on the engine's own tick thread,
picked up in Engine.process_tick, using whatever price that
next real tick brings -- never a price the requester invented.

EXIT and EXIT ALL requests are the one exception to "next real
tick" above -- see core/engine.py's _process_pending_manual_exits()
docstring (added 2026-07-23 night, operator report: "some stocks
exited, then silently stopped exiting" -- a quiet, thinly-ticking
symbol could sit mid-batch for minutes with zero feedback). Those
now act immediately off market_data's last known price the moment
ANY tick arrives, not specifically a tick for that exact symbol --
get_exit_requested_symbols() below is what lets the engine scan the
whole pending set at once instead of checking one symbol at a time.

2026-07-24: EXIT ALL's dashboard button became a popup with two
distinct choices, operator's own request -- "a popup or box showing
Stop new entries button & exit all and only exit all, new entries
will resume after all open positions will exit":
  - "Stop New Entries + Exit All": request_pause_new_entries() AND
    request_exit_all() together. Automated (structural) entries are
    gated off (core/engine.py's _try_structural_entry()) until the
    book is genuinely flat again, at which point the engine itself
    calls resume_new_entries() -- no operator action needed to turn
    entries back on. Manual buy/short are NOT gated by the pause,
    same "explicit operator override" reasoning already applied to
    the news/sector blocks.
  - "Exit All only": request_exit_all() alone, exactly the original
    single-click behaviour -- the bot keeps trading normally
    throughout the flush.
"""

import os


class TradeController:

    def __init__(self):
        self._exit_all = False
        self._exit_symbols = set()
        self._buy_symbols = set()
        self._short_symbols = set()
        self._entries_paused = False

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

    def get_exit_requested_symbols(self):
        """Copy of every symbol with a pending individual EXIT
        request right now -- lets the engine act on the whole
        pending set in one pass instead of one symbol at a time."""
        return set(self._exit_symbols)

    # --------------------------------------------------

    def request_buy(self, symbol):
        self._buy_symbols.add(symbol)

    def is_buy_requested(self, symbol):
        return symbol in self._buy_symbols

    def clear_buy(self, symbol):
        self._buy_symbols.discard(symbol)

    # --------------------------------------------------

    def request_short(self, symbol):
        self._short_symbols.add(symbol)

    def is_short_requested(self, symbol):
        return symbol in self._short_symbols

    def clear_short(self, symbol):
        self._short_symbols.discard(symbol)

    # --------------------------------------------------

    # The pause flag is PERSISTED (2026-07-25). It is a deliberate
    # operator decision -- "stop trading" -- and a restart (crash, feed
    # drop, code change) must not silently undo it. A file is used
    # rather than session_state.json because that file's load() returns
    # a fixed-shape tuple every caller unpacks; a separate flag keeps
    # this independent and impossible to break by accident. Presence of
    # the file = paused. All I/O is best-effort: if it fails, the flag
    # still works in memory for this session.
    PAUSE_FLAG_PATH = os.path.join("data", "entries_paused.flag")

    def _write_pause_flag(self, paused):
        try:
            if paused:
                directory = os.path.dirname(self.PAUSE_FLAG_PATH)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(self.PAUSE_FLAG_PATH, "w", encoding="utf-8") as f:
                    f.write("paused\n")
            elif os.path.exists(self.PAUSE_FLAG_PATH):
                os.remove(self.PAUSE_FLAG_PATH)
        except OSError:
            pass          # never let bookkeeping break trading control

    def restore_pause_state(self):
        """Called once at startup. Re-arms the pause if the operator
        left entries stopped when the process last ended."""
        try:
            if os.path.exists(self.PAUSE_FLAG_PATH):
                self._entries_paused = True
                return True
        except OSError:
            pass
        return False

    def request_pause_new_entries(self):
        """EXIT ALL popup's "Stop New Entries + Exit All" option --
        gates off automated (structural) entries in
        core/engine.py's _try_structural_entry() until the operator
        explicitly clicks Resume. Persisted across restarts."""
        self._entries_paused = True
        self._write_pause_flag(True)

    def is_new_entries_paused(self):
        return self._entries_paused

    def resume_new_entries(self):
        self._entries_paused = False
        self._write_pause_flag(False)
