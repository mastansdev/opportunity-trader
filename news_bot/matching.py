"""
==========================================================
News Bot -- Stage 2: Matching (free, rule-based, no AI)
==========================================================

Checks every ingested NewsItem against the verified 750-
stock master database. Anything that matches nothing is
DUMMY and never costs an AI call. Anything that matches is
handed to Stage 3 (AI classification -- not built yet).

Two match tiers, kept separate so later stages know how much
to trust a match:

  COMPANY -- the headline names one specific company (its
      COMPANY NAME or SYMBOL appeared). High confidence,
      single stock (or a small handful, if names collide).

  BROAD -- the headline matched a SECTOR, INDUSTRY, KEYWORDS,
      THEMES, or COMMODITY_EXPOSURE term. Lower per-stock
      confidence (one headline can match dozens of stocks --
      e.g. a crude-oil price move), but real and worth
      keeping. Stage 3/4 decide materiality, not this stage.

KNOWN LIMITATION (documented, not hidden): many COMPANY NAME
values in master_stocks.csv are the abbreviated/truncated
names as stored in the Dhan scrip master (e.g. "ZF COM VE CTR
SYS IND LTD", "UJJIVAN SMALL FINANC BANK"), not the full legal
name a news article would use. Exact-phrase matching against
those truncated names will under-match. SYMBOL matching and
SECTOR/INDUSTRY/KEYWORDS/THEMES/COMMODITY matching carry more
of the real-world load until/unless the COMPANY NAME field is
separately enriched with full legal names.

Author : H&M Opportunity Trader
==========================================================
"""

import re

from core.master_loader import MasterLoader
from news_bot.config import NEWS_ENABLE_BROAD_TIER
from news_bot.models import MatchedNews, MatchResult

_CORP_SUFFIXES = {
    "LIMITED", "LTD", "LTD.", "LLP", "CO", "CO.", "CORP", "CORP.",
    "PVT", "PVT.", "PRIVATE", "INC", "INC.",
}

_MIN_SYMBOL_LEN = 3          # guard against short/generic symbol false-hits
_MIN_COMPANY_TERM_LEN = 3    # guard against 1-2 char normalized names

# NOTE: an earlier version of this file capped a story at 25 symbols and
# DROPPED anything wider. That was wrong -- measured against the real
# universe, legitimate sector news is genuinely wide:
#
#     "Crude oil prices surge"    ->  67 symbols
#     "IT services hiring demand" ->  46 symbols
#     "Steel prices surge"        -> 151 symbols
#
# Deleting those loses real information. The harm was never the WIDTH,
# it was letting a sector story reach HIGH priority and block entries in
# every one of those names. That is fixed where priority is decided --
# see news_bot/priority.py's BROAD rule -- not by throwing the data away.

# Routine exchange housekeeping. Real compliance obligations, zero
# trading information. Checked against the UPPERCASED headline+summary.
_ROUTINE_FILING_MARKERS = (
    "TRADING WINDOW",
    "APPOINTMENT OF", "RESIGNATION OF", "CESSATION OF", "RE-APPOINTMENT",
    "CHANGE IN DIRECTOR", "CHANGE IN MANAGEMENT", "COMPANY SECRETARY",
    "COMPLIANCE CERTIFICATE", "CERTIFICATE UNDER",
    "DISCLOSURE UNDER REGULATION", "DISCLOSURE UNDER SEBI",
    "SCHEDULE OF", "INVESTOR PRESENTATION", "ANALYST MEET",
    "EARNINGS CALL", "CONFERENCE CALL", "AUDIO RECORDING",
    "TRANSCRIPT", "NEWSPAPER PUBLICATION", "NEWSPAPER ADVERTISEMENT",
    "LOSS OF SHARE CERTIFICATE", "DUPLICATE SHARE CERTIFICATE",
    "TRANSFER OF SHARES", "SHARE TRANSFER", "REGISTRAR AND",
    "ANNUAL REPORT", "ANNUAL GENERAL MEETING", "POSTAL BALLOT",
    "RECORD DATE", "BOOK CLOSURE", "SHAREHOLDING PATTERN",
    "INVESTOR COMPLAINT", "GRIEVANCE REDRESSAL",
    "RELATED PARTY", "SECRETARIAL",
)


# A headline that is ABOUT ONE COMPANY, whether or not that company is
# in our 750. Found 2026-07-26, after the first fan-out fix:
#
#   "V-Mart Retail Q1 Results: Profit surges 40%"
#        -> tagged bullish-HIGH on RELIANCE, DMART, ABFRL, ARVINDFASN
#   "Steel Strips Wheels Limited has informed the Exchange..."
#        -> tagged to 131 symbols
#
# Neither company is in our universe, so nothing matched at COMPANY
# tier, so the broad sector patterns ran and sprayed the story across
# the sector. V-Mart's profit says nothing about Reliance.
#
# If a headline names a company and we cannot resolve it, the correct
# answer is SILENCE.
_COMPANY_STORY_MARKERS = (
    " LIMITED", " LTD", " PVT", " INC.", " CORP",
    "HAS INFORMED THE EXCHANGE", "HAS SUBMITTED TO THE EXCHANGE",
    "INFORMED THE EXCHANGE", "SUBMITTED TO THE EXCHANGE",
)

_QUARTER_RESULT_RE = re.compile(r"\bQ[1-4]\s+RESULTS?\b")


def is_company_story(text):
    """True when the headline is about one named company."""
    upper = str(text or "").upper()
    if _QUARTER_RESULT_RE.search(upper):
        return True
    return any(marker in upper for marker in _COMPANY_STORY_MARKERS)


# MARKET COMMENTARY -- 2026-07-26, second operator report. The live feed
# showed this, identical text on three unrelated stocks:
#
#   UPL / TIMETECHNO / GESHIP   bullish 55% MID
#   "US stock market today: S&P 500, Nasdaq futures edge higher as oil
#    retreats; Intel jumps 4%"      keyword match: gains, jumps, higher
#
# Intel's move says nothing about UPL. The headline matched on a
# commodity keyword, and the classifier then read the generic price
# verbs ("jumps", "higher") as a bullish signal for each.
#
# Every one of the 18 commonest headlines in the store was this shape:
# index wraps, global markets, commodity price reports, IPO coverage,
# and stories about a single unnamed share. All sprayed across 20-114
# symbols. None is a per-stock signal.
# Two strengths, because they need different treatment.
#
# HARD -- the headline IS commentary, whoever it mentions. "Market wrap:
# HCLTech, Bajaj Finance, Eternal among top gainers" names three of our
# stocks and is still just a gainers list. Dropped before any matching.
_HARD_COMMENTARY = (
    "STOCK MARKET TODAY", "MARKET TODAY", "MARKETS TODAY", "MARKET WRAP",
    "STOCKS TODAY", "WALL STREET", "CLOSING BELL", "OPENING BELL",
    "STOCKS TO WATCH", "TOP GAINERS", "TOP LOSERS",
    "PENNY STOCK", "MULTIBAGGER", "SHOULD YOU BUY", "SHOULD YOU INVEST",
    "SHARES TO BUY", "STOCKS THAT",
    # primary market -- not listed, not tradeable by us
    "IPO", "GMP", "LISTING GAINS", "ISSUE BOOKED", "SUBSCRIBED",
    # commodity / macro price reports
    "PRICES TODAY", "GOLD, SILVER",
)

# SOFT -- an index or macro reference that is often incidental.
# "Reliance shares jump 5% as Sensex rallies" IS about Reliance, so this
# set only applies when the headline named nobody we track.
_SOFT_COMMENTARY = (
    "SENSEX", "NIFTY", "S&P 500", "S&AMP;P 500", "NASDAQ", "DOW JONES",
    "ASIAN MARKETS", "GLOBAL MARKETS", "GLOBAL CUES",
    "PRE-MARKET", "PREMARKET", "MARKET OUTLOOK",
    "BULL MARKET", "BEAR MARKET", "SELL-OFF", "SELLOFF",
    "CRUDE OIL PRICES", "BOND YIELD", "RUPEE VS", "FOREX",
)


def is_hard_commentary(text):
    """Commentary whoever it names -- index wraps, gainers lists, IPOs."""
    upper = str(text or "").upper()
    return any(marker in upper for marker in _HARD_COMMENTARY)


def is_market_commentary(text):
    """Any commentary, hard or soft. Used once nothing has been named."""
    upper = str(text or "").upper()
    return (is_hard_commentary(upper)
            or any(marker in upper for marker in _SOFT_COMMENTARY))


def is_routine_filing(text):
    """
    True for exchange housekeeping that carries no trading signal.

    A results filing is NOT routine and must survive -- check that
    first, because "Financial Results" often appears alongside
    "Newspaper Publication" in the same subject line.
    """
    upper = str(text or "").upper()
    if "RESULT" in upper and "NEWSPAPER" not in upper \
            and "PUBLICATION" not in upper:
        return False
    return any(marker in upper for marker in _ROUTINE_FILING_MARKERS)


def _normalize_company_name(raw_name):
    """Strip trailing corporate-entity suffix tokens (LIMITED,
    LTD, PVT, etc.) from a company name, repeatedly, so
    'WOCKHARDT LIMITED' -> 'WOCKHARDT' and 'ABC PVT LTD' ->
    'ABC'. Leaves genuinely short results (e.g. '3M') as-is --
    the min-length guard in the caller decides if they're
    usable, this function just normalizes."""

    tokens = raw_name.strip().upper().split()
    while tokens and tokens[-1].rstrip(".") in {
        s.rstrip(".") for s in _CORP_SUFFIXES
    }:
        tokens.pop()
    return " ".join(tokens)


def _split_multi(value):
    """Master DB multi-value fields are pipe-delimited, e.g.
    'ALUMINIUM | ZINC | LEAD'. Returns a list of cleaned,
    uppercase terms with 'NONE' dropped."""

    if not value:
        return []
    terms = [t.strip().upper() for t in value.split("|")]
    return [t for t in terms if t and t != "NONE"]


def _word_boundary_pattern(term):
    """Build a case-sensitive-safe word-boundary regex for a
    term that may contain spaces or punctuation (e.g. company
    names, '&', '-'). \\b doesn't reliably bracket non-word
    chars at the edges, so we bracket explicitly instead."""

    escaped = re.escape(term)
    return re.compile(r"(?<![A-Z0-9])" + escaped + r"(?![A-Z0-9])")


class NewsMatcher:
    """Builds its matching indices once from the master
    database, then matches any number of NewsItems against
    them cheaply (no AI, no network)."""

    def __init__(self, loader: MasterLoader = None):
        self.loader = loader or MasterLoader()
        if not self.loader.all_symbols(include_blocked=True):
            self.loader.load()

        # COMPANY tier
        self._company_patterns = []   # list[(compiled_regex, term, symbol)]
        # Matched CASE-SENSITIVELY against the ORIGINAL headline, not the
        # uppercased copy. Found 2026-07-26: "Crude oil prices surge on
        # Middle East supply concerns" matched the symbol OIL (Oil India),
        # which then suppressed the entire genuine sector story. Same
        # family as "ban" inside "Bank".
        #
        # Real tickers appear in headlines in CAPS ("OIL reports Q1");
        # the ordinary English word does not. Company NAMES are matched
        # separately and case-insensitively, so "Oil India Limited" is
        # still caught properly.
        self._symbol_patterns = []    # list[(compiled_regex, symbol)]

        # BROAD tier: field_name -> list[(compiled_regex, term, symbol)]
        self._broad_patterns = {
            "SECTOR": [],
            "INDUSTRY": [],
            "KEYWORDS": [],
            "THEMES": [],
            "COMMODITY_EXPOSURE": [],
        }

        self._build_indices()

    # --------------------------------------------------

    def _build_indices(self):
        # include_blocked=True on purpose. A stock the morning run marked
        # SUBSCRIBE = NO is not TRADED today, but news about it is still
        # worth recording -- it may be back to YES tomorrow, and the news
        # engine runs 24/7 independently of whether we hold a position.
        for symbol in self.loader.all_symbols(include_blocked=True):
            record = self.loader.get_by_symbol(symbol)

            if len(symbol) >= _MIN_SYMBOL_LEN:
                # CASE-SENSITIVE, deliberately -- see the note on
                # _symbol_patterns below.
                self._symbol_patterns.append(
                    (re.compile(r"(?<![A-Za-z0-9])" + re.escape(symbol.upper())
                                + r"(?![A-Za-z0-9])"), symbol)
                )

            norm_name = _normalize_company_name(record["COMPANY NAME"])
            if len(norm_name) >= _MIN_COMPANY_TERM_LEN:
                self._company_patterns.append(
                    (_word_boundary_pattern(norm_name), norm_name, symbol)
                )

            for field, csv_key in (
                ("SECTOR", "SECTOR"),
                ("INDUSTRY", "INDUSTRY"),
                ("KEYWORDS", "KEYWORDS"),
                ("THEMES", "THEMES"),
                ("COMMODITY_EXPOSURE", "COMMODITY_EXPOSURE"),
            ):
                for term in _split_multi(record.get(csv_key, "")):
                    if len(term) < _MIN_COMPANY_TERM_LEN:
                        continue
                    self._broad_patterns[field].append(
                        (_word_boundary_pattern(term), term, symbol)
                    )

    # --------------------------------------------------

    def match(self, item):
        text = f"{item.title} {item.summary}".upper()

        # ROUTINE COMPLIANCE FILINGS -- 2026-07-26.
        # The store held 12,831 rows from 1,034 real headlines, and the
        # commonest were "Trading Window closure", "Appointment of Mr X",
        # "Schedule of analyst call", "Disclosure under Regulation 30".
        # None of those move a price. Dropped before matching, so they
        # cannot fan out either.
        if is_routine_filing(text) or is_hard_commentary(text):
            return MatchedNews(item=item, matches=[])

        results = []
        seen = set()

        def add(symbol, field, term, tier):
            key = (symbol, field, term)
            if key in seen:
                return
            seen.add(key)
            results.append(MatchResult(symbol, field, term, tier))

        # Exchange filings (NSE announcements) tell us the exact
        # symbol directly -- that's ground truth, not a guess, so
        # it's trusted ahead of any text pattern matching. Still
        # validated against the master DB so a bad/unknown symbol
        # from the feed can't silently create a fake match.
        if item.known_symbol:
            record = self.loader.get_by_symbol(item.known_symbol)
            if record is not None:
                add(item.known_symbol, "EXCHANGE_FILING", item.known_symbol, "COMPANY")

        for pattern, term, symbol in self._company_patterns:
            if pattern.search(text):
                add(symbol, "COMPANY_NAME", term, "COMPANY")

        raw = f"{item.title} {item.summary}"
        for pattern, symbol in self._symbol_patterns:
            if pattern.search(raw):          # raw, NOT the uppercased text
                add(symbol, "SYMBOL", symbol, "COMPANY")

        # THE FAN-OUT FIX -- 2026-07-26, operator report.
        #
        # A single Vedanta trading-window notice was stored against 264
        # symbols: ABB, AMBER, ASHOKLEY, BAJAJ-AUTO and every other name
        # whose SECTOR / THEMES / COMMODITY_EXPOSURE mentions steel. It
        # told you nothing whatsoever about ABB.
        #
        # If a headline NAMES a company, it is about that company. Full
        # stop. Broad sector matching exists for the other case -- "steel
        # prices surge on import duty" names nobody, and there the whole
        # sector genuinely is the story.
        #
        # Measured: 93% of stored rows were BROAD, 12.4 copies of every
        # headline. This one condition removes almost all of it.
        if results:
            return MatchedNews(item=item, matches=results)

        # A named company we could not resolve -> say nothing. Fanning it
        # across the sector is how "V-Mart Retail Q1 Results" ended up
        # flagged bullish on RELIANCE.
        if is_company_story(text):
            return MatchedNews(item=item, matches=[])

        # Market/index/commodity/IPO commentary -> say nothing. This is
        # what put a US market wrap on UPL, TIMETECHNO and GESHIP.
        if is_market_commentary(text):
            return MatchedNews(item=item, matches=[])

        # Sector matching is OFF by default -- see config's
        # NEWS_ENABLE_BROAD_TIER for the measurements behind that.
        if not NEWS_ENABLE_BROAD_TIER:
            return MatchedNews(item=item, matches=[])

        for field, patterns in self._broad_patterns.items():
            for pattern, term, symbol in patterns:
                if pattern.search(text):
                    add(symbol, field, term, "BROAD")

        return MatchedNews(item=item, matches=results)

    def match_all(self, items):
        return [self.match(item) for item in items]
