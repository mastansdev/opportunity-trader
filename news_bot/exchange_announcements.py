"""
==========================================================
News Bot -- Exchange Corporate Announcements (NSE + BSE)
==========================================================

Fetches official corporate filings directly from NSE and
BSE -- the same category of news the old bot's
adapters/nse_adapter.py and collectors/bse_corporate_collector.py
were trying to get, but via a different, PROVEN mechanism.

Why not RSS/raw-XML like the old nse_adapter.py or Claude's
own sandbox test attempted:
    - NSE's RSS/XML endpoints require session cookies from a
      prior visit to nseindia.com before they'll serve content
      to a script (anti-bot). Raw urllib/requests without that
      handshake gets blocked or returns unparseable content --
      confirmed independently twice: once by the old bot's
      nse_adapter.py never being finished past a stub, and
      again in this build's own sandbox testing.
    - The `nse` and `bse` PyPI packages (BennyThadikaran --
      NseIndiaApi / BseIndiaApi) already implement that
      handshake and were PROVEN working in the old bot for
      results-calendar data (collectors/results_calendar_collector.py,
      NseResultsCalendarCollector, real confirmed field names).
      Same packages expose a general `.announcements()` method
      for corporate filings -- that's what this module uses.

IMPORTANT -- known risk carried over from the old bot's own
hard-won lesson (see tools/news_pipeline_check.py and
collectors/results_calendar_collector.py comments in the
prior project): both NSE and BSE have been observed refusing
connections from cloud/datacenter IPs (Railway, and this
build sandbox both hit ProxyError/ConnectionError -- see
build notes). This is suspected IP-reputation blocking, NOT
a code bug. It has only been confirmed failing from
cloud/sandboxed origins so far -- NOT from a normal home/
residential IP, which is what this bot actually runs from in
PAPER mode. Treat first real run's log output as the actual
verdict, not this module's sandbox test result.

Real, confirmed field names (fetched from each package's own
published sample response on GitHub, not guessed):

  NSE .announcements() row:
      symbol, desc, dt, attchmntFile, sm_name, sm_isin, an_dt,
      sort_date, seq_id, smIndustry, attchmntText, ...
      -- 'symbol' is the NSE ticker directly. That's ground
      truth for which stock this filing is about, so it's
      passed through as NewsItem.known_symbol rather than left
      for Stage 2 to guess from text.

  BSE .announcements() row (inside response['Table']):
      NEWSID, SCRIP_CD, HEADLINE, MORE, CATEGORYNAME,
      SUBCATNAME, CRITICALNEWS, News_submission_dt, NSURL,
      SLONGNAME, ...
      -- BSE gives a BSE-specific numeric SCRIP_CD, not an NSE
      symbol, and master_stocks.csv has no BSE-code column to
      map it against. So BSE items do NOT get known_symbol set
      -- they fall through to normal Stage 2 text matching
      against SLONGNAME/HEADLINE, same limitation as general
      news. A BSE-scripcode-to-NSE-symbol mapping is a possible
      future improvement, not built here.

BSE category pre-filter below is ported from the old bot's
collectors/bse_corporate_collector.py, which had already been
tuned against real BSE data (ALLOWED_CATEGORIES /
ALLOWED_SUBCATEGORIES / IGNORE_SUBCATEGORIES) to cut a
2,000+/day raw announcement volume down to material events
before it reaches Stage 2. NSE's announcements() volume is
lower and hasn't been through that tuning process yet, so no
category filter is applied on the NSE side -- everything NSE
returns is passed to Stage 2 as-is; Stage 2/3/4 decide
materiality from there.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

from core.logger import diagnostic
from news_bot.models import NewsItem

# --------------------------------------------------
# BSE category pre-filter (ported, proven in the old bot)
# --------------------------------------------------

BSE_ALLOWED_CATEGORIES = {
    "Board Meeting",
    "Company Update",
    "Result",
    "Financial Results",
}

BSE_ALLOWED_SUBCATEGORIES = {
    "Acquisition",
    "Board Meeting",
    "Buyback",
    "Dividend",
    "Bonus",
    "Split",
    "Merger",
    "Amalgamation",
    "Fund Raising",
    "Preferential Issue",
    "QIP",
    "Rights Issue",
    "Credit Rating",
    "Order",
    "Order Win",
    "Contract",
    "Expansion",
    "Capacity Expansion",
}

BSE_IGNORE_SUBCATEGORIES = {
    "Newspaper Publication",
    "AGM",
    "EGM",
    "Annual Report",
    "Business Responsibility and Sustainability Reporting (BRSR)",
    "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018",
    "General",
}


class ExchangeFetchError(Exception):
    """Raised when NSE or BSE cannot be reached or returns an
    unusable response. Caught per-source by whoever calls
    these functions (ingestion.py) -- one exchange being down
    must not silently zero out the other, or RSS."""


# --------------------------------------------------
# NSE
# --------------------------------------------------

def fetch_nse_announcements(lookback_days=1):
    """Fetch NSE corporate announcements for the last
    `lookback_days` (inclusive of today) via the `nse` package.
    Every row becomes a NewsItem with known_symbol set --
    NSE tells us the exact stock directly."""

    try:
        from nse import NSE
    except ImportError as exc:
        raise ExchangeFetchError(
            "NSE_ANNOUNCEMENTS: 'nse' package not installed "
            "(pip install nse)"
        ) from exc

    to_date = datetime.now()
    from_date = to_date - timedelta(days=lookback_days)

    try:
        with NSE(download_folder=".", server=False) as nse_client:
            rows = nse_client.announcements(
                index="equities", from_date=from_date, to_date=to_date
            )
    except Exception as exc:
        raise ExchangeFetchError(
            f"NSE_ANNOUNCEMENTS: fetch failed: {exc}"
        ) from exc

    if rows is None:
        raise ExchangeFetchError(
            "NSE_ANNOUNCEMENTS: package returned None instead of a list"
        )

    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = str(row.get("symbol", "") or "").strip().upper()
        headline_text = str(row.get("attchmntText", "") or "").strip()
        category = str(row.get("desc", "") or "").strip()
        link = str(row.get("attchmntFile", "") or "")
        published_raw = str(row.get("an_dt", "") or row.get("sort_date", "") or "")
        seq_id = str(row.get("seq_id", "") or "")

        if not headline_text:
            # Fall back to company name + category if the free-text
            # summary is missing -- still better than dropping a
            # real filing silently.
            headline_text = f"{row.get('sm_name', symbol)}: {category}".strip(": ")

        if not headline_text:
            diagnostic(
                f"NEWS_BOT: NSE_ANNOUNCEMENTS: skipped row with no "
                f"usable text (symbol={symbol!r})"
            )
            continue

        items.append(
            NewsItem(
                source="NSE_ANNOUNCEMENTS",
                title=headline_text,
                summary=category,
                link=link or f"nse-announcement:{seq_id or symbol}",
                published_raw=published_raw,
                guid=seq_id or link or f"{symbol}:{published_raw}",
                known_symbol=symbol,
            )
        )

    return items


# --------------------------------------------------
# BSE
# --------------------------------------------------

def _bse_row_passes_filter(category, subcategory, critical):
    if subcategory in BSE_IGNORE_SUBCATEGORIES:
        return False
    if category in BSE_ALLOWED_CATEGORIES or subcategory in BSE_ALLOWED_SUBCATEGORIES:
        if not critical and subcategory not in BSE_ALLOWED_SUBCATEGORIES:
            return False
        return True
    return False


def fetch_bse_announcements(page_no=1):
    """Fetch one page of BSE corporate announcements via the
    `bse` package, pre-filtered by the category rules ported
    from the old bot's proven BSE collector. BSE gives no NSE-
    style symbol, so known_symbol is left unset -- Stage 2
    matches these by company name/headline text instead."""

    try:
        from bse import BSE
    except ImportError as exc:
        raise ExchangeFetchError(
            "BSE_ANNOUNCEMENTS: 'bse' package not installed (pip install bse)"
        ) from exc

    try:
        bse_client = BSE(download_folder=".")
    except Exception as exc:
        raise ExchangeFetchError(
            f"BSE_ANNOUNCEMENTS: could not start BSE client: {exc}"
        ) from exc

    try:
        response = bse_client.announcements(page_no=page_no)
    except Exception as exc:
        raise ExchangeFetchError(
            f"BSE_ANNOUNCEMENTS: fetch failed: {exc}"
        ) from exc
    finally:
        try:
            bse_client.exit()
        except Exception:
            pass

    if not isinstance(response, dict):
        raise ExchangeFetchError(
            "BSE_ANNOUNCEMENTS: unexpected response shape (not a dict)"
        )

    rows = response.get("Table", [])

    items = []
    skipped_by_filter = 0
    for row in rows:
        if not isinstance(row, dict):
            continue

        category = str(row.get("CATEGORYNAME", "") or "").strip()
        subcategory = str(row.get("SUBCATNAME", "") or "").strip()
        critical = row.get("CRITICALNEWS", 0)

        if not _bse_row_passes_filter(category, subcategory, critical):
            skipped_by_filter += 1
            continue

        headline = str(row.get("HEADLINE", "") or "").strip()
        if not headline:
            continue

        company_name = str(row.get("SLONGNAME", "") or "")
        summary = f"{company_name} {row.get('MORE', '') or ''}".strip()

        items.append(
            NewsItem(
                source="BSE_ANNOUNCEMENTS",
                title=headline,
                summary=summary,
                link=str(row.get("NSURL", "") or ""),
                published_raw=str(row.get("News_submission_dt", "") or ""),
                guid=str(row.get("NEWSID", "") or row.get("NSURL", "") or headline),
            )
        )

    diagnostic(
        f"NEWS_BOT: BSE_ANNOUNCEMENTS: page {page_no}: {len(rows)} raw rows, "
        f"{skipped_by_filter} filtered out by category rules, "
        f"{len(items)} kept"
    )

    return items
