"""
==========================================================
News Bot -- RSS Source Registry
==========================================================

Every general-news RSS source News Bot polls, declared in
one place. Exchange corporate announcements (NSE/BSE) are
NOT here -- those use dedicated packages, see
exchange_announcements.py, because RSS/raw-XML scraping of
NSE/BSE was already tried in the previous bot and abandoned
in favour of the `nse`/`bse` PyPI packages, which handle the
session/anti-bot handshake for you.

REAL evidence, not guesses -- this list reflects what the
PREVIOUS bot (orb-auto-trader) actually observed running on
the real trading machine (not a cloud sandbox):

  ECONOMIC_TIMES -- confirmed working. Kept enabled.
  LIVEMINT       -- confirmed working. Kept enabled.
  MONEYCONTROL   -- confirmed BROKEN: persistent invalid-feed
      error even with a proper browser User-Agent header.
      Disabled by default. Left in this registry (not deleted)
      so the decision and the reason are visible, and so it's
      a one-line flip to re-test later if Moneycontrol changes
      its feed.
  BUSINESS_STANDARD -- confirmed BROKEN: explicit HTTP 403
      Forbidden even with a proper header. Disabled by default,
      same reasoning as above. (Note: this is the opposite of
      what Claude's own dev-sandbox test found -- the sandbox
      could fetch Business Standard fine but was blocked from
      Moneycontrol/ET. That sandbox result is NOT trusted here;
      it's a different network with different rules than the
      machine this bot actually runs on. The previous bot's
      real, on-machine results above are what's authoritative.)

Author : H&M Opportunity Trader
==========================================================
"""

from dataclasses import dataclass


@dataclass
class NewsSource:
    name: str                # short id, used in logs and NewsItem.source
    url: str
    enabled: bool
    timeout_seconds: int = 15


SOURCES = [
    NewsSource(
        name="ECONOMIC_TIMES",
        url="https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        enabled=True,
    ),
    NewsSource(
        name="LIVEMINT",
        url="https://www.livemint.com/rss/markets",
        enabled=True,
    ),
    NewsSource(
        name="MONEYCONTROL",
        url="https://www.moneycontrol.com/rss/marketreports.xml",
        enabled=False,   # confirmed broken on the real machine -- see module docstring
    ),
    NewsSource(
        name="BUSINESS_STANDARD",
        url="https://www.business-standard.com/rss/markets-106.rss",
        enabled=False,   # confirmed 403 on the real machine -- see module docstring
    ),
]


def enabled_sources():
    return [s for s in SOURCES if s.enabled]
