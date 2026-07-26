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
from news_bot.models import MatchedNews, MatchResult

_CORP_SUFFIXES = {
    "LIMITED", "LTD", "LTD.", "LLP", "CO", "CO.", "CORP", "CORP.",
    "PVT", "PVT.", "PRIVATE", "INC", "INC.",
}

_MIN_SYMBOL_LEN = 3          # guard against short/generic symbol false-hits
_MIN_COMPANY_TERM_LEN = 3    # guard against 1-2 char normalized names


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
                self._symbol_patterns.append(
                    (_word_boundary_pattern(symbol.upper()), symbol)
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

        for pattern, symbol in self._symbol_patterns:
            if pattern.search(text):
                add(symbol, "SYMBOL", symbol, "COMPANY")

        for field, patterns in self._broad_patterns.items():
            for pattern, term, symbol in patterns:
                if pattern.search(text):
                    add(symbol, field, term, "BROAD")

        return MatchedNews(item=item, matches=results)

    def match_all(self, items):
        return [self.match(item) for item in items]
