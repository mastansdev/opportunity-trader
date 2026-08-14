"""
==========================================================
NSE's own numbers -- the reference the bot is judged against
==========================================================

    "NSE & BOT are not synchronised - bot is not following as NSE -
     pls check how nse calculated % moving previous close & today gap
     up/down opening & trading. (do not deviate from NSE)"
                                        -- operator, 2026-07-29

    "change in % of stock raising / falling must follow with NSE -
     Do not invent on our own formulas."
                                        -- operator, 2026-07-28

WHAT THIS IS
------------
A read of NSE's own live quote data, so the bot's numbers can be put
NEXT TO the exchange's and the difference measured rather than argued
about.

It decides nothing and trades nothing. It exists to answer one
question: where, and by how much, does the bot disagree with NSE?

WHY THIS MATTERS MORE THAN IT SOUNDS
------------------------------------
Every other measurement in this system is computed from the bot's own
prices. If the percentage base is wrong then the shortlist ranking is
wrong, the sector heatmap is wrong, and any study of the exit rules is
wrong too -- tuned against a corrupted number, with no way to tell.

The operator put it first for exactly that reason, and he was right.

HOW NSE SERVES THIS
-------------------
One request returns a whole index constituent list with last price,
previous close and NSE's own percentage change already computed:

    /api/equity-stockIndices?index=NIFTY%20TOTAL%20MARKET

Several index lists are read and merged, because no single one covers
the bot's 973-name master.

NSE refuses a bare request. It wants a browser User-Agent AND a cookie
from a prior page visit, so the session hits the home page first. This
is the same handshake core/results_ingest.py already uses successfully
for corporate filings -- copied from there rather than reinvented.

NEVER RAISES. A symbol NSE doesn't return is reported as MISSING and
never guessed, exactly like core/premarket.py. A price comparison built
on a filled-in blank would be worse than no comparison at all.

Author : H&M Opportunity Trader
==========================================================
"""

import json

from core.logger import diagnostic, warn

BASE = "https://www.nseindia.com"

# THE HANDSHAKE TARGET IS NOT THE HOMEPAGE. Measured with
# tools/nse_handshake.py on 30 July 2026, three runs, two header sets:
#
#     GET /                             403, zero or one cookie
#     GET /market-data/live-equity-market   200, _abck + ak_bmsc + bm_sz
#
# NSE sits behind Akamai Bot Manager and the bare homepage is the most
# aggressively defended URL on the site. Every session this bot has ever
# opened started with a 403 it then ignored, which is why no [NSE] line
# has ever appeared in a log.
#
# The market-data page is the page that legitimately calls these APIs,
# so asking for it first is also what a browser actually does.
HOME = BASE + "/market-data/live-equity-market"

# RETIRED, 30 July 2026 -- kept only so the reason is discoverable.
# This endpoint now returns NSE's 382-byte "Resource not found" page for
# every index name and every encoding (%20, +, literal space, no space).
# It is not a block and not an encoding fault: on the SAME session,
# /api/marketStatus and /api/allIndices both returned 200 JSON.
#
# CORRECTION, same day. The line that stood here read "endpoints WITHOUT
# a query parameter answer; endpoints WITH one do not" -- and it was
# wrong. The operator disproved it by running tools/preopen_gaps.py,
# which calls
#
#     /api/market-data-pre-open?key=ALL
#
# a parameterised endpoint, and got 2,007 stocks back. So the rule is
# not about parameters at all. THIS PARTICULAR endpoint is gone;
# nothing general follows from that, and the generalisation would have
# stopped somebody using pre-open data that works perfectly well.
#
# core/index_members.py no longer uses it -- index membership now comes
# from NSE's published CSVs on nsearchives.nseindia.com, which need no
# parameter and no API at all.
INDEX_URL = BASE + "/api/equity-stockIndices?index={index}"

# Parameterless and confirmed working, 30 July 2026. allIndices returns
# every index NSE publishes -- NIFTY 50, NIFTY BANK and INDIA VIX among
# them -- in one 113 KB payload.
#
# NOT a substitute for the Dhan live feed. It is a snapshot from behind a
# bot wall that has already changed behaviour once without notice. Its
# value is as a CROSS-CHECK: it can confirm that a Dhan security id maps
# to the index its tile claims, which is the mistake that put ABB's share
# price in the Nifty tile.
ALL_INDICES_URL = BASE + "/api/allIndices"
MARKET_STATUS_URL = BASE + "/api/marketStatus"

# Merged in this order; the first list to carry a symbol wins. Between
# them these cover the large, mid and small caps the master file holds.
INDEX_LISTS = (
    "NIFTY%20TOTAL%20MARKET",
    "NIFTY%20500",
    "SECURITIES%20IN%20F%26O",
    "NIFTY%20MIDSMALLCAP%20400",
    "NIFTY%20SMALLCAP%20250",
)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/market-data/live-equity-market",
}


def parse_index_payload(payload):
    """One index list -> {SYMBOL: quote}. Never raises.

    NSE's own field names are kept deliberately visible here so anyone
    reading this can check them against the site:

        lastPrice      last traded price
        previousClose  the PRIOR SESSION's close
        pChange        NSE's OWN percentage change
        open           today's open (this is what a gap is measured on)

    pChange is read rather than recomputed. The whole point is to use
    the exchange's arithmetic, not ours.
    """
    out = {}
    try:
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        for row in (payload or {}).get("data") or []:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            try:
                last = float(row.get("lastPrice"))
            except (TypeError, ValueError):
                continue
            if last <= 0:
                continue

            def _num(key):
                try:
                    value = float(row.get(key))
                    return value if value != 0 else None
                except (TypeError, ValueError):
                    return None

            out[symbol] = {
                "symbol": symbol,
                "last": last,
                "prev_close": _num("previousClose"),
                "pct": _num("pChange"),
                "open": _num("open"),
                "high": _num("dayHigh"),
                "low": _num("dayLow"),
            }
    except Exception:                                      # noqa: BLE001
        return out
    return out


def requests_fetcher(timeout=20):
    """Live fetcher with NSE's cookie handshake.

    Injected rather than imported so tests never touch the network and
    a missing library degrades to "no data", not a crash.
    """
    state = {"session": None}

    def _session():
        import requests
        if state["session"] is None:
            session = requests.Session()
            session.headers.update(HEADERS)
            # NSE hands out the cookie the API calls need only after a
            # normal page load. Without this every /api/ call 401s --
            # or, more confusingly, 404s.
            #
            # The failure used to be invisible: a diagnostic() line at
            # DEBUG level, then carry on regardless, so a session with
            # NO cookies made API calls that came back 404 and the 404
            # was reported as if NSE had rejected the URL. Every
            # [INDEX] fetch failure ever logged looked like a bad
            # endpoint. Whether the handshake worked is the first thing
            # anyone needs to know, so it is a WARNING and it says what
            # it means.
            try:
                home = session.get(HOME, timeout=timeout)
                got = list(session.cookies.keys())
                if not got:
                    warn(f"[NSE] Handshake returned {home.status_code} but "
                         f"NO cookies -- every /api/ call after this will "
                         f"fail, and it will look like a 404 on the "
                         f"endpoint. Run py tools/nse_handshake.py to see "
                         f"what NSE is actually returning.")
                else:
                    diagnostic(f"[NSE] Handshake OK "
                               f"({home.status_code}), cookies: "
                               f"{', '.join(got)}.")
            except Exception as exc:                       # noqa: BLE001
                warn(f"[NSE] Handshake on {HOME} FAILED ({exc}) -- the "
                     f"session has no cookies, so every /api/ call will "
                     f"fail for this reason and not because of the URL. "
                     f"Run py tools/nse_handshake.py.")
            state["session"] = session
        return state["session"]

    def _get(url):
        response = _session().get(url, timeout=timeout)
        response.raise_for_status()
        return response.text

    return _get


class NseQuotes:
    """NSE's live numbers for as much of the universe as it will give."""

    def __init__(self, fetcher=None, index_lists=INDEX_LISTS):
        self._fetcher = fetcher
        self.index_lists = tuple(index_lists)
        self.quotes = {}
        self.sources_ok = []
        self.sources_failed = []

    def refresh(self):
        """Read every index list and merge. Returns how many symbols
        were collected. Never raises.

        One dead list does not lose the others -- same posture as
        core/premarket.py.
        """
        if self._fetcher is None:
            warn("[NSE] No fetcher wired -- nothing collected.")
            return 0

        merged = {}
        self.sources_ok, self.sources_failed = [], []
        for index in self.index_lists:
            try:
                rows = parse_index_payload(self._fetcher(
                    INDEX_URL.format(index=index)))
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[NSE] {index}: {exc}")
                self.sources_failed.append(index)
                continue
            if not rows:
                self.sources_failed.append(index)
                continue
            self.sources_ok.append((index, len(rows)))
            for symbol, quote in rows.items():
                merged.setdefault(symbol, quote)

        self.quotes = merged
        if not merged:
            warn("[NSE] No quotes collected from any index list.")
        return len(merged)

    def get(self, symbol):
        """NSE's quote for one symbol, or None. None means MISSING --
        never a guessed number."""
        return self.quotes.get((symbol or "").strip().upper())
