"""
==========================================================
News Bot -- Stage 1: Ingestion
==========================================================

Fetches every enabled RSS source, parses it, and normalizes
every entry into a NewsItem -- the one shape every later
stage relies on. A broken/unreachable source is logged
loudly and skipped; it never silently kills ingestion of the
other sources, and it never silently pretends to have zero
news either (see fetch_all's per-source result reporting).

Nothing here matches against the master database or spends
an AI call -- that starts in matching.py (Stage 2).

Author : H&M Opportunity Trader
==========================================================
"""

import feedparser
import requests

from core.logger import decision, diagnostic, warn
from news_bot import config as news_config
from news_bot.exchange_announcements import (
    ExchangeFetchError,
    fetch_bse_announcements,
    fetch_nse_announcements,
)
from news_bot.models import NewsItem
from news_bot.sources import NewsSource, enabled_sources

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SourceFetchError(Exception):
    """Raised when a single source cannot be fetched or parsed.
    Callers (fetch_all) catch this per-source -- it is never
    allowed to propagate and abort the whole ingestion run."""


def fetch_source(source: NewsSource):
    """Fetch and parse ONE RSS source. Returns a list[NewsItem].
    Raises SourceFetchError on any network, HTTP, or parse
    failure -- never returns a partial/guessed result.

    No session/cookie warm-up here -- that approach was tried
    for NSE in an earlier draft of this module and abandoned;
    NSE/BSE are handled separately in exchange_announcements.py
    via the `nse`/`bse` packages instead (see that module's
    docstring for why). Every source left in sources.py is a
    plain public RSS feed that doesn't need it."""

    try:
        session = requests.Session()
        headers = {"User-Agent": USER_AGENT}

        resp = session.get(
            source.url, headers=headers, timeout=source.timeout_seconds
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SourceFetchError(
            f"{source.name}: network/HTTP failure fetching {source.url}: {exc}"
        ) from exc

    parsed = feedparser.parse(resp.content)

    if parsed.bozo and not parsed.entries:
        raise SourceFetchError(
            f"{source.name}: feed did not parse as valid RSS/Atom "
            f"({parsed.bozo_exception!r}) and produced zero entries"
        )

    items = []
    for entry in parsed.entries:
        link = getattr(entry, "link", "") or ""
        guid = getattr(entry, "id", "") or link
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        published_raw = getattr(entry, "published", "") or getattr(
            entry, "updated", ""
        )

        if not title or not link:
            # A feed entry with no headline or no link is useless
            # to every later stage -- drop it, but log that it
            # happened rather than silently thinning the list.
            diagnostic(
                f"NEWS_BOT: {source.name}: skipped entry with missing "
                f"title/link (title={title!r}, link={link!r})"
            )
            continue

        items.append(
            NewsItem(
                source=source.name,
                title=title.strip(),
                summary=summary.strip(),
                link=link.strip(),
                published_raw=published_raw.strip(),
                guid=guid.strip(),
            )
        )

    return items


def fetch_all(sources=None):
    """Fetch every enabled source (or an explicit list, for
    tests), dedupe across sources by guid/link, and return the
    combined list[NewsItem]. Per-source success/failure is
    always logged -- silence about a dead source is exactly
    the kind of blanket-'done' claim this project does not
    allow."""

    sources = sources if sources is not None else enabled_sources()

    if not sources:
        warn("NEWS_BOT: no enabled sources configured -- ingestion will "
             "return zero items every run until sources.py is updated")
        return []

    seen_keys = set()
    combined = []

    for source in sources:
        try:
            source_items = fetch_source(source)
        except SourceFetchError as exc:
            warn(f"NEWS_BOT: {exc}")
            continue

        new_count = 0
        for item in source_items:
            key = item.dedupe_key()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            combined.append(item)
            new_count += 1

        decision(
            f"NEWS_BOT: {source.name}: fetched {len(source_items)} entries "
            f"({new_count} new after dedupe)"
        )

    return combined


def fetch_exchange_sources():
    """Fetch NSE + BSE corporate announcements (see
    exchange_announcements.py). Same isolation rule as RSS:
    one exchange failing is logged loudly and skipped, never
    silently zeroes out the other or crashes the run."""

    items = []

    if news_config.EXCHANGE_NSE_ENABLED:
        try:
            nse_items = fetch_nse_announcements(
                lookback_days=news_config.EXCHANGE_NSE_LOOKBACK_DAYS
            )
            decision(f"NEWS_BOT: NSE_ANNOUNCEMENTS: fetched {len(nse_items)} entries")
            items.extend(nse_items)
        except ExchangeFetchError as exc:
            warn(f"NEWS_BOT: {exc}")
    else:
        diagnostic("NEWS_BOT: NSE_ANNOUNCEMENTS disabled in news_bot/config.py")

    if news_config.EXCHANGE_BSE_ENABLED:
        try:
            for page in range(1, news_config.EXCHANGE_BSE_PAGES_PER_POLL + 1):
                bse_items = fetch_bse_announcements(page_no=page)
                decision(
                    f"NEWS_BOT: BSE_ANNOUNCEMENTS: page {page}: "
                    f"fetched {len(bse_items)} entries"
                )
                items.extend(bse_items)
        except ExchangeFetchError as exc:
            warn(f"NEWS_BOT: {exc}")
    else:
        diagnostic("NEWS_BOT: BSE_ANNOUNCEMENTS disabled in news_bot/config.py")

    return items


def fetch_everything(rss_sources=None):
    """The single entry point Stage 2 (and eventually the News
    Bot's poll loop) should call: RSS + NSE + BSE, deduped
    together across all of them by guid/link. This is what
    'ingestion' means end-to-end -- fetch_all() and
    fetch_exchange_sources() stay independently callable/
    testable for unit tests and for isolating one channel
    when debugging."""

    combined = fetch_all(sources=rss_sources)

    seen_keys = {item.dedupe_key() for item in combined}
    for item in fetch_exchange_sources():
        key = item.dedupe_key()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        combined.append(item)

    return combined
