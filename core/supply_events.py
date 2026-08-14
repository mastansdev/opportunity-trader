"""
==========================================================
Huge volume that is SUPPLY, not demand
==========================================================

    "lic is hitting with more volumes due to some ofs news . so again
     we had some thing to resolve"
                                -- operator, 8 August 2026

WHAT HAPPENED
-------------
LICI was picked on four of five replayed days -- 165x, 86x, 65x its
own first-minute volume, the largest institutional flow on the board
each time. It lost on every one:

    04 Aug   -171     06 Aug   -278
    07 Aug   -536     and a stop-out

The volume filter was working perfectly. It found the biggest flow in
the market. What it could not tell is that the flow was SUPPLY.

And the bot was holding the answer the whole time. In data/telegram.db
since 3 August, 23:44:

    "The Government of India will launch an Offer For Sale..."
    "Life Insurance Corporation of India's (LIC) Offer..."

An OFS is a large block coming to market at a DISCOUNT to the screen
price. It produces exactly the signature the bot hunts -- enormous
volume, institutional participation, sustained through the session --
and the price is pushed DOWN, because the whole event is somebody
selling.

THE DISTINCTION THIS ADDS
-------------------------
Every event the bot reads is one of two kinds, and they have identical
volume signatures:

    DEMAND     results, order wins, business updates, upgrades
               -> someone wants the stock

    SUPPLY     OFS, QIP, block deal, stake sale, promoter selling,
               lock-in expiry, pledge invocation
               -> someone needs to get OUT of the stock

    "i only trade in long positions"

So a supply event is not a weaker buy. It is not a buy at all,
whatever the volume says.

WHY MATCHING IS DELIBERATELY STRICT
-----------------------------------
A false positive here costs a good trade. A missed one costs money on
a stock that cannot go up. So the phrases are the ones that actually
appear in his channels, matched whole, and the symbol has to be the
SUBJECT of the message -- core/subject.py -- not merely mentioned in
it. A market wrap listing ten OFS candidates must not blacklist all
ten.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import sqlite3
from datetime import datetime, timedelta

TELEGRAM_DB = "data/telegram.db"

# messages.at is UTC; the clock is IST. Same offset core/catalysts.py
# had to learn on 8 August.
IST_OFFSET = timedelta(hours=5, minutes=30)

# A stake sale overhangs the stock until it is done and absorbed. Two
# sessions is the window where the discount is still being filled.
FRESH_HOURS = 60.0

# ---- WHAT SELLING LOOKS LIKE IN HIS CHANNELS ----
# Whole-phrase matches only. "STAKE" alone appears in ordinary
# commentary; "STAKE SALE" does not.
_SUPPLY = (
    (r"\bOFS\b", "an offer for sale is on -- a block is coming to market"),
    (r"OFFER\s+FOR\s+SALE", "an offer for sale is on -- a block is coming "
                            "to market"),
    (r"STAKE\s+SALE", "a stake sale is on -- somebody large is exiting"),
    (r"BLOCK\s+DEAL", "a block deal -- size changing hands off-screen"),
    (r"\bQIP\b", "a QIP -- new shares being issued into the market"),
    (r"QUALIFIED\s+INSTITUTIONAL\s+PLACEMENT",
     "a QIP -- new shares being issued into the market"),
    (r"PROMOTER[S']?\s+(?:SELL|SELLING|SOLD|PARE|OFFLOAD|TRIM)",
     "the promoter is selling"),
    (r"(?:SELLS?|SOLD|OFFLOAD(?:S|ED)?)\s+(?:\d[\d.,]*\s*%\s+)?STAKE",
     "a stake is being sold"),
    (r"LOCK[- ]?IN\s+EXPIR", "lock-in expiry -- held shares become "
                             "sellable"),
    (r"PLEDGE[D]?\s+SHARES?\s+(?:INVOK|SOLD)", "pledged shares invoked"),
    (r"DIVEST(?:MENT|ING)\s+(?:STAKE|SHARES)", "a divestment is under way"),
)

# Buying back is the opposite and must never be caught by the above.
_DEMAND_OVERRIDE = re.compile(
    r"BUY\s*-?\s*BACK|BUYBACK|PROMOTER[S']?\s+(?:BUY|BOUGHT|ACQUIR|RAIS"
    r"(?:E|ES|ED)\s+STAKE)|OPEN\s+OFFER\s+TO\s+ACQUIRE", re.I)

_compiled = [(re.compile(p, re.I), why) for p, why in _SUPPLY]


def read(text):
    """{"supply", "why"} for one message. None when it is not selling."""
    body = str(text or "")
    if not body.strip():
        return None
    if _DEMAND_OVERRIDE.search(body):
        # A buyback is the mirror image -- shares LEAVING the market.
        return None
    for pattern, why in _compiled:
        hit = pattern.search(body)
        if hit:
            # ---- SHOW THE EVIDENCE, NOT THE FIRST 140 CHARS ----
            # 8 August: LICI's 7 August match quoted a Q1 results card
            # whose visible text contained no supply phrase at all --
            # the trigger was further into the message and the stored
            # snippet made it impossible to check. Evidence that cannot
            # be verified is not evidence.
            start = max(hit.start() - 70, 0)
            excerpt = re.sub(r"\s+", " ", body[start:hit.end() + 70]).strip()
            return {"supply": True, "why": why,
                    "matched": hit.group(0),
                    "excerpt": excerpt}
    return None


def _rows(db_path, sql, args=()):
    try:
        con = sqlite3.connect(db_path)
        got = con.execute(sql, args).fetchall()
        con.close()
        return got
    except Exception:                                      # noqa: BLE001
        return []


_cache = {}


def overhang(symbol, now=None, db_path=TELEGRAM_DB, hours=FRESH_HOURS):
    """Is this stock under a supply event right now? {"why"} or None.

    The answer a long-only bot needs before it reads the volume: is
    this flow somebody buying, or somebody leaving.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return None
    now = now or datetime.now()
    now_utc = now - IST_OFFSET
    cutoff = (now_utc - timedelta(hours=hours)).isoformat()
    ceiling = now_utc.isoformat()

    key = (symbol, cutoff[:13], ceiling[:13], db_path)
    if key in _cache:
        return _cache[key]

    # ---- ONE SCAN PER WINDOW, NOT ONE PER SYMBOL. 9 Aug 2026. ----
    #
    # Wiring this into core/auto_entry.py put it on the live entry
    # path, and the first version re-ran the LIKE scan for every
    # candidate: 150ms each, about 3 SECONDS for a cycle of 20. That is
    # the same hazard I created on 8 August with a DB open per symbol
    # per cycle, measured at 7.59s a pass, and told him I had fixed.
    #
    # The window is identical for every symbol in a cycle. Read it
    # once, keep it, and match symbols against it in memory.
    found = _owners(db_path, cutoff, ceiling).get(_flat(symbol))

    # ---- THE INDEX IS A FAST PATH, NOT THE ANSWER. 10 Aug 2026. ----
    #
    # The index resolves a message by its #HASHTAG or by the master's
    # registered company name. core/subject.is_about() knows more than
    # both -- and LICI proves it: NSE abbreviates the company to
    # "LIFE INSURA CORP OF INDIA" while the notice says "Life Insurance
    # Corporation of India", so no name match exists, yet is_about()
    # still answers True through its softer fallbacks.
    #
    # Dropping those fallbacks to go faster would have un-blocked the
    # exact stock this module was written for. So: index first, and
    # when it says nothing, ask the real judge once for this symbol and
    # remember the answer.
    #
    # The cost is bounded. This runs only on candidates that already
    # cleared every other gate -- a handful a cycle -- and the per
    # (symbol, hour) cache above means each is asked once an hour.
    if found is None:
        found = _ask_subject(symbol, db_path, cutoff, ceiling)

    if len(_cache) > 4000:
        _cache.clear()
    _cache[key] = found
    return found


def _ask_subject(symbol, db_path, cutoff, ceiling):
    """The slow, complete test -- one symbol, once per hour."""
    try:
        from core import subject
    except Exception:                                      # noqa: BLE001
        return None
    for body, ocr, at in _window(db_path, cutoff, ceiling):
        text = f"{body} {ocr}"
        got = read(text)
        if not got:
            continue
        try:
            if not subject.is_about(symbol, text):
                continue
        except Exception:                                  # noqa: BLE001
            continue
        return {"why": got["why"], "at": at,
                "matched": got.get("matched"),
                "text": got.get("excerpt") or
                        re.sub(r"\s+", " ", text).strip()[:140]}
    return None


def _flat(symbol):
    return re.sub(r"[^A-Z0-9]", "", str(symbol or "").upper())


_owner_index = {}


def _owners(db_path, cutoff, ceiling):
    """{symbol: event} for the whole window. Built ONCE.

    ==========================================================
    WHY THIS IS INVERTED.  10 August 2026.
    ==========================================================
    The first version asked, for every candidate: "is any supply
    message about YOU?" -- which ran core/subject.is_about() once per
    candidate per message, at about 57 ms a call. Twenty candidates
    cold was 1.15 seconds and the test suite stopped finishing, so the
    gate was written, wired, and switched OFF on 9 August.

    The question is the wrong way round. A supply message names its own
    subject. So ask each MESSAGE who it is about -- a handful of
    hashtags, resolved once -- and the per-candidate answer becomes a
    dictionary lookup.

    WHAT THIS COVERS, AND WHAT IT DOES NOT
    --------------------------------------
    Cards that declare themselves with a #HASHTAG, which is every
    channel he trusts: "ALL PULSE CHANNEL FOLLOWS THE #STOCKNAME".
    is_about() still decides -- a market wrap listing ten OFS names is
    still refused for all ten, because is_about() refuses a list card.

    A supply message carrying NO hashtag at all is not indexed here.
    That is a real gap and it is stated rather than hidden: it means a
    missed block, never a wrong one. A missed block costs what LICI
    cost; a wrong one refuses a good trade forever.
    """
    key = (db_path, cutoff[:13], ceiling[:13])
    if key in _owner_index:
        return _owner_index[key]

    out = {}
    try:
        from core import subject
    except Exception:                                      # noqa: BLE001
        return out

    for body, ocr, at in _window(db_path, cutoff, ceiling):
        text = f"{body} {ocr}"
        got = read(text)
        if not got:
            continue
        event = {"why": got["why"], "at": at,
                 "matched": got.get("matched"),
                 "text": got.get("excerpt") or
                         re.sub(r"\s+", " ", text).strip()[:140]}
        try:
            tags = subject.declared(text)
        except Exception:                                  # noqa: BLE001
            continue
        claimed = False
        for tag in tags:
            flat = _flat(tag)
            if not flat or flat in out:
                continue
            try:
                if subject.is_about(tag, text):
                    out[flat] = event
                    claimed = True
            except Exception:                              # noqa: BLE001
                continue

        # ---- THE ONE THAT MATTERS HAS NO HASHTAG. 10 Aug 2026. ----
        #
        # The hashtag pass alone was fast and WRONG: LICI stopped being
        # blocked. Its notice is plain prose --
        #
        #     "Life Insurance Corporation of India's (LIC) Offer for
        #      Sale (OFS) opens on August 4..."
        #
        # -- with no #LICI anywhere. That is the exact message this
        # whole module was written for, on the exact stock that lost on
        # four of five replayed days. A faster gate that misses it is
        # not a gate.
        #
        # subject._headline_owner() already resolves prose to a company
        # against the master's own name index, longest name first, so
        # "SIEMENS ENERGY" beats "SIEMENS". Run ONCE per message, not
        # once per candidate -- which is the whole point of inverting
        # the question.
        if not claimed:
            try:
                owner = subject._headline_owner(text[:400])
            except Exception:                              # noqa: BLE001
                owner = None
            if owner:
                out.setdefault(_flat(owner), event)

    if len(_owner_index) > 8:
        _owner_index.clear()
    _owner_index[key] = out
    return out


_windows = {}


def _window(db_path, cutoff, ceiling):
    """Every possibly-supply message in this window. Read once."""
    key = (db_path, cutoff[:13], ceiling[:13])
    if key in _windows:
        return _windows[key]
    rows = _rows(
        db_path,
        "select coalesce(text, ''), coalesce(ocr_text, ''), at "
        "from messages where at >= ? and at <= ? "
        "and (upper(coalesce(text,'') || coalesce(ocr_text,'')) like '%OFS%' "
        "  or upper(coalesce(text,'') || coalesce(ocr_text,'')) "
        "     like '%OFFER FOR SALE%' "
        "  or upper(coalesce(text,'') || coalesce(ocr_text,'')) "
        "     like '%STAKE%' "
        "  or upper(coalesce(text,'') || coalesce(ocr_text,'')) "
        "     like '%BLOCK DEAL%' "
        "  or upper(coalesce(text,'') || coalesce(ocr_text,'')) "
        "     like '%QIP%') "
        "order by at desc limit 300",
        (cutoff, ceiling))

    # Only messages that actually READ as supply are kept, so the
    # per-symbol loop above does the subject test and nothing else.
    kept = []
    for body, ocr, at in rows:
        text = f"{body} {ocr}"
        if read(text):
            kept.append((body, ocr, at))

    if len(_windows) > 8:
        _windows.clear()
    _windows[key] = kept
    return kept
