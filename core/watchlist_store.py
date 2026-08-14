"""
==========================================================
The watchlist -- results today, and whatever he adds
==========================================================

    "WATCHLIST = MAINTAIN ONLY STOCKS WHICH WILL GET RESULTS TODAY
     DURING LIVE MARKETS & GIVE ME OPTION TO ADD SOME STOCKS TO
     WATCHLIST TO TRACK IF I WANT. AFTER MARKET STOCK RESULTS + NEXT
     DAY DURING MARKET RESULTS STOCK ON NEXT DAY."
    "LIST AS PER DURING , AFTER & OPTION TO ADD/REMOVE + BUTTONS TO
     BUY/SELL ALONG WITH QTY"
                                    -- operator, 4 August 2026

WHAT WAS WRONG WITH THE OLD ONE
-------------------------------
    "Watchlist = Still mess (bot clubbed all under same roof; why user
     needs to work hard)"

Everything the bot had an opinion about landed in one list -- breakouts,
news mentions, shortlist candidates, results -- so it was long, it was
undifferentiated, and he had to do the sorting himself. A list that
needs sorting before it can be read is not a watchlist.

THREE GROUPS, AND TWO OF THEM MANAGE THEMSELVES
-----------------------------------------------
    DURING    reporting inside market hours today. The tradeable one.
    AFTER     reporting after 15:30 today -- carried to TOMORROW,
              because a company reporting at 17:00 is tomorrow's
              opening move, not today's.
    MINE      what he added. Never touched by the automatic ones.

WHY A THIRD TIME BUCKET EXISTS
------------------------------
core/results_calendar.py learns each company's habit from its own
history and returns a reliability flag with it:

    BASF    14:25   spread 18 min    reliable      -> DURING
    DIXON   16:07   spread 63 min    reliable      -> AFTER
    TITAN   17:07   spread 269 min   NOT reliable  -> UNKNOWN

TITAN has reported anywhere across a four-and-a-half hour window.
Filing it under AFTER would be inventing a certainty the data does not
support, so it goes in UNKNOWN and he decides. A wrong bucket is worse
than an honest one, because he would stop checking.

THIS FILE ONLY STORES HIS CHOICES
---------------------------------
The results groups are computed fresh each session from the calendar --
nothing about them is persisted, so a stale entry cannot survive into a
day it does not belong to. Only add/remove is written down, because
only that is his.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import threading
from datetime import datetime

from core.logger import decision, diagnostic, warn

STORE_PATH = os.path.join("data", "watchlist.json")

# Market hours. A result filed inside these is something he can act on
# today; outside them it is tomorrow's open.
MARKET_OPEN_MINUTES = 9 * 60 + 15        # 09:15
MARKET_CLOSE_MINUTES = 15 * 60 + 30      # 15:30

DURING = "during"
AFTER = "after"
UNKNOWN = "unknown"
MINE = "mine"


def bucket_for(timing):
    """Which group a results timing belongs in.

    `timing` is core/results_calendar.py's typical_time() reply:
        {"minutes": 865, "hhmm": "14:25", "samples": 4,
         "spread_minutes": 18, "reliable": True}

    An unreliable or missing timing returns UNKNOWN. It never guesses
    DURING, because DURING is the group he trades from.
    """
    if not isinstance(timing, dict):
        return UNKNOWN
    if not timing.get("reliable"):
        return UNKNOWN
    minutes = timing.get("minutes")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return UNKNOWN
    if MARKET_OPEN_MINUTES <= minutes <= MARKET_CLOSE_MINUTES:
        return DURING
    return AFTER


class WatchlistStore:
    """His own adds, on disk, one JSON file.

    Never raises. A watchlist that cannot be written must cost him the
    watchlist, never the session.
    """

    def __init__(self, path=STORE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._rows = {}
        self._load()

    # ------------------------------------------------------------

    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return
        except Exception as exc:                           # noqa: BLE001
            warn(f"[WATCHLIST] Could not read {self._path} ({exc}). "
                 f"Starting empty -- your adds are not lost on disk.")
            return
        rows = data.get("rows") if isinstance(data, dict) else data
        if isinstance(rows, dict):
            self._rows = {str(k).upper(): v for k, v in rows.items()}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            # Write beside then replace, so a crash mid-write cannot
            # leave him with half a file and no watchlist.
            temporary = self._path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump({"rows": self._rows}, handle, indent=2)
            os.replace(temporary, self._path)
            return True
        except Exception as exc:                           # noqa: BLE001
            warn(f"[WATCHLIST] Could not save ({exc}). The change is "
                 f"live now but will not survive a restart.")
            return False

    # ------------------------------------------------------------

    def add(self, symbol, note=""):
        symbol = str(symbol or "").upper().strip()
        if not symbol:
            return False
        with self._lock:
            if symbol in self._rows:
                return True                       # already there, not an error
            self._rows[symbol] = {
                "added_at": datetime.now().isoformat(timespec="seconds"),
                "note": str(note or "")[:200],
            }
            self._save()
        decision(f"[WATCHLIST] {symbol} added.")
        return True

    def remove(self, symbol):
        symbol = str(symbol or "").upper().strip()
        with self._lock:
            if symbol not in self._rows:
                return False
            self._rows.pop(symbol, None)
            self._save()
        decision(f"[WATCHLIST] {symbol} removed.")
        return True

    def symbols(self):
        with self._lock:
            return sorted(self._rows)

    def note_for(self, symbol):
        with self._lock:
            return (self._rows.get(str(symbol or "").upper())
                    or {}).get("note") or ""

    def status(self):
        return {"available": True, "path": self._path,
                "count": len(self._rows)}
