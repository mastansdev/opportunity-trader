"""
==========================================================
News Bot -- Data Models
==========================================================

Plain, explicit records passed between pipeline stages.
No hidden state, no silent defaults -- every field is set
on purpose so later stages can trust what they're reading.

Author : H&M Opportunity Trader
==========================================================
"""

from dataclasses import dataclass, field


@dataclass
class NewsItem:
    """One normalized headline, regardless of which RSS
    source it came from. This is Stage 1's output shape --
    every source-specific parser must produce exactly this."""

    source: str            # source name, e.g. "ECONOMIC_TIMES", "NSE_ANNOUNCEMENTS"
    title: str              # headline text
    summary: str            # feed summary/description (may be empty string)
    link: str                # article URL -- primary dedupe key
    published_raw: str       # original published string from feed (kept as-is)
    guid: str                 # feed-provided guid if present, else link
    known_symbol: str = ""    # set ONLY when the source itself tells us the exact
                               # stock this item is about (e.g. NSE's corporate
                               # announcements feed returns a 'symbol' field
                               # directly, per-filing). Empty for general news
                               # RSS, where Stage 2 has to work it out from text.
                               # Stage 2 treats a valid known_symbol as ground
                               # truth and skips text-guessing for that symbol.

    def dedupe_key(self):
        return self.guid or self.link


@dataclass
class MatchResult:
    """One (news item, matched stock) pairing produced by
    Stage 2. A single NewsItem can produce zero, one, or many
    MatchResults (e.g. a crude-oil headline matches every
    oil-exposed stock)."""

    symbol: str              # SYMBOL from master_stocks.csv
    field: str                # which master DB field matched: COMPANY_NAME /
                               # SYMBOL / SECTOR / INDUSTRY / KEYWORDS / THEMES /
                               # COMMODITY_EXPOSURE
    matched_term: str         # the exact term/phrase that matched
    tier: str                  # "COMPANY" (single-stock, high confidence) or
                               # "BROAD" (sector/theme/commodity, many-stock,
                               # lower per-stock confidence)


@dataclass
class MatchedNews:
    """A NewsItem plus every MatchResult it produced. This is
    Stage 2's final output -- the input Stage 3 (AI
    classification, not built yet) will consume."""

    item: NewsItem
    matches: list = field(default_factory=list)

    @property
    def is_dummy(self):
        """No match to anything in the 750-stock universe --
        Stage 2's DUMMY verdict. Zero AI spend on this item."""
        return len(self.matches) == 0

    @property
    def matched_symbols(self):
        return sorted({m.symbol for m in self.matches})
