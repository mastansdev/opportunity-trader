"""
==========================================================
Order wins and business updates -- the reasons nobody read
==========================================================

    "concall , business updates are already with telegram pro channels
     & also check for the data we were ignoring"
                                -- operator, 8 August 2026

    "BUSINESS PULSE IS GOOD WITH COMPLETE DATA"

    "without any info no one will buy even a 1 rs. in the stock market
     every thing is connected"

WHY THIS EXISTS
---------------
Measured 8 August against the real store. Two paid channels had been
arriving for a month, correctly symbol-tagged, and why_moving() had
never once read either:

    Business Pulse    107 messages / 30 days,  99% tag accuracy
                      20% of its symbols had any reason at all
    OrderBook Pulse   102 messages / 30 days,  92% tag accuracy

These are the ANTICIPATION catalysts -- the ones that move a stock
weeks before a result exists. A Rs 990 crore stadium contract for a
mid-cap is the event that makes funds accumulate; a monthly business
update is how auto, NBFC and retail names get re-rated between
quarters. The bot was reading neither.

THE TWO FORMATS, verbatim from the store
----------------------------------------
    OrderBook Pulse
        "New Rs 990.16 crore order for International Cricket Stadium.
         #JKIL - 1 minute ago"
        "L&T wins major offshore orders from ONGC... #LT"

    Business Pulse
        "Monthly Business Update : Ashok Leyland - July 2026 #ASHOKLEY"
        "Quarterly Business Update : Sai Silks - Q2 FY27 #KALAMANDIR"

SIZE, NOT THE STAR
------------------
The channel marks its own magnitude, and measured across 57 orders it
is real:

    trophy      median Rs 334 Cr
    star        median Rs  33 Cr
    no marker   median Rs 2.7 Cr

But the rupee figure is printed on the card, so this reads that
instead -- a number beats a proxy for a number. The marker is kept
only as a fallback when the value cannot be parsed.

WHAT IT DOES NOT DO
-------------------
It does not judge whether the order is good for margins. A large order
at thin margins can still be POSITIVE for the price, and deciding
which is a question for scored outcomes, not for a regex.

    "nothing from the guides becomes a rule until scored against real
     outcomes"

The weights below are therefore PROVISIONAL and marked as such. They
rank one catalyst against another; they do not claim to know what a
contract is worth.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import sqlite3
from datetime import datetime, timedelta

TELEGRAM_DB = "data/telegram.db"

ORDER_CHANNEL = "OrderBook Pulse"
UPDATE_CHANNEL = "Business Pulse"

# How far back a catalyst still explains today's move. An order win is
# news for a session or two; after that the tape has absorbed it.
FRESH_HOURS = 30.0

# ---- PROVISIONAL WEIGHTS ----
# Calibrated against why_moving's existing scale, where a reported
# result carries 0.55 and an unexplained volume spike 0.35. They will
# be re-set from the outcome scorer once it has a few hundred rows;
# until then they order catalysts against each other and nothing more.
W_ORDER_HUGE = 0.60         # >= Rs 500 Cr
W_ORDER_LARGE = 0.45        # >= Rs 100 Cr
W_ORDER_MID = 0.30          # >= Rs 25 Cr
W_ORDER_SMALL = 0.15        # anything smaller, or no figure printed
W_UPDATE_QUARTERLY = 0.35
W_UPDATE_MONTHLY = 0.25

HUGE_CR, LARGE_CR, MID_CR = 500.0, 100.0, 25.0

# "Rs. 1.05 crore", "₹37.79 crore", "Rs 990.16 Cr", "₹4.88 crore"
_VALUE = re.compile(
    r"(?:Rs\.?|₹|INR)\s*([\d][\d,]*(?:\.\d+)?)\s*"
    r"(crore|cr\b|lakh|lakhs)", re.I)

# The recap board -- "Orderbook Recap, Daily Highlights - AUGUST 06".
# It lists the day's orders and belongs to no single stock.
_RECAP = re.compile(r"ORDERBOOK\s+RECAP|DAILY\s+HIGHLIGHTS|"
                    r"#STOCKSTOWATCH", re.I)

_UPDATE_KIND = re.compile(
    r"(Monthly|Quarterly)\s+Business\s+Update\s*:\s*([^#\n]{2,48}?)\s*"
    r"[-–—]\s*([A-Za-z0-9 ]{3,18})", re.I)

# The channel appends "- 35 seconds ago" to every headline. It is not
# part of the sentence he should read.
_AGO = re.compile(r"\s*[-–—]\s*\d+\s*(second|minute|hour|day)s?\s*ago.*$",
                  re.I | re.S)


# ---- messages.at IS UTC. THE CLOCK IS IST. 8 August 2026. ----
#
# Verified against the store rather than assumed: the pre-open gapper
# card carries at = 03:38 and seen_at = 09:09, and it is published at
# 09:08 IST. So at + 5:30 = IST, and every window built from
# datetime.now() has to be pushed back to UTC before it touches `at`.
#
# The first version of this file compared an IST cutoff against UTC
# timestamps -- a 5.5 hour error, silently including catalysts from
# the previous evening and excluding the current morning's. Nothing
# raised; the answers were just quietly wrong, which is the failure
# mode this project keeps producing.
#
# core/outcomes.py and tools/check.py already carry the same offset.
IST_OFFSET = timedelta(hours=5, minutes=30)


def _utc_window(now, hours):
    """(cutoff, ceiling) in UTC for an IST wall-clock `now`."""
    now_utc = now - IST_OFFSET
    return (now_utc - timedelta(hours=hours)).isoformat(), now_utc.isoformat()


def _rows(db_path, sql, args=()):
    try:
        con = sqlite3.connect(db_path)
        got = con.execute(sql, args).fetchall()
        con.close()
        return got
    except Exception:                                      # noqa: BLE001
        return []


def value_cr(text):
    """The order's size in rupees crore, or None if none is printed."""
    match = _VALUE.search(str(text or ""))
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = match.group(2).lower()
    return amount / 100.0 if unit.startswith("lakh") else amount


def _weight_for(size_cr, marker):
    if size_cr is None:
        # No figure printed. Fall back to the channel's own marker,
        # which measured out at a median of Rs 334 Cr for the trophy.
        if marker == "trophy":
            return W_ORDER_LARGE
        return W_ORDER_SMALL
    if size_cr >= HUGE_CR:
        return W_ORDER_HUGE
    if size_cr >= LARGE_CR:
        return W_ORDER_LARGE
    if size_cr >= MID_CR:
        return W_ORDER_MID
    return W_ORDER_SMALL


def _marker(text):
    body = str(text or "")
    if "\U0001F3C6" in body:            # trophy
        return "trophy"
    if "⭐" in body:                # star
        return "star"
    return None


def _headline(text):
    """The sentence without the channel's '- 2 minutes ago' tail."""
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    body = _AGO.sub("", body)
    # Drop leading markers and stray emoji so the reason reads plainly.
    body = re.sub(r"^[^A-Za-z0-9₹Rs]+", "", body).strip()
    return body[:150]


def read_order(text):
    """{"text", "size_cr", "weight"} for one OrderBook Pulse card."""
    body = str(text or "")
    if not body.strip() or _RECAP.search(body):
        return None
    size = value_cr(body)
    headline = _headline(body)
    if not headline:
        return None
    if size is not None:
        sentence = f"order win -- {headline}"
    else:
        sentence = f"order win -- {headline}"
    return {"text": sentence, "size_cr": size,
            "weight": _weight_for(size, _marker(body)),
            "kind": "order"}


def read_update(text):
    """{"text", "weight"} for one Business Pulse card."""
    body = str(text or "")
    if not body.strip():
        return None
    match = _UPDATE_KIND.search(body)
    if not match:
        return None
    cadence = match.group(1).title()
    company = re.sub(r"\s+", " ", match.group(2)).strip(" .-")
    period = re.sub(r"\s+", " ", match.group(3)).strip(" .-")
    weight = (W_UPDATE_QUARTERLY if cadence.lower().startswith("quarter")
              else W_UPDATE_MONTHLY)
    return {"text": f"{cadence.lower()} business update -- "
                    f"{company} {period}",
            "weight": weight, "kind": "update"}


def for_symbol(symbol, now=None, db_path=TELEGRAM_DB, hours=FRESH_HOURS):
    """The freshest catalyst for this stock, or None.

    Shaped exactly like core/why_moving.py's other mechanisms so it can
    be returned straight from why(), with `direction` POSITIVE -- an
    order win and a business update are both, by their nature, the
    company reporting something it chose to announce.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return None
    now = now or datetime.now()

    # ---- ONE QUERY PER WINDOW, NOT ONE PER STOCK. 8 Aug 2026 ----
    #
    # The first version ran a SQL query and up to 60 subject.is_about()
    # calls EVERY time why() was asked about a symbol. The ranker asks
    # about 60+ symbols per cycle, several times a minute, and the test
    # suite went from 165 seconds to not finishing.
    #
    # In production that is worse than slow: the ranking loop would
    # have been doing thousands of redundant reads while the market
    # moved. Build the whole window once and look the symbol up.
    index = _window_index(now, hours, db_path)
    return index.get(symbol)


_index_cache = {}


def _window_index(now, hours, db_path):
    """{symbol: catalyst} for one window, built once and cached."""
    cutoff, ceiling = _utc_window(now, hours)
    key = (cutoff, ceiling, db_path)
    hit = _index_cache.get(key)
    if hit is not None:
        return hit
    built = _build_index(cutoff, ceiling, db_path)
    # A live session walks forward minute by minute, so the key changes
    # constantly. Keep the cache small rather than unbounded.
    if len(_index_cache) > 8:
        _index_cache.clear()
    _index_cache[key] = built
    return built


def _build_index(cutoff, ceiling, db_path):
    out = {}
    rows = _rows(
        db_path,
        "select channel, coalesce(text, ''), coalesce(ocr_text, ''), "
        "at, coalesce(symbols, '') from messages "
        "where channel in (?, ?) and at >= ? and at <= ? "
        "and symbols is not null and symbols <> '' "
        "order by at desc limit 400",
        (ORDER_CHANNEL, UPDATE_CHANNEL, cutoff, ceiling))

    for channel, body, ocr, at, raw in rows:
        text = f"{body} {ocr}"
        got = (read_order(text) if channel == ORDER_CHANNEL
               else read_update(text))
        if not got:
            continue
        for part in re.split(r"[,\[\]\"']+", str(raw or "")):
            symbol = part.strip().upper()
            if not symbol:
                continue
            # The same subject rule as the chips -- without it the
            # Orderbook RECAP would become an order win for every
            # company printed on it.
            try:
                from core import subject
                if not subject.is_about(symbol, text):
                    continue
            except Exception:                              # noqa: BLE001
                continue
            record = dict(got)
            record["source"] = channel
            record["direction"] = "POSITIVE"
            record["at"] = at
            best = out.get(symbol)
            if best is None or record["weight"] > best["weight"]:
                out[symbol] = record
    return out


def _for_symbol_uncached(symbol, now, db_path, hours):
    """Kept for reference and for the one-off tools; not on the hot
    path."""
    cutoff, ceiling = _utc_window(now, hours)

    rows = _rows(
        db_path,
        "select channel, coalesce(text, ''), coalesce(ocr_text, ''), at "
        "from messages where channel in (?, ?) and at >= ? and at <= ? "
        "and symbols is not null and symbols <> '' "
        "order by at desc limit 60",
        (ORDER_CHANNEL, UPDATE_CHANNEL, cutoff, ceiling))

    best = None
    for channel, body, ocr, at in rows:
        text = f"{body} {ocr}"
        # ---- THE SAME SUBJECT RULE AS THE CHIPS. 8 August 2026. ----
        # These cards carry #SYMBOL exactly like the Pulse channels, so
        # core/subject.py already knows how to read them. Without this
        # the Orderbook RECAP -- which names a dozen companies -- would
        # become an order win for every one of them.
        try:
            from core import subject
            if not subject.is_about(symbol, text):
                continue
        except Exception:                                  # noqa: BLE001
            continue

        got = (read_order(text) if channel == ORDER_CHANNEL
               else read_update(text))
        if not got:
            continue
        got["source"] = channel
        got["direction"] = "POSITIVE"
        got["at"] = at
        # Newest first from the query, and a bigger order outranks an
        # older smaller one on the same day.
        if best is None or got["weight"] > best["weight"]:
            best = got
    return best


def recent(hours=FRESH_HOURS, now=None, db_path=TELEGRAM_DB):
    """{symbol: catalyst} across both channels -- for the watchlist."""
    now = now or datetime.now()
    return dict(_window_index(now, hours, db_path))
