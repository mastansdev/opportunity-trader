"""
==========================================================
Pre-market picture -- what happened while India slept
==========================================================

    "why can't we use bot for collecting the information from every
     source & store them into memory? in this era of AI! again why
     human needs to manual check?"
                                        -- operator, 2026-07-28

He was right, and the honest answer was: nobody built it. Not that it
could not be built.

WHAT THIS IS
------------
COLLECTION AND STORAGE ONLY. It fetches the overnight numbers, writes
them to data/premarket.db, and puts them on the screen. It does NOT say
what they mean.

That line is deliberate and it is the whole design. The operator's own
workflow chart draws the chain:

    crude up -> inflation up -> RBI may hike -> banks benefit,
    real estate hurt -> Nifty moves

Every arrow in that chain is obvious backwards and unreliable forwards.
Crude has risen plenty of times and banks fell anyway. A bot that
announces "IT should lead today because the Nasdaq rose" would be
confidently wrong often enough to cost money, and there would be no way
to separate the good calls from the bad.

So: facts on the screen, and the operator reads them. An AI briefing on
top of this is the NEXT piece, and when it comes it will be marked as
opinion and RECORDED, so in a month we can check whether its calls were
worth anything -- the same discipline the reason gate is held to.

WHAT IT COLLECTS
----------------
    US        S&P 500, Nasdaq, Dow, Russell 2000  (previous close)
    RATES     US 10-year yield, 2-year, Dollar Index
    ENERGY    crude, natural gas
    METALS    gold, silver, copper, aluminium
    ASIA      Nikkei, Hang Seng, Shanghai, Kospi   (live at 06:00 IST)
    FX        USDINR, EURUSD, USDJPY

Everything is a spot quote plus its own % change. No derived numbers, no
interpretation, nothing invented.

WHY YAHOO'S CHART ENDPOINT
--------------------------
Free, no API key, JSON, and it carries the previous close in the same
response -- so the % change is Yahoo's own arithmetic rather than mine.

Stooq was tried first, on 2026-07-28, and every quote URL returned 404
across six variants. Not a symbol problem: the endpoint is gone. The one
URL that answered served an HTML consent page. Recorded here so nobody
tries it again.

Yahoo's v7/quote endpoint returns 401 Unauthorized without a session
cookie. v8/chart does not. Use chart.

NEVER RAISES, and a missing number is reported as MISSING rather than
guessed. A pre-market panel that quietly shows yesterday's crude price
is worse than one that says "could not fetch".

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import threading
import time
from datetime import datetime

from core.logger import decision, diagnostic, warn

STORE_PATH = os.path.join("data", "premarket.json")

YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
             "?range=2d&interval=1d")

# (key, yahoo symbol, human label, group)
SOURCES = (
    ("sp500",      "^GSPC",    "S&P 500",          "US"),
    ("nasdaq",     "^IXIC",    "Nasdaq",           "US"),
    ("dow",        "^DJI",     "Dow Jones",        "US"),
    ("russell",    "^RUT",     "Russell 2000",     "US"),

    ("us10y",      "^TNX",     "US 10Y yield",     "RATES"),
    ("us2y",       "^FVX",     "US 5Y yield",      "RATES"),
    ("dxy",        "DX-Y.NYB", "Dollar index",     "RATES"),

    ("crude",      "CL=F",     "Crude oil",        "ENERGY"),
    ("natgas",     "NG=F",     "Natural gas",      "ENERGY"),

    ("gold",       "GC=F",     "Gold",             "METALS"),
    ("silver",     "SI=F",     "Silver",           "METALS"),
    ("copper",     "HG=F",     "Copper",           "METALS"),

    # ---- EUROPE. 4 August 2026, operator's request. ----
    #
    # They open at 12:30 IST and run through most of his session, so
    # unlike the US numbers these are not overnight history -- they are
    # live context while he holds a position.
    #
    # GIFT NIFTY IS DELIBERATELY NOT HERE. It is the number he asked
    # for and the one that matters most for an Indian open, but Yahoo
    # carries no dependable feed for it -- ^NSEI is Nifty SPOT, which
    # before 09:15 is simply yesterday's close wearing a live label.
    # Putting that on the screen as a leading indicator would be a
    # fabricated number, which is worse than a missing one. It needs a
    # real source (NSE IX / Bloomberg) checked first.
    ("ftse",       "^FTSE",    "FTSE 100",         "EUROPE"),
    ("dax",        "^GDAXI",   "DAX",              "EUROPE"),
    ("stoxx",      "^STOXX50E", "Euro Stoxx 50",   "EUROPE"),

    ("nikkei",     "^N225",    "Nikkei",           "ASIA"),
    ("hangseng",   "^HSI",     "Hang Seng",        "ASIA"),
    ("shanghai",   "000001.SS", "Shanghai",        "ASIA"),

    ("usdinr",     "INR=X",    "USD / INR",        "FX"),
    ("eurusd",     "EURUSD=X", "EUR / USD",        "FX"),
    ("usdjpy",     "JPY=X",    "USD / JPY",        "FX"),
)

MISSING = "MISSING"

# Yahoo throttles a burst. Eighteen requests with no pause is what lost
# the whole overnight picture on 3 August, so they are spaced and each
# one gets three attempts with a widening gap. Worst case this adds
# about a minute to a job that runs once, before the market opens.
REQUEST_GAP_SECONDS = 0.4
RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5


def parse_yahoo(payload):
    """One quote out of Yahoo's chart JSON. None when it cannot be
    trusted.

    Yahoo returns null for a market that has not opened, and an error
    object for an unknown symbol. Both must read as MISSING, never as
    zero -- a pre-market panel showing crude at 0.00 is worse than one
    saying "could not fetch", because zero looks like data.

    The % change uses Yahoo's OWN previous close rather than anything
    derived here, so it matches what every other site shows.
    """
    try:
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        results = ((payload or {}).get("chart") or {}).get("result")
        if not results:
            return None
        meta = results[0].get("meta") or {}
        last = meta.get("regularMarketPrice")
        if last is None:
            last = meta.get("previousClose")
        if last is None:
            return None
        last = float(last)
        if last <= 0:
            return None
        out = {"last": round(last, 4),
               "currency": meta.get("currency"),
               "market_state": meta.get("marketState")}
        # previousClose is the PRIOR SESSION's close. chartPreviousClose
        # is the close before the requested RANGE began -- with range=5d
        # that is six sessions back, and using it reported crude at
        # -10.65% and the Nikkei at -7.13% "overnight" on 2026-07-28.
        # Neither happened. Prefer previousClose, always.
        previous = (meta.get("previousClose")
                    or meta.get("chartPreviousClose"))
        try:
            previous = float(previous)
            if previous > 0:
                out["change_pct"] = round((last - previous) / previous * 100, 2)
                out["previous"] = round(previous, 4)
        except (TypeError, ValueError):
            pass
        return out
    except Exception:                                      # noqa: BLE001
        return None


def requests_fetcher(timeout=10):
    """Live fetcher. Injected rather than imported so tests never touch
    the network and a missing library degrades to MISSING, not a crash.

    A browser User-Agent is required -- Yahoo refuses the default
    requests one.
    """
    from urllib.parse import quote

    def _get(symbol):
        import requests
        url = YAHOO_URL.format(symbol=quote(symbol, safe=""))
        response = requests.get(
            url, timeout=timeout,
            headers={"User-Agent":
                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        response.raise_for_status()
        return response.text

    # The flag refresh() looks for before pausing between requests. Only
    # the live fetcher is throttled; a test double runs at full speed.
    _get.throttle = True
    return _get


class PreMarket:
    """Overnight numbers, fetched once and cached to disk.

    Cached because a restart at 09:10 must not mean eighteen fresh HTTP
    requests before the feed can start -- and because these are closing
    prices, which do not change.
    """

    def __init__(self, fetcher=None, store_path=STORE_PATH):
        self._fetcher = fetcher
        self.store_path = store_path
        self._lock = threading.Lock()
        self._mtime = None
        self._data = self._load()

    # ------------------------------------------------------------

    def _stamp(self):
        """(mtime_ns, size) -- see core/preopen.py's _stamp() for why this
        is not getmtime(). Float seconds miss a rewrite inside one tick."""
        try:
            st = os.stat(self.store_path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _load(self):
        self._mtime = self._stamp()
        try:
            with open(self.store_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _maybe_reload(self):
        """Re-read the file if something else has written it since.

        Same fix, same reason as core/preopen.py's, one hour earlier in
        the day. main.py builds this as PreMarket(fetcher=None) --
        "reads what the 08:45 run stored" -- and _load() ran once in
        __init__. On 30 July 2026 the operator started the session at
        08:59 and ran tools/premarket_brief.py at 09:07; it collected
        the overnight numbers correctly and the Global Markets and Macro
        panels stayed empty all day, because the object in memory had
        already read an empty file.

        The file is the source of truth. One stat() per dashboard
        refresh, re-parsed only when the timestamp actually moved.
        """
        stamp = self._stamp()
        if stamp is None or stamp == self._mtime:
            return
        fresh = self._load()
        if fresh:
            self._data = fresh
            decision(f"[PREMARKET] Re-read {self.store_path} -- "
                     f"{len(fresh.get('quotes') or {})} quotes, "
                     f"collected {fresh.get('fetched_at') or '?'}.")

    def _save(self, data):
        """Write the overnight numbers, and SAY SO if the write failed.

        Was `except OSError: pass`. The collection log would report "18
        overnight numbers collected" while nothing reached disk, and since
        the mtime reload landed the file IS what the dashboard reads --
        so a failed save shows as an empty Global Markets panel under a
        log line claiming success. Same shape as the Telegram bug.
        """
        try:
            directory = os.path.dirname(self.store_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
        except OSError as exc:
            warn(f"[PREMARKET] COULD NOT SAVE {self.store_path}: {exc}. The "
                 f"overnight numbers were collected but are NOT stored, so "
                 f"the Global Markets and Macro panels will stay empty.")
            return False
        return True

    # ------------------------------------------------------------

    def refresh(self):
        """Fetch everything. Never raises. Returns how many succeeded.

        A source that fails leaves the PREVIOUS value in place and is
        marked stale, rather than blanking the panel -- but it is marked,
        so a stale crude price can never be mistaken for a live one.
        """
        if self._fetcher is None:
            warn("[PREMARKET] No fetcher wired -- nothing collected.")
            return 0

        # ---- EIGHTEEN REQUESTS IN A ROW IS WHY IT FAILS ----
        #      3 August 2026.
        #
        # data/premarket.json was found with fetched_at 17:24:38 and
        # ALL EIGHTEEN sources in "failed" -- crude, gold, the dollar,
        # both US yields, every index. Run again by hand minutes later
        # it collected all eighteen first time.
        #
        # Nothing was broken. This loop fires eighteen HTTP requests at
        # Yahoo back to back with no pause and no second attempt, and
        # Yahoo throttles that. It is all-or-nothing: either the burst
        # gets through or the whole overnight picture is lost for the
        # session, and the operator is left trading blind on exactly
        # the inputs he asked to be watched continuously.
        # Only the real network fetcher waits. requests_fetcher() marks
        # itself; an injected test double does not, so the suite stays
        # instant and never sleeps eighteen times per call.
        throttled = bool(getattr(self._fetcher, "throttle", False))
        gap = REQUEST_GAP_SECONDS if throttled else 0.0
        backoff = RETRY_BACKOFF_SECONDS if throttled else 0.0

        collected, failed = {}, []
        for index, (key, symbol, label, group) in enumerate(SOURCES):
            if index and gap:
                time.sleep(gap)
            quote = None
            for attempt in range(RETRIES):
                try:
                    quote = parse_yahoo(self._fetcher(symbol))
                    if quote is not None:
                        break
                except Exception as exc:                   # noqa: BLE001
                    diagnostic(f"[PREMARKET] {label}: attempt "
                               f"{attempt + 1}/{RETRIES} failed ({exc}).")
                if attempt + 1 < RETRIES and backoff:
                    # Backing off further each time. A throttle wants
                    # patience, not persistence.
                    time.sleep(backoff * (attempt + 1))
            if quote is None:
                failed.append(label)
                continue
            quote.update(label=label, group=group, symbol=symbol)
            collected[key] = quote

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            previous = dict(self._data.get("quotes") or {})
            for key, value in previous.items():
                if key not in collected:
                    value = dict(value)
                    value["stale"] = True
                    collected[key] = value
            # fetched_at alone made a total failure look fresh: the file
            # said 17:24 while every number in it was hours older. The
            # question that matters is when data last actually ARRIVED,
            # so that is recorded separately and never overwritten by a
            # run that collected nothing.
            fresh_now = len(collected) - sum(1 for q in collected.values()
                                             if q.get("stale"))
            self._data = {
                "quotes": collected,
                "fetched_at": now,
                "last_success_at": (now if fresh_now
                                    else self._data.get("last_success_at")),
                "failed": failed,
            }
        self._save(self._data)

        fresh = len(collected) - sum(1 for q in collected.values()
                                     if q.get("stale"))
        if failed:
            warn(f"[PREMARKET] {fresh}/{len(SOURCES)} collected. "
                 f"Could not fetch: {', '.join(failed)}.")
        else:
            decision(f"[PREMARKET] {fresh} overnight numbers collected.")
        return fresh

    # ------------------------------------------------------------

    def snapshot(self):
        """What the dashboard renders. Grouped, plain data, safe to JSON.

        Checks the file first -- see _maybe_reload().
        """
        with self._lock:
            self._maybe_reload()
            data = dict(self._data)
        quotes = data.get("quotes") or {}
        groups = {}
        for key, _symbol, label, group in SOURCES:
            quote = quotes.get(key)
            groups.setdefault(group, []).append({
                "key": key,
                "label": label,
                "last": quote.get("last") if quote else None,
                "change_pct": quote.get("change_pct") if quote else None,
                "stale": bool(quote.get("stale")) if quote else False,
                "available": quote is not None,
            })
        return {
            "groups": groups,
            "fetched_at": data.get("fetched_at"),
            "failed": data.get("failed") or [],
            "available": bool(quotes),
        }

    def get(self, key):
        with self._lock:
            return (self._data.get("quotes") or {}).get(key)

    def as_text(self):
        """The overnight picture in plain lines -- for the console at
        08:45, and later as the input an AI briefing reads."""
        snap = self.snapshot()
        if not snap["available"]:
            return "No overnight data collected."
        lines = [f"OVERNIGHT PICTURE  (collected {snap['fetched_at']})", ""]
        for group in ("US", "RATES", "ENERGY", "METALS", "ASIA", "FX"):
            rows = snap["groups"].get(group) or []
            shown = [r for r in rows if r["available"]]
            if not shown:
                continue
            lines.append(f"  {group}")
            for row in shown:
                change = ("" if row["change_pct"] is None
                          else f"  {row['change_pct']:+.2f}%")
                stale = "   (stale)" if row["stale"] else ""
                lines.append(f"    {row['label']:<16} {row['last']:>12,.2f}"
                             f"{change}{stale}")
            lines.append("")
        if snap["failed"]:
            lines.append(f"  could not fetch: {', '.join(snap['failed'])}")
        return "\n".join(lines)
