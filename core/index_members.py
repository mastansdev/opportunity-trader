"""
==========================================================
Which stocks are in NIFTY 50, and which are in F&O
==========================================================

    "i'll check with NSE pre-open page which have NIFTY50, ALL NIFTY,
     FNO STOCKS, & Some others... i'll check these NIFTY50, ALL NIFTY,
     FNO STOCKS for top gainers/loosers both in pre-open markets
     sessions"                      -- operator, 29 July 2026

That is the 09:00-09:12 routine this dashboard is meant to replace.
The pre-open panel drew the group buttons on 29 July and clicking one
redrew the identical list, because nothing in the bot knew which stock
belonged to which index. A button that pretends to filter is worse
than no button at all -- it would have been trusted at 09:05.

WHAT THIS IS
------------
Membership only. Which symbols are in NIFTY 50, which have F&O
contracts. No prices, no ranking, no opinion -- core/nse_quotes.py
already fetches quotes and this deliberately does not duplicate it.

CACHED ON DISK, because membership changes a few times a YEAR while
the pre-open window is twelve minutes long. Fetching this at 09:00
would spend the scarcest minutes of the day on an answer that was
already true last week. A stale-but-present list beats a fresh-but-
missing one every time here: the cost of a slightly out-of-date NIFTY
50 is one stock in the wrong tab, and the cost of a failed fetch at
09:03 is the whole panel.

Every failure is survivable and returns an EMPTY set, never a wrong
one -- and dashboard/state.py hides a group whose membership is
unknown rather than showing it filled with the wrong stocks.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import io
import json
import os
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn
from core.nse_quotes import requests_fetcher

CACHE_PATH = os.path.join("data", "index_members.json")

# WHERE THIS COMES FROM, AND WHY IT CHANGED, 30 July 2026
# -------------------------------------------------------
# It used to call /api/equity-stockIndices?index=NIFTY%2050. That
# endpoint now returns NSE's 382-byte "Resource not found" page, and it
# always had -- there is no [INDEX] success in any log this project has
# ever written, and data/index_members.json on disk read {"members": {}}.
#
# tools/nse_handshake.py established what was actually happening, over
# three runs and two header sets:
#
#     /api/marketStatus                      200  JSON
#     /api/allIndices                        200  JSON, 113 KB
#     /api/equity-stockIndices?index=...     404  382 bytes
#     /api/equity-meta-info?symbol=INFY      404  382 bytes
#
# Parameterless endpoints answer; parameterised ones do not. It is not a
# bot block (JSON came back on the same session) and not an encoding
# fault (%20, +, a literal space and no space all 404).
#
# So this reads NSE's PUBLISHED CSVs instead. They are the source the API
# was a view onto, they take no query parameter, and core/results_ingest.py
# already fetches from this host. Confirmed live, same session:
#
#     ind_nifty50list.csv    200   51 lines
#     ind_nifty500list.csv   200  501 lines
#     fo_mktlots.csv         200  215 lines
ARCHIVE = "https://nsearchives.nseindia.com"

# The two the operator actually names. "All NIFTY" is every symbol NSE
# publishes a pre-open book for, which needs no membership list at all
# -- it is simply everything, and is handled without a fetch.
#
# `column` is the CSV column holding the ticker. fo_mktlots.csv pads its
# headers with spaces ("UNDERLYING                          ,SYMBOL    ,")
# so the match is on the STRIPPED, upper-cased name.
GROUPS = {
    "nifty50": {
        "url": ARCHIVE + "/content/indices/ind_nifty50list.csv",
        "column": "SYMBOL",
    },
    "fno": {
        "url": ARCHIVE + "/content/fo/fo_mktlots.csv",
        "column": "SYMBOL",
    },
}

# fo_mktlots.csv lists INDEX derivatives alongside single stocks. The
# operator asked for "FNO STOCKS", and an index in a stock filter would
# match nothing in the pre-open book and look like a bug.
INDEX_UNDERLYINGS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
    "NIFTYIT", "NIFTYINFRA", "NIFTYPSE", "NIFTYMIDSELECT", "SENSEX",
    "BANKEX", "INDIAVIX",
}

# Membership changes at index review, roughly twice a year. A week is
# already far more often than it needs to be.
MAX_AGE_DAYS = 7


def symbols_from_payload(payload):
    """Just the constituent tickers. Never raises.

    Deliberately NOT core/nse_quotes.py's parse_index_payload(), which
    is a QUOTE parser: it drops any row whose lastPrice is missing or
    zero. That is right for quotes and wrong here -- a stock halted or
    suspended on the day of the fetch would silently disappear from
    the NIFTY 50 and stay missing for a week. Membership is a question
    about the index, not about today's trading.

    NSE returns the index itself as the first row ("NIFTY 50",
    "NIFTY BANK"). Real tickers never contain a space, which is a
    cheaper and more reliable filter than matching the index name.
    """
    out = set()
    try:
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        for row in (payload or {}).get("data") or []:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol or " " in symbol:
                continue
            out.add(symbol)
    except Exception:                                      # noqa: BLE001
        return out
    return out


def symbols_from_csv(text, column="SYMBOL", drop_indices=True):
    """Constituent tickers out of one of NSE's published CSVs.

    Never raises -- a malformed file returns an empty set, and the caller
    keeps whatever was already on disk.

    Handles what the real files actually contain:

      PADDED HEADERS. fo_mktlots.csv's header line is
      "UNDERLYING                          ,SYMBOL    ,AUG-26     ,..."
      so both the header names and the values need stripping. Matching on
      the raw name finds nothing.

      SECTION ROWS AND FOOTNOTES. The lot-size file carries section
      headings and a trailing note. A real ticker has no spaces, so that
      is the filter -- the same test the old JSON parser used, and for the
      same reason.

      INDEX UNDERLYINGS. Kept out by default; see INDEX_UNDERLYINGS.

    Deliberately does NOT drop a row for missing price data, because
    membership is a question about the index and not about today's
    trading. A halted stock is still in the NIFTY 50.
    """
    out = set()
    if not text:
        return out
    try:
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        wanted = str(column).strip().upper()
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return out
        header = [str(h or "").strip().upper() for h in rows[0]]
        if wanted not in header:
            diagnostic(f"[INDEX] CSV has no {wanted!r} column "
                       f"(found {header[:6]}).")
            return out
        position = header.index(wanted)
        for row in rows[1:]:
            if len(row) <= position:
                continue
            symbol = str(row[position] or "").strip().upper()
            if not symbol or " " in symbol:
                continue
            # A REPEATED HEADER ROW. fo_mktlots.csv restates its column
            # names partway down the file, so the literal string "SYMBOL"
            # was collected as a ticker and rode all the way into the F&O
            # membership list -- 209 symbols where there are 208. It
            # passed every other filter: no spaces, not an index, plain
            # alphanumeric. Only a cross-check against the master file
            # exposed it, so it is excluded by name here.
            if symbol == wanted or symbol in header:
                continue
            if drop_indices and symbol in INDEX_UNDERLYINGS:
                continue
            out.add(symbol)
    except Exception:                                      # noqa: BLE001
        return out
    return out


class IndexMembers:
    """Which symbols are in which index. Cached, fail-empty."""

    def __init__(self, fetcher=None, cache_path=CACHE_PATH,
                 groups=None, max_age_days=MAX_AGE_DAYS):
        self.fetcher = fetcher
        self.cache_path = cache_path
        self.groups = dict(groups or GROUPS)
        self.max_age_days = max_age_days
        self._members = {}
        self._fetched_at = None
        self._load()

    # ------------------------------------------------------------

    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        self._fetched_at = data.get("fetched_at")
        self._members = {
            key: set(symbols or [])
            for key, symbols in (data.get("members") or {}).items()
        }

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump({
                    "fetched_at": self._fetched_at,
                    "members": {k: sorted(v) for k, v in self._members.items()},
                }, fh, indent=1)
        except OSError as exc:
            warn(f"[INDEX] Could not save {self.cache_path}: {exc}")

    # ------------------------------------------------------------

    def is_stale(self):
        """True if the cache is missing or older than max_age_days."""
        if not self._members or not self._fetched_at:
            return True
        try:
            age = datetime.now() - datetime.strptime(
                self._fetched_at, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return True
        return age > timedelta(days=self.max_age_days)

    def refresh(self, force=False):
        """Fetch membership from NSE. Returns True if anything changed.

        Never raises and never empties a good cache: if a fetch fails,
        the list already on disk is kept. Yesterday's NIFTY 50 is
        almost certainly still correct; an empty one is not.
        """
        if not force and not self.is_stale():
            diagnostic("[INDEX] Membership is current -- not re-fetching.")
            return False

        fetcher = self.fetcher or requests_fetcher()
        changed = False
        for key, source in self.groups.items():
            # A group is {"url":..., "column":...}. A plain string is
            # accepted so a caller can still pass just a URL.
            if isinstance(source, str):
                source = {"url": source, "column": "SYMBOL"}
            try:
                payload = fetcher(source["url"])
                symbols = symbols_from_csv(
                    payload, column=source.get("column", "SYMBOL"))
            except Exception as exc:                       # noqa: BLE001
                warn(f"[INDEX] {key} fetch failed ({exc}) -- keeping the "
                     f"{len(self._members.get(key) or [])} symbols already "
                     f"on disk.")
                continue
            if not symbols:
                warn(f"[INDEX] {key} came back empty -- keeping what we had.")
                continue
            if symbols != self._members.get(key):
                self._members[key] = symbols
                changed = True
            decision(f"[INDEX] {key}: {len(symbols)} symbols.")

        if changed or self._fetched_at is None:
            self._fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save()
        return changed

    # ------------------------------------------------------------

    def members(self, group):
        """The symbols in one group, or an empty set if unknown.

        Empty means UNKNOWN, and the caller must treat it that way --
        showing an unfiltered list under a NIFTY 50 heading is the
        exact lie this module exists to prevent.
        """
        return set(self._members.get(group) or ())

    def known_groups(self):
        """Only the groups we actually have membership for."""
        return {key for key, symbols in self._members.items() if symbols}

    def contains(self, group, symbol):
        return str(symbol).strip().upper() in self.members(group)

    def status(self):
        return {
            "fetched_at": self._fetched_at,
            "stale": self.is_stale(),
            "counts": {k: len(v) for k, v in self._members.items() if v},
        }
