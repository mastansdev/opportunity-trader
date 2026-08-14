"""
==========================================================
FII / DII flows -- who is actually buying
==========================================================

config.py has carried FII_NET_CR = None and DII_NET_CR = None since the
dashboard was built. They were meant to be typed in by hand and never
were, so the Market Intelligence tile has read "set in config (EOD)"
every session since.

Operator, 2026-07-28: "they also play imp role, pls fix them too with
working conditions."

WHAT THIS IS AND IS NOT
-----------------------
NSE publishes FII and DII cash-market net figures once a day, AFTER the
close. There is no intraday feed of this anywhere -- the provisional
number lands in the evening. So this tile can only ever say what the
institutions did YESTERDAY (or, after the close, today).

That is still worth having: sustained FII selling is the backdrop to a
lot of weak sessions. But it is a CONTEXT number, not a trigger, and the
panel labels it with its own date so a stale figure can never be
mistaken for a live one -- which is exactly the failure this whole
dashboard was built to avoid.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn

CACHE_PATH = os.path.join("data", "market_flows.json")

# The nse package has renamed this over versions; try each.
# The nse package renames this between versions and none of the four
# names guessed on 2026-07-28 existed. Rather than guess a fifth time,
# ANY method whose name mentions fii/dii is tried, and the ones actually
# available are logged so the real name is visible once.
NSE_METHODS = ("fiiDiiTradeReact", "fii_dii", "fiiDii", "fiidiiTradeReact",
               "fiiDiiData", "fii_dii_data", "fiidii")


def _num(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("₹", "").strip()
    if not text or text in ("-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group()) if m else None


def parse_rows(rows):
    """NSE returns a list like:
        [{"category": "DII **", "date": "28-Jul-2026",
          "buyValue": "12345.67", "sellValue": "11000.00",
          "netValue": "1345.67"}, ...]
    Returns {"fii_cr": float|None, "dii_cr": float|None, "as_of": str}.
    """
    out = {"fii_cr": None, "dii_cr": None, "as_of": None}
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category") or row.get("Category") or "").upper()
        net = _num(row.get("netValue") or row.get("net_value")
                   or row.get("Net") or row.get("net"))
        date = str(row.get("date") or row.get("Date") or "").strip()
        if date and not out["as_of"]:
            out["as_of"] = date
        if net is None:
            continue
        if "FII" in cat or "FPI" in cat:
            out["fii_cr"] = round(net, 2)
        elif "DII" in cat:
            out["dii_cr"] = round(net, 2)
    return out


# ---------------------------------------------------------------
# THE TELEGRAM FALLBACK -- 30 July 2026
# ---------------------------------------------------------------
#     "News_pulse = same as ours (rss) but this will also post FII &
#      DII numbers."
#
# The FII/DII panel had been a config placeholder since it was written:
#
#     "FII / DII set in config (EOD) ?  these are still as a place
#      holders . pls check with dhan if any of them we are recvng ??"
#
# Dhan does not publish it. NSE does, after the close, and the operator's
# own News Pulse channel reposts it within minutes:
#
#     "FIIs were net buyers of Rs 3,623.51 Cr in equities today, while
#      DIIs were net sellers of Rs 1,864.03 Cr."
#
# So the number was already on disk, in telegram.db, being displayed as
# a chat message and read as data by nothing.
_FLOW_LINE = re.compile(
    r"(FII|DII)s?\s+(?:were\s+)?net\s+(buyer|seller)s?\s+of\s+"
    r"(?:Rs\.?|₹|INR)?\s*([\d,]+(?:\.\d+)?)\s*(cr|crore)",
    re.I)

# ---- ONE PHRASING OUT OF SEVEN. 3 August 2026. ----
#
#     "FII/DII = news pulse (keep green if buy & red if sold)"
#
# The regex above was written against a single sentence shape and
# caught one message in six. Read out of the operator's real
# data/telegram.db, News Pulse writes the same daily figure at least
# seven different ways:
#
#   "FIIs were net buyers of Rs 3,623.51 Cr in equities today, while
#    DIIs were net sellers of Rs 1,864.03 Cr"          <- the old one
#   "DIIs were net buyers of Rs 2,260.37 Cr, and FII/FPIs were net
#    buyers of Rs 277.48 Cr"                    <- the slash broke it
#   "FIIs net bought shares worth Rs 3,624 crore, while DIIs net sold
#    equities worth Rs 1,864 crore"
#   "FIIs bought Indian equities worth Rs 3,623.51 crore on Thursday"
#   "DIIs net purchased shares worth Rs 998 crore"
#   "Foreign investors were net buyers of Indian equities, investing
#    nearly Rs 3,000 crore"                   <- never says "FII"
#   "Foreign Institutional Investors (FIIs) net bought Rs 277.48 Cr"
#
# AND THE TRAP THAT MATTERS MOST
# ------------------------------
# The same channel, under the same heading, also posts PERIOD figures:
#
#   "FPIs became net buyers ... with inflows of Rs 6,732 crore in July"
#
# Six thousand crore is a month, not a day. Parsed as a daily number it
# would put a figure eleven times too large on the tile and make an
# ordinary session look like a stampede. Period wording is refused
# outright -- a missing number is recoverable, a wrong one is not.
_PARTY = re.compile(
    r"(FII|FPI|DII|foreign\s+(?:institutional\s+|portfolio\s+)?investors?"
    r"|domestic\s+(?:institutional\s+)?investors?)", re.I)
_BUY = re.compile(r"\b(buyer|bought|buying|purchas\w+|invest(?:ing|ed)|"
                  r"inflow)\w*", re.I)
_SELL = re.compile(r"\b(seller|sold|selling|offload\w*|outflow)\w*", re.I)
_AMOUNT = re.compile(
    r"(?:Rs\.?|₹|INR)?\s*([\d,]+(?:\.\d+)?)\s*(?:cr\b|crore)", re.I)
# Anything describing a stretch of time rather than one session.
_PERIOD = re.compile(
    r"\b(?:in|for|during|over)\s+(?:the\s+)?"
    r"(?:month|week|year|quarter|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|"
    r"jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)"
    r"|\bmonthly\b|\bweekly\b|\byear[- ]to[- ]date\b|\bytd\b"
    r"|\b(?:four|three|two|five|six)[- ]month\b|\bso far\b", re.I)

_WINDOW = 130   # characters after a party name that still describe it

# A Monday morning has to reach back past the weekend to Friday's
# close, so four days rather than the thirty hours that used to be the
# default. The scan depth is a day's traffic across nine channels.
FLOW_LOOKBACK_HOURS = 96
FLOW_SCAN_ROWS = 3000


def _side_of(chunk):
    buy, sell = _BUY.search(chunk), _SELL.search(chunk)
    if buy and sell:
        return 1 if buy.start() < sell.start() else -1
    if buy:
        return 1
    if sell:
        return -1
    return 0


def parse_flow_message(text):
    """{"fii_cr": ..., "dii_cr": ...} from one News Pulse line.

    SIGN MATTERS AND IS THE WHOLE POINT. "net buyers of Rs 3,623.51 Cr"
    is +3623.51; "net sellers of Rs 1,864.03 Cr" is -1864.03. Storing
    both as positive magnitudes would make a day of heavy institutional
    selling read exactly like a day of heavy buying.

    Returns None rather than a guess. A blank tile is a question; a
    wrong tile is a trade.
    """
    body = " ".join(str(text or "").split())
    if not body:
        return None

    hits = list(_PARTY.finditer(body))
    if not hits:
        return None

    out = {}
    for index, hit in enumerate(hits):
        name = hit.group(1).lower()
        who = "dii" if name.startswith("d") else "fii"
        if who == "fii" and name.startswith("foreign") and "investor" not in name:
            continue
        # Read only as far as the next party, so "FIIs bought X while
        # DIIs sold Y" can never hand X's number to DII.
        end = hits[index + 1].start() if index + 1 < len(hits) else len(body)
        chunk = body[hit.end():min(end, hit.end() + _WINDOW)]

        if _PERIOD.search(chunk):
            continue
        side = _side_of(chunk)
        if not side:
            continue
        amount = _AMOUNT.search(chunk)
        if not amount:
            continue
        try:
            value = float(amount.group(1).replace(",", ""))
        except ValueError:
            continue
        if value <= 0:
            continue
        key = f"{who}_cr"
        # First mention wins; later sentences in the same post tend to
        # be commentary restating a rounded version of the same figure.
        out.setdefault(key, round(value * side, 2))

    return out or None


def from_telegram(telegram, hours=FLOW_LOOKBACK_HOURS, limit=FLOW_SCAN_ROWS):
    """The most recent FII/DII figure the channels have posted.

    Returns None when nothing is found -- which must stay distinct from
    "flows were zero". Nobody has ever seen a day with exactly zero.

    ---- WHY THE DEFAULTS ARE WHAT THEY ARE. 3 August 2026. ----

    Measured against the operator's real data/telegram.db:

        limit=200, hours=30  ->  502 rows scanned,  0 flow figures
        limit=3000, hours=168 -> 3000 rows scanned, 11 flow figures

    Two separate mistakes, both invisible because the fallback simply
    returned None and the tile stayed blank:

      * 200 is far below a day's traffic across nine channels, so the
        flow post was never in the rows being read at all.
      * 30 hours cannot cross a weekend. Today is Monday; the last
        session was Friday 31 July and its figure is 57 hours old. Any
        Monday would have shown an empty tile no matter what.
    """
    if telegram is None:
        return None
    try:
        rows = telegram.recent(limit=limit, hours=hours) or []
    except Exception:                                      # noqa: BLE001
        return None
    for row in rows:                       # recent() is newest-first
        body = (row.get("text") or "") + "\n" + (row.get("ocr_text") or "")
        parsed = parse_flow_message(body)
        if parsed:
            parsed["as_of"] = row.get("at")
            parsed["source"] = row.get("channel") or "Telegram"
            return parsed
    return None


class MarketFlows:
    """Fetches once at startup and again after the close. Cached to disk
    so a restart shows yesterday's number instead of a dash."""

    def __init__(self, fetcher=None, cache_path=CACHE_PATH):
        self._fetcher = fetcher or self._fetch_nse
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._data = self._load_cache()
        self._error = None
        self._fetched_at = None

    # ------------------------------------------------------------

    @staticmethod
    def _fetch_nse():
        from nse import NSE
        with NSE(download_folder="data") as n:
            for name in NSE_METHODS:
                fn = getattr(n, name, None)
                if callable(fn):
                    return fn()
            # Nothing matched. Find anything fii/dii-ish and TRY it,
            # then report what the package really offers so the next
            # attempt is informed rather than another guess.
            candidates = [m for m in dir(n)
                          if not m.startswith("_")
                          and ("fii" in m.lower() or "dii" in m.lower())]
            for name in candidates:
                fn = getattr(n, name, None)
                if callable(fn):
                    decision(f"[FLOWS] Using nse.{name}() for FII/DII.")
                    try:
                        return fn()
                    except Exception:                      # noqa: BLE001
                        continue
            # List CALLABLES only, lowercase-first. The first version of
            # this sorted everything alphabetically and the 40-item cap
            # filled with CONSTANTS -- FNO_BANK, HOLIDAY_TRADING -- which
            # told the operator nothing about what methods exist.
            methods = sorted(m for m in dir(n)
                             if not m.startswith("_")
                             and callable(getattr(n, m, None)))
            raise AttributeError(
                "no FII/DII method on the nse package. Callables: "
                + ", ".join(methods))

    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, data):
        try:
            d = os.path.dirname(self.cache_path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ------------------------------------------------------------

    def refresh(self):
        """Never raises. On failure the cached figure stays on screen and
        the error is surfaced, because a blank tile and a broken feed
        must not look the same."""
        try:
            parsed = parse_rows(self._fetcher())
        except Exception as exc:                           # noqa: BLE001
            self._error = str(exc)[:140]
            warn(f"[FLOWS] FII/DII fetch failed ({self._error}). "
                 f"Showing the last figure held.")
            return None
        if parsed["fii_cr"] is None and parsed["dii_cr"] is None:
            self._error = "feed returned no FII/DII rows"
            warn("[FLOWS] FII/DII feed returned nothing usable.")
            return None
        parsed["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock:
            self._data = parsed
            self._error = None
            self._fetched_at = datetime.now()
        self._save_cache(parsed)
        decision(f"[FLOWS] FII {parsed['fii_cr']} cr / DII "
                 f"{parsed['dii_cr']} cr (as of {parsed['as_of']}).")
        return parsed

    def snapshot(self):
        with self._lock:
            d = dict(self._data)
        fii, dii = d.get("fii_cr"), d.get("dii_cr")
        return {
            "available": fii is not None or dii is not None,
            "fii_cr": fii, "dii_cr": dii,
            "as_of": d.get("as_of"),
            "fetched_at": d.get("fetched_at"),
            "error": self._error,
            # NSE publishes this after the close, so it is ALWAYS about a
            # completed session. Labelled so a stale number can never be
            # read as a live one.
            "note": ("EOD figure, published after the close"
                     if fii is not None or dii is not None
                     else "not fetched yet"),
        }
