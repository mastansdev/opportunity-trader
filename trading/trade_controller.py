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
        # symbol -> shares, for requests that name a size. Absent means
        # "the whole position" on an exit and "the standard Rs 1 lakh
        # size" on an entry -- which is what every caller meant before
        # a size could be named at all. See _remember_qty() below.
        self._exit_qty = {}
        self._buy_qty = {}
        self._short_qty = {}
        self._entries_paused = False

        # ACTION LOG, 2026-07-28. Every click, sent or failed, held
        # SERVER-side.
        #
        # It lived in the browser first. The operator refreshed the page
        # and the record vanished -- and he runs two or three screens,
        # so a log only the clicking screen can see is not a record at
        # all. He could click on one monitor, watch another, and never
        # learn the click died.
        #
        # That matters because this IS the safety feature: on
        # 2026-07-28 two BUY clicks were eaten by the 1-second panel
        # rebuild, silently, and the second SUPREMEIND click filled
        # Rs 87 higher. A row that survives a refresh, and appears on
        # every screen, is the difference between noticing and not.
        import threading as _threading
        self._action_log = []
        self._action_lock = _threading.Lock()

    # --------------------------------------------------
    # ACTION LOG
    # --------------------------------------------------

    MAX_ACTIONS = 40

    def note_action(self, ok, text, at=None):
        """Record one click. Never raises -- bookkeeping must not be
        able to break a trade request.

        `at` overrides the clock. Only core/session_replay.py passes
        it, so a replayed session shows the time an order actually
        went out rather than the time the replay was run -- a log
        stamped 22:15 for a 09:31 order would be worse than no log.
        """
        try:
            from datetime import datetime
            with self._action_lock:
                self._action_log.insert(0, {
                    "at": at or datetime.now().strftime("%H:%M:%S"),
                    "ok": bool(ok),
                    "text": str(text)[:160],
                })
                del self._action_log[self.MAX_ACTIONS:]
        except Exception:                                  # noqa: BLE001
            pass

    def actions(self):
        with self._action_lock:
            return list(self._action_log)

    # --------------------------------------------------

    def request_exit_all(self):
        self._exit_all = True

    def is_exit_all_requested(self):
        return self._exit_all

    def clear_exit_all(self):
        self._exit_all = False

    # --------------------------------------------------

    # ---- HOW MANY, NOT JUST WHICH. 2 August 2026. ----
    #
    #     "yes pls complete now."
    #
    # Every request here used to be a bare symbol in a set, so every
    # buy was exactly the Rs 1 lakh margin rule and every sell was the
    # WHOLE position. That second one contradicted his own method:
    #
    #     "ride untill the momentum stays - exit once it gone
    #      ruthlessly"
    #
    # Riding a move usually means trimming into strength, and the
    # dashboard could only ever sell all of it.
    #
    # The quantity is held BESIDE the set rather than replacing it, so
    # every existing caller -- request_exit("TCS"), is_exit_requested,
    # the exit-all batch -- behaves exactly as before. None still means
    # "all of it" / "the standard size", which is what every one of
    # those callers has always meant.
    def _remember_qty(self, store, symbol, qty):
        if qty is None:
            store.pop(symbol, None)
            return
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            store.pop(symbol, None)
            return
        if qty > 0:
            store[symbol] = qty
        else:
            store.pop(symbol, None)

    def request_exit(self, symbol, qty=None):
        self._remember_qty(self._exit_qty, symbol, qty)
        self._exit_symbols.add(symbol)

    def exit_qty(self, symbol):
        """Shares to close, or None for the whole position."""
        return self._exit_qty.get(symbol)

    def buy_qty(self, symbol):
        """Shares to buy, or None for the standard Rs 1 lakh size."""
        return self._buy_qty.get(symbol)

    def short_qty(self, symbol):
        return self._short_qty.get(symbol)

    def is_exit_requested(self, symbol):
        return symbol in self._exit_symbols

    def clear_exit(self, symbol):
        self._exit_symbols.discard(symbol)
        self._exit_qty.pop(symbol, None)

    def get_exit_requested_symbols(self):
        """Copy of every symbol with a pending individual EXIT
        request right now -- lets the engine act on the whole
        pending set in one pass instead of one symbol at a time."""
        return set(self._exit_symbols)

    # --------------------------------------------------

    def request_buy(self, symbol, qty=None):
        self._remember_qty(self._buy_qty, symbol, qty)
        self._buy_symbols.add(symbol)

    def is_buy_requested(self, symbol):
        return symbol in self._buy_symbols

    def clear_buy(self, symbol):
        self._buy_symbols.discard(symbol)
        self._buy_qty.pop(symbol, None)

    # --------------------------------------------------

    def request_short(self, symbol, qty=None):
        self._remember_qty(self._short_qty, symbol, qty)
        self._short_symbols.add(symbol)

    def is_short_requested(self, symbol):
        return symbol in self._short_symbols

    def clear_short(self, symbol):
        self._short_qty.pop(symbol, None)
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
        except OSError as exc:
            # Control flow is UNCHANGED -- bookkeeping must never break
            # trading control, and the in-memory pause is already set.
            # But it is now reported, because the flag is what survives a
            # restart: if it cannot be written, "Stop New Entries" holds
            # for this process and is silently forgotten by the next one.
            # The operator would restart believing entries were still off.
            #
            # Imported HERE, not at module scope. This file deliberately
            # depends on nothing but `os` -- it sits in the trading
            # control path and a module-level import of core.logger would
            # add an import cycle risk for a message that only ever fires
            # on a disk fault. The file already uses local imports for
            # threading and datetime, so this matches its own idiom.
            try:
                from core.logger import warn
                warn(f"[CONTROL] Could not persist the pause flag "
                     f"({self.PAUSE_FLAG_PATH}): {exc}. Entries are paused "
                     f"for THIS process only -- a restart will come back "
                     f"with entries LIVE.")
            except Exception:                              # noqa: BLE001
                pass

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
