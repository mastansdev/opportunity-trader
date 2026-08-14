"""
==========================================================
One row per stock, not one row per message
==========================================================

    "News collected - now it is a hell of mess with repeated items
     without clarity ... i need a clean table with
     Symbol  News (here details)  Time
     and mostly if the same stock gets more news, results from our
     sources. simply add them next to news column . not to print a
     separate line alone."
                                    -- operator, 1 August 2026

WHAT THE PANEL WAS DOING
------------------------
Every RSS item and every Telegram message, one line each, newest
first, nothing removed and nothing joined. Measured on the 400 most
recent messages held on 1 August 2026:

    average body length        211 characters
    bodies over 200 characters 124
    junk rows (bot DMs)         10  -- "/start", "Logged in!",
                                       "Subscription Activated!"

and the same company arriving three ways produced three lines that
looked unrelated:

    [TG] Earnings 360    07:51  GHCL - Q1 FY27 Exceptional gain from
                                ESOS Trust settlement inflates an
                                otherwise solid quarter...
    [TG] Earnings Pulse  07:51  #GHCL - OK Results - 32 seconds ago

Two readings of one quarter, printed as two unconnected paragraphs.
The operator has about a minute before the open and he was reading
the same stock twice without knowing it.

WHAT THIS BUILDS INSTEAD
------------------------
    SYMBOL   NEWS                                          TIME
    GHCL     OK Results  (Earnings Pulse 07:51)            07:51
             Exceptional gain from ESOS Trust settlement
             inflates an otherwise solid quarter
             (Earnings 360 07:51)

One row per stock. Every item it received is in the News cell, each
carrying its own source and its own clock. Time is the newest of them,
because that is what decides where the row sits.

THREE RULES, AND EACH ONE COST SOMETHING TO LEARN
-------------------------------------------------
1. A BOT DM IS NOT NEWS. @WLPulseBot's login and subscription
   confirmations were being ranked alongside earnings.

2. THE HEADLINE IS THE FIRST SENTENCE, NOT THE WHOLE CARD. An OCR'd
   results card is 400 characters of table. The chip layer already
   extracts what matters; this layer shows the first line and stops.

3. MARKET COMMENTARY KEEPS ITS OWN SECTION. "Chris Wood cautions on AI
   capex" names no stock. Dropping it loses context that sometimes
   explains an entire day; mixing it in is what made the table
   unreadable. So it sits below, separately, and is never sorted
   against stock news.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not judge, score, or rank. Ordering is by time, newest first.
Deciding which news matters is core/shortlist.py's job and it has the
evidence to do it; this table's only promise is that everything
received is visible and readable.

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import datetime

# ---------------------------------------------------------------
# NOT NEWS
# ---------------------------------------------------------------
# Read off the real store: @WLPulseBot is a bot we talk to, so its
# side of the conversation lands in the same table as its alerts.
# Ten rows in the last six hundred, and every one of them at the top
# of the panel because they were the most recent thing that happened.
_NOT_NEWS = re.compile(
    r"^\s*/\w+\s*$|"                       # /start, /help
    r"logged\s*in\b|signed\s+in\s+on|"
    r"subscription\s+activated|plan\s*:\s*\w+\s+(quarterly|monthly)|"
    r"what'?s\s+included|choose\s+an\s+option|tap\s+(below|the)|"
    r"use\s+the\s+buttons|welcome\s+to\s+\w+bot|"
    r"^\s*(hi|hello|hey|ok|thanks)\s*[!.]?\s*$",
    re.I)

# Page furniture on an OCR'd card. Never the story.
_FURNITURE = re.compile(
    r"earningspulse\.ai|AI-generated\s+summary|Not\s+investment\s+advice|"
    r"Verify\s+with\s+official|Full\s+analysis|Page\s+\d+\s+of\s+\d+|"
    r"^\s*\d{1,2}[-\s]\w{3}[-\s]20\d\d",
    re.I)

# ---- THE X ACCOUNT HEADER, 1 August 2026 ----
#
#     "THEY WILL POST/FORWARD ONLY IMAGES FROM X WHICH ARE USEFUL FOR
#      OUR CAUSE & EFFECT ON STOCKS + RESULTS + NDTV LIST"
#                                    -- operator
#
# He is right that the images are the value. They are SCREENSHOTS of
# tweets, and every one opens with the poster's account card:
#
#     a= RedboxGlobal India @          <- display name, verified badge
#     i= @REDBOXINDIA                  <- the handle
#     DIXON TECH: Q1 CONS NET PROFIT 6.6B RUPEES VS 2.25B (YOY)
#
# The news starts on line three. Without this every Day Trader Telugu
# row spent its first forty characters saying REDBOXINDIA, and the
# operator has about a minute before the open.
#
# IMPORTED, NOT RESTATED. The same header has to come off in two
# places -- here for the panel, and in core/stock_events.py when the
# EVENT headline is built, because by then the line breaks are gone
# and no line-based rule can find it again. Two copies of the pattern
# is how one of them silently stops matching.
from core.stock_events import _X_HEADER            # noqa: E402

# "- 28 seconds ago", "- 3 minutes ago". The channel's own freshness
# stamp, which is meaningless once we have stored our own timestamp
# and actively misleading a day later.
_AGO = re.compile(r"\s*[-–—]?\s*\d+\s*(second|minute|hour|day)s?\s+ago\s*$",
                  re.I)

# Leading decoration: hashes, bullets, emoji, the coloured dot.
_LEAD_JUNK = re.compile(r"^[\s\W\d_]{0,8}")

MAX_HEADLINE = 150
MAX_ITEMS_PER_SYMBOL = 6


# A line that is only a ticker and a quarter. Earnings 360 puts the
# title on line one and the SENTENCE on line two:
#
#     🟢 #GHCL — Q1 FY27
#     Exceptional gain from ESOS Trust settlement inflates an
#     otherwise solid quarter.
#
# Taking the first usable line alone produced a table of "GHCL — Q1
# FY27" and "CLEAN — Q1 FY27", which is a list of things that
# happened with the news removed.
_TITLE_ONLY = re.compile(
    r"^[\s\W]{0,6}[A-Z][A-Z0-9&\-]{1,14}\s*[—–\-|·]?\s*"
    r"(Q[1-4]\s*FY\s*\d{2,4}|Earnings|Concall\s+Summary|Results?)?"
    r"[\s\W]*$", re.I)

# Enough characters that the row says something. Below this the
# headline is a label, so the next line is pulled in behind it.
ENOUGH = 55

# A page about the whole session, not about one company.
#
#     Today Earnings - 01 Aug, 2026
#     Key companies reporting results today...
#
# It names a dozen tickers, so a few of them get it attached to their
# row -- where it says nothing about that stock and pushes its real
# news down. It belongs in the market section, which is exactly what
# that section is for.
_WHOLE_SESSION = re.compile(
    r"today'?s?\s+earnings\b|key\s+companies\s+reporting|"
    r"results\s+calendar|market\s+wrap|closing\s+bell|"
    r"top\s+(gainers|losers)\s+today|daily\s+(highlights|digest|recap)",
    re.I)


def _useful_lines(text):
    for line in str(text or "").splitlines():
        line = " ".join(line.split())
        if not line or _FURNITURE.search(line) or _X_HEADER.match(line):
            continue
        stripped = _AGO.sub("", _LEAD_JUNK.sub("", line)).strip()
        if len(stripped) >= 6:
            yield stripped


def _clean(text):
    """One readable line out of whatever the source gave us.

    Joins the title to the sentence beneath it when the title alone
    says nothing -- see _TITLE_ONLY.
    """
    parts = []
    for line in _useful_lines(text):
        if parts and _TITLE_ONLY.match(line):
            continue                      # a repeated #TICKER footer
        parts.append(line)
        joined = " · ".join(parts)
        if len(joined) >= ENOUGH and not _TITLE_ONLY.match(parts[0]):
            break
        if len(parts) >= 3:
            break

    body = " · ".join(parts).strip(" ·")
    if not body:
        body = _AGO.sub("", " ".join(str(text or "").split()))
        body = _LEAD_JUNK.sub("", body).strip()
    if len(body) > MAX_HEADLINE:
        cut = body.rfind(" ", 0, MAX_HEADLINE)
        body = body[:cut if cut > 60 else MAX_HEADLINE].rstrip(" ,;.-·") + "…"
    return body


def is_news(text):
    """False for a bot's own chatter and for a promo clip.

    ---- THE YOUTUBE LINKS, 1 August 2026 ----

        "DAY TRADER TELUGU WILL NOT USE THIS #COMPANY. THEY WILL
         POST/FORWARD ONLY IMAGES FROM X WHICH ARE USEFUL FOR OUR
         CAUSE & EFFECT ON STOCKS + RESULTS + NDTV LIST & WE NEED TO
         STOP USING THEIR YOUTUBE LINKS (NOT IMPORTANT)"

    core/stock_events.NOISE has blocked these from becoming EVENTS
    since it was written, and it catches all 19 of them in the store.
    This panel does not read events -- it reads the stored `symbols`
    column -- so the block never applied here, and four stocks were
    carrying a video thumbnail as their news:

        NTPC       LATEST MARKET UPDATES ...
        KAYNES     BREAKING NEWS ...
        CARTRADE   BREAKING NEWS ...
        ACC        Must Watch Shorts / Gold in Bank Locker? Not Safe

    Imported rather than restated. Two copies of "what is noise" is
    how one of them silently stops matching the other.
    """
    body = " ".join(str(text or "").split())
    if len(body) < 8:
        return False
    if _NOT_NEWS.search(body):
        return False
    try:
        from core.stock_events import NOISE
    except Exception:                                      # noqa: BLE001
        return True
    return not NOISE.search(body)


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _hhmm(at, today=None):
    """The clock, and the DATE when it is not today's.

    ---- 1 August 2026 ----
    JIOFIN's row read

        Bandhan Small Cap ...                       08:11
        Jio Financial has set August 10 ...         07:03
        Jio Financial has set August 10 ...         14:28

    and the last of those is from the PREVIOUS DAY. Printed as a bare
    clock it looks like the newest item in the row -- the operator is
    reading this at 09:10 with a minute to decide, and the one thing a
    time column must never do is put yesterday above this morning.
    """
    text = str(at or "")
    match = re.search(r"(\d{2}):(\d{2})", text)
    if not match:
        return ""
    clock = f"{match.group(1)}:{match.group(2)}"
    day = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not day:
        return clock
    stamp = day.group(0)
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    if stamp == today:
        return clock
    return f"{int(day.group(3))} {_MONTHS[int(day.group(2)) - 1]} {clock}"


def _key(text):
    """What makes two items the same item.

    The same card reaching us twice -- once as a caption, once via a
    second channel -- is one piece of news. Compared on letters and
    digits only, because one copy will have an emoji the other lacks.
    """
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())[:60]


def build(rss_rows=None, telegram_rows=None, limit=60, today=None):
    """{"stocks": [...], "market": [...]} for the news panel.

    Each stock row is
        {"symbol", "at", "time", "count", "items": [{text, source, time}]}

    `market` holds the items that named no stock, in the same shape
    minus the symbol -- kept, never mixed, never dropped.
    """
    by_symbol, market, market_seen = {}, [], set()

    def take(text, source, at, symbols, from_image=False):
        if not is_news(text):
            return
        line = _clean(text)
        if not line:
            return
        # ---- DEDUPED PER SYMBOL, NOT PER MESSAGE. 1 August 2026. ----
        #
        # The first version keyed on (text, tuple of symbols), and the
        # stored symbol lists repeat themselves -- a card hashtagged
        # twice stores "GHCL,GHCL". ('GHCL',) and ('GHCL','GHCL') are
        # different tuples, so the same sentence appeared twice in
        # GHCL's row:
        #
        #     GHCL — Q1 FY27   Earnings 360 07:51
        #     GHCL — Q1 FY27   Earnings 360 07:51
        #
        # Keying inside each symbol's own list removes that and also
        # catches the same story arriving on two channels.
        symbols = list(dict.fromkeys(
            s.strip().upper() for s in (symbols or []) if s and s.strip()))
        # A whole-session page is not news about one company, whichever
        # tickers it happens to list.
        if _WHOLE_SESSION.search(line):
            symbols = []
        # A MACHINE READING A SCREENSHOT AND A HUMAN TYPING A SENTENCE
        # ARE NOT THE SAME KIND OF EVIDENCE, and the operator has to be
        # able to tell which he is looking at. The old panel labelled
        # it; a shorter table is no reason to stop.
        item = {"text": line, "source": source or "", "time": _hhmm(at, today),
                "at": str(at or ""), "from_image": bool(from_image)}
        if not symbols:
            if _key(line) in market_seen:
                return
            market_seen.add(_key(line))
            market.append(item)
            return
        for symbol in symbols:
            row = by_symbol.setdefault(
                symbol, {"symbol": symbol, "items": [], "at": "",
                         "time": "", "_seen": set()})
            if _key(line) in row["_seen"]:
                continue
            row["_seen"].add(_key(line))
            row["items"].append(item)
            if str(at or "") > row["at"]:
                row["at"], row["time"] = str(at or ""), _hhmm(at, today)

    for row in (rss_rows or []):
        take(row.get("headline") or row.get("title"),
             row.get("source") or "RSS",
             row.get("at") or row.get("published_at"),
             row.get("symbols") or ([row["symbol"]] if row.get("symbol")
                                    else []))

    for row in (telegram_rows or []):
        typed = (row.get("text") or "").strip()
        read = (row.get("ocr_text") or "").strip()
        take(typed or read or row.get("headline"),
             row.get("channel") or "Telegram",
             row.get("at"), row.get("symbols") or [],
             from_image=bool(read and not typed))

    stocks = sorted(by_symbol.values(), key=lambda r: r["at"], reverse=True)
    for row in stocks:
        # Newest first inside the cell too, so the top line of a row is
        # the most recent thing known about that stock.
        row["items"].sort(key=lambda i: i["at"], reverse=True)
        row["count"] = len(row["items"])
        row["items"] = row["items"][:MAX_ITEMS_PER_SYMBOL]
        # Working set, not payload -- and a set is not JSON.
        row.pop("_seen", None)

    market.sort(key=lambda i: i["at"], reverse=True)
    return {"stocks": stocks[:limit], "market": market[:limit],
            "stock_count": len(by_symbol), "market_count": len(market)}
