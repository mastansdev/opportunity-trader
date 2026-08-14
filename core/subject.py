"""
==========================================================
Is this card ABOUT the stock, or does it merely mention it?
==========================================================

    "0 knowlede is far better than half knowledge"
                                -- operator, 8 August 2026

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"
    "so pls do not miss or club one data to other stock"

WHAT WENT WRONG
---------------
Measured 8 August against the real store. core/result_read.py builds a
stock's chip from every message TAGGED with that symbol, and the tag
means "this text mentions the company" -- not "this text is about it".

    SIEMENS   22 messages feed its chip, 4 of them about ENRIN
              (Siemens Energy India -- a different listed company)

    and inside SIEMENS's own chip:
        "PAT -100% YoY"
        "a 22% YoY net profit rise to Rs 518 Cr as soft like-for-like
         fashion volume growth"

That second line is TRENT. A retailer's like-for-like fashion volumes,
scored into an engineering company's earnings chip, which then read
AVOID at -1.2.

    GLAND     14 messages, 5 about NEULANDLAB -> "Revenue +2008% YoY",
              a number only reachable by comparing two companies
    TOTAL     38 messages, 5 about DMART -- the word "total" in a
              D-Mart card read as the ticker TOTAL, which is real

Of 1,824 single-stock cards in the store, 560 carry a symbol that does
not match the card's own hashtag.

THE RULE
--------
The pro channels declare their own subject. Every Pulse channel opens
with #STOCKNAME, and the operator said so in as many words:

    "ALL PULSE CHANNEL FOLLOWS THE #STOCKNAME"

So the card's hashtag is authoritative. If a card says #NEULANDLAB, it
is about Neuland -- whatever else its body happens to name.

    hashtags present, ours among them   -> SUBJECT, keep
    hashtags present, ours absent       -> MENTION, drop
    no hashtags at all                  -> fall back to the headline
                                           position, same rule as
                                           core/forwarded_card.py

WHAT THIS COSTS
---------------
Some chips will go blank. A stock whose only coverage was ambiguous
will show nothing instead of showing something wrong. That is the
trade he chose, in his words, when he saw what the wrong version was
producing.

Author : H&M Opportunity Trader
==========================================================
"""

import re

# A card's own declaration of what it is about.
_HASHTAG = re.compile(r"#([A-Za-z][A-Za-z0-9&_.]{1,24})")

# Hashtags that are topics, not companies. Seen in the real store:
# #STOCKSTOWATCH, #MORNINGMARKETWITHDTT, #1QWithCNBCTV18.
_TOPIC_TAGS = {
    "STOCKSTOWATCH", "STOCKSINNEWS", "TRADING", "NIFTY", "SENSEX",
    "BANKNIFTY", "MARKET", "MARKETS", "NEWS", "BREAKING", "RESULTS",
    "EARNINGS", "MORNINGMARKETWITHDTT", "TODAY", "LIVE", "ALERT",
    "IPO", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK",
}

# A card that names this many companies is a LIST -- an earnings
# calendar, a sector recap, a stocks-to-watch board. It is about all of
# them and therefore about none of them, so it must not feed any single
# stock's chip. Measured: the "Week Ahead" calendar names 155.
LIST_CARD_TAGS = 5

# A roundup naming this many companies with no identifiable subject is
# a digest, not a story about any one of them. Two is deliberately
# still allowed -- a genuine head-to-head comparison is about both.
DIGEST_CARD_TAGS = 3

# How much of an untagged card counts as its headline. A result card
# names its company in the first line; a name 300 characters in is a
# peer, a customer or a table row.
HEADLINE_CHARS = 90

# Cards that are boards by nature -- they list many companies and
# belong to none of them. Taken verbatim from the real store.
_BOARDS = re.compile(
    r"THE\s+WEEK\s+AHEAD|EARNINGS\s+CALENDAR|PULSE\s+RECAP|"
    r"AFTER\s+MARKET\s+HOURS|BEFORE\s+MARKET\s+HOURS|"
    r"OPPORTUNITIES|STOCKS?\s+TO\s+WATCH|STOCKS?\s+IN\s+NEWS|"
    r"MARKET\s+INDEX|TOP\s+GAINERS|TOP\s+LOSERS|GAPPING\s+UP|"
    r"MARKET\s+SENTIMENT\s+FOR|ORDERBOOK\s+RECAP|DAILY\s+HIGHLIGHTS",
    re.I)

_names_cache = {}


def _is_a_board(body):
    """A multi-company board, whatever it happens to mention."""
    return bool(_BOARDS.search(body or ""))


def _clean_keep_spaces(text):
    return re.sub(r"[^A-Z0-9 ]", " ", str(text or "").upper())


def _registered_names(symbol):
    """How this company is actually written out, from the NSE master.

    'GMDCLTD' never appears on its own card -- 'GUJARAT MINERAL
    DEVELOPMENT CORPORATION' does.
    """
    symbol = _clean(symbol)
    if symbol in _names_cache:
        return _names_cache[symbol]
    names = []
    try:
        from core.master_loader import MasterLoader
        if "__loader__" not in _names_cache:
            _names_cache["__loader__"] = MasterLoader()
        row = _names_cache["__loader__"].get_by_symbol(symbol) or {}
        # ---- READ THE KEY, DO NOT GUESS IT. 8 August 2026. ----
        # The first version listed SYMBOL_NAME / DISPLAY_NAME / SM_NAME
        # from memory. The master's column is "COMPANY NAME", with a
        # space, so every lookup returned nothing and FORTIS, GMDCLTD
        # and every other image-only card stayed dropped. Checked
        # against the real master before this shipped.
        for key in ("COMPANY NAME", "COMPANY_NAME", "NAME",
                    "SYMBOL_NAME", "DISPLAY_NAME", "SM_NAME"):
            value = _clean_keep_spaces((row or {}).get(key) or "")
            value = re.sub(r"\s+(LTD|LIMITED|INDIA|CORP)\s*$", "",
                           value).strip()
            # Two significant words is enough to identify, and short
            # enough to survive the OCR mangling the rest of the line.
            parts = [p for p in value.split() if len(p) > 2][:3]
            if len(parts) >= 2:
                candidate = " ".join(parts[:2])
                if candidate not in names:
                    names.append(candidate)
    except Exception:                                      # noqa: BLE001
        pass
    _names_cache[symbol] = names
    return names


def _name_index():
    """[(cleaned name, symbol)] for the whole NSE master, longest first.

    Built once. Longest-first is the whole point: "SIEMENS ENERGY"
    must be tested before "SIEMENS", or the shorter name claims every
    card belonging to the longer one.
    """
    if "__index__" in _names_cache:
        return _names_cache["__index__"]
    index = []
    claims = {}
    try:
        from core.master_loader import MasterLoader
        loader = _names_cache.get("__loader__")
        if loader is None:
            loader = MasterLoader()
            _names_cache["__loader__"] = loader
        # ---- THE REAL ACCESSOR, READ NOT GUESSED. 8 August 2026 ----
        # all_rows/rows/records do not exist on MasterLoader. It keeps
        # _by_symbol and exposes all_symbols() + get_by_symbol(). This
        # is the third API name I have written from memory in this
        # project and the third that was wrong; checked in the source
        # before shipping.
        rows = []
        try:
            # all_symbols() does NOT lazy-load -- only get_by_symbol()
            # does. Without this the index came back empty and every
            # headline owner was None.
            if not getattr(loader, "_by_symbol", None):
                loader.load()
            for sym in loader.all_symbols(include_blocked=True) or []:
                row = loader.get_by_symbol(sym)
                if row:
                    rows.append(row)
        except Exception:                                  # noqa: BLE001
            rows = list((getattr(loader, "_by_symbol", {}) or {}).values())
        for row in (rows or []):
            symbol = _clean((row or {}).get("SYMBOL"))
            raw = (row or {}).get("COMPANY NAME") or ""
            name = _clean_keep_spaces(raw)
            name = re.sub(r"\s+(LTD|LIMITED|LIMITE|L)\s*$", "", name).strip()
            name = re.sub(r"\s+", " ", name)
            if not symbol:
                continue
            if len(name) >= 5:
                _add(claims, name, symbol)
            # ---- TWO-WORD PREFIXES. 8 August 2026. ----
            # ENRIN is "SIEMENS ENERGY INDIA LTD" but the card says
            # "SIEMENS ENERGY: CO SAYS...". The full name never
            # matches, so the shorter "SIEMENS" won and six Siemens
            # Energy cards landed in Siemens Ltd's chip. Indexing the
            # first two words gives "SIEMENS ENERGY" -> ENRIN, which
            # is longer than "SIEMENS" and therefore wins.
            words = name.split()
            if len(words) >= 3:
                _add(claims, " ".join(words[:2]), symbol)
            if len(symbol) >= 4:
                _add(claims, symbol, symbol)
    except Exception:                                      # noqa: BLE001
        claims = {}

    # A phrase claimed by two different companies identifies neither.
    for phrase, owners in claims.items():
        if len(owners) == 1:
            index.append((phrase, next(iter(owners))))
    index.sort(key=lambda pair: -len(pair[0]))
    _names_cache["__index__"] = index
    return index


def _add(claims, phrase, symbol):
    phrase = re.sub(r"\s+", " ", str(phrase or "")).strip()
    if len(phrase) >= 4:
        claims.setdefault(phrase, set()).add(symbol)


def _headline_owner(head):
    """Which company does this headline name most specifically?

    None when no listed company is recognisable, which sends the
    caller to its softer fallbacks rather than refusing outright.
    """
    text = " " + re.sub(r"\s+", " ", _clean_keep_spaces(head)) + " "
    for name, symbol in _name_index():
        if f" {name} " in text:
            return symbol
    return None


def _clean(tag):
    """Letters and digits only.

    ---- & AND _ BOTH GO. 8 August 2026. ----
    Keeping "&" made M&M and #M_M different strings, so every Mahindra
    card was dropped as a mention. The channels write the same company
    as M&M, M_M and M-M depending on whether the platform allows the
    ampersand in a hashtag.

    This does NOT loosen the similar-name rule: M&M cleans to MM and
    M&MFIN cleans to MMFIN, so Mahindra and Mahindra Finance still do
    not match each other -- which is correct, they are separate
    listings and the Breakouts channel has already confused them once.
    """
    return re.sub(r"[^A-Z0-9]", "", str(tag or "").upper())


def declared(text):
    """The company hashtags a card puts on itself, topics removed."""
    out = []
    for raw in _HASHTAG.findall(str(text or "")):
        tag = _clean(raw)
        if len(tag) >= 2 and tag not in _TOPIC_TAGS and not tag.isdigit():
            if tag not in out:
                out.append(tag)
    return out


def _same(symbol, tag):
    """Is this hashtag the same company as this symbol?

    Deliberately strict. UNOMINDA and MINDACORP are different
    companies; WELCORP and WELENT are different companies. Only exact
    matches after punctuation is stripped, so M&M and #M_M agree while
    GLAND and #NEULANDLAB do not.
    """
    return _clean(symbol) == _clean(tag)


def is_about(symbol, text):
    """True when this text is ABOUT `symbol`, not merely mentioning it.

    Returns False for a list card regardless of whether the symbol is
    on it -- an earnings calendar naming 155 companies is not evidence
    about any one of them.
    """
    symbol = _clean(symbol)
    if not symbol:
        return False
    tags = declared(text)

    if len(tags) >= LIST_CARD_TAGS:
        return False

    body_upper = str(text or "").upper()
    if _is_a_board(body_upper):
        return False

    # ---- THE HEADLINE OUTRANKS THE HASHTAG. 8 August 2026. ----
    #
    # Four Siemens Energy stories survived every other guard because
    # News Pulse tagged them #SIEMENS:
    #
    #     "#SIEMENS  Siemens Energy India's Q3 net profit surged 68%"
    #     "#SIEMENS  Siemens Energy India shares jumped over 7%"
    #
    #     "NEWS PULSE IS NOT THE WORTH TIME TO SPEND . THAT CHANNEL IS
    #      ALSO RSS LIKE OURS & STOCK TAGS DIFFER I CHECKED MANUALLY"
    #                                            -- operator, 8 Aug
    #
    # He had already found this by hand. A hashtag is an aggregator's
    # guess; the first line of the story is what the story is about.
    # So when the headline names a listed company UNAMBIGUOUSLY and it
    # is not us, the card is not ours -- whatever the tag says.
    #
    # This cannot misfire on a mangled Pulse card: _headline_owner
    # needs an exact phrase match against the NSE master, so OCR
    # damage returns None and the hashtag rule below still applies.
    owner = _headline_owner(body_upper[:HEADLINE_CHARS])
    if owner is not None and owner != symbol:
        # ---- UNLESS THE CARD DECLARED BOTH. 8 August 2026. ----
        # "#HDFCBANK and #ICICIBANK both report margin expansion" has
        # one headline owner and two legitimate subjects. Rejecting
        # the loser would throw away half of every comparison card.
        #
        # The override only fires when the headline names someone the
        # tags do NOT -- which is exactly the News Pulse failure:
        # tagged #SIEMENS, headline owned by ENRIN, ENRIN absent from
        # the tags. That is a mis-tag, not a comparison.
        declared_owner = any(_same(owner, tag) for tag in tags)
        if not (declared_owner and any(_same(symbol, tag) for tag in tags)):
            return False

    # ---- A DIGEST IS NOT EVIDENCE. 8 August 2026. ----
    #
    #     "🚀 Behari Lal Engineering has set its IPO price band..."
    #     tagged #CRIMSON #CROMPTON #SIEMENS
    #     "Siemens Energy" appears 157 characters in
    #
    #     "EARNINGS & RESULTS - State Bank of India is expected to
    #      report Q1 earnings today..."   tagged #SBIN #SIEMENS #GOKEX
    #
    # The second one HAS a headline owner (SBIN) -- it is simply the
    # first story in the roundup. So the digest test cannot depend on
    # the owner being unknown; three company tags is itself the tell.
    #
    # Three unrelated companies, several stories, no single subject --
    # News Pulse's roundup format. Under the 5-tag list threshold, and
    # no headline owner to arbitrate. Whichever stock asked, the answer
    # is that this card is not about it.
    #
    # Two tags stay allowed: a genuine comparison ("#HDFCBANK and
    # #ICICIBANK both report margin expansion") is about both.
    if len(tags) >= DIGEST_CARD_TAGS:
        return False

    if tags:
        # The card declared itself and nothing contradicts it.
        return any(_same(symbol, tag) for tag in tags)

    # ---- AN IMAGE HAS NO HASHTAG. 8 August 2026. ----
    #
    # The hashtag lives in the message CAPTION; the card itself is a
    # picture, and its OCR text carries the company in plain words:
    #
    #     "FORTIS HEALTHCARE Q1 CONS EARNINGS REPORT CARD Profit..."
    #     "IXIGO Q1FY27 expectations Bullish 30%+ GTV growth..."
    #     "Gujarat Mineral Development Corporation"
    #
    # The first version dropped all three -- FORTIS, IXIGO and GMDCLTD
    # each lost every card they had and went blank. That is not "0
    # knowledge better than half knowledge", that is throwing away
    # good knowledge, and it is the opposite failure to the one this
    # module exists to fix.
    #
    # So: no hashtags means look at the HEADLINE, and accept either the
    # ticker or the registered company name there.
    body = str(text or "").upper()
    if _is_a_board(body):
        return False

    head = body[:HEADLINE_CHARS]

    # ---- LONGEST NAME WINS. 8 August 2026. ----
    #
    # A plain "is SIEMENS in the headline" test kept 8 Siemens ENERGY
    # cards out of 13 for SIEMENS, because the ticker is a prefix of a
    # different listed company:
    #
    #     "SIEMENS ENERGY: CO SAYS WE WILL..."          -> ENRIN
    #     "Siemens Energy India Ltd Q3 FY2026"          -> ENRIN
    #     "SIEMENS: SEES SURGE IN DATA CENTER..."       -> SIEMENS
    #
    # Same trap as UNO MINDA vs MINDA CORP and WELSPUN CORP vs WELSPUN
    # ENTERPRISES. So we ask which company the headline names MOST
    # specifically, and only that one owns the card.
    owner = _headline_owner(head)
    if owner is not None:
        return owner == symbol

    for name in _registered_names(symbol):
        if name and name in head:
            return True

    # Last resort: the forwarded-screenshot headline reader, which
    # handles "@REDBOXINDIA  ELECTROSTEEL CASTINGS: Q1 CONS NET..."
    try:
        from core import forwarded_card
        got = forwarded_card.read(text)
        if got.get("kind") != "COMPANY":
            return False
        subjects = [_clean(s) for s in got.get("subjects") or []]
        return any(symbol == s or (len(symbol) >= 4 and symbol in s)
                   for s in subjects)
    except Exception:                                      # noqa: BLE001
        return False


def only(symbol, messages):
    """Keep the (channel, text) pairs that are ABOUT this stock.

    This is the gate result_read should have had from the first day.
    """
    kept = []
    for item in (messages or []):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            channel, text = item[0], item[1]
        else:
            channel, text = None, item
        if is_about(symbol, text):
            kept.append((channel, text))
    return kept


def audit(symbol, messages):
    """{"kept", "dropped", "why"} -- so a blank chip can be explained.

    A chip that vanishes must be able to say why it vanished, or it is
    just a different kind of silence.
    """
    kept, dropped, lists = 0, 0, 0
    for item in (messages or []):
        text = item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 \
            else item
        if len(declared(text)) >= LIST_CARD_TAGS:
            lists += 1
            dropped += 1
        elif is_about(symbol, text):
            kept += 1
        else:
            dropped += 1
    return {"kept": kept, "dropped": dropped, "list_cards": lists,
            "why": (f"{kept} card(s) about {symbol}, {dropped} dropped "
                    f"as mentions" + (f" ({lists} list cards)" if lists
                                      else ""))}
