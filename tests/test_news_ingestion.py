"""
Decision-correctness tests for News Bot Stage 1 (ingestion).

No real network calls -- requests.Session.get is monkeypatched
per test so these run offline and deterministically. What's
being verified is the LOGIC: normalization, malformed-entry
handling, per-source failure isolation, and dedupe -- not
whether any particular website is up right now.
"""

import requests

from news_bot.ingestion import SourceFetchError, fetch_all, fetch_source
from news_bot.sources import NewsSource

_GOOD_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Test Feed</title>
<item>
  <title>Reliance Industries reports strong Q1 profit</title>
  <link>https://example.com/reliance-q1</link>
  <guid>guid-reliance-q1</guid>
  <description>Reliance posted higher refining margins.</description>
  <pubDate>Wed, 22 Jul 2026 09:00:00 GMT</pubDate>
</item>
<item>
  <title>Second headline</title>
  <link>https://example.com/second</link>
  <description>No guid on this one.</description>
  <pubDate>Wed, 22 Jul 2026 09:05:00 GMT</pubDate>
</item>
</channel></rss>
"""

_MISSING_LINK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Test Feed</title>
<item>
  <title>Headline with no link at all</title>
  <description>Should be dropped, not crash.</description>
</item>
<item>
  <title>Good headline</title>
  <link>https://example.com/good</link>
  <description>Kept.</description>
</item>
</channel></rss>
"""

_NOT_RSS_AT_ALL = "This is not XML or RSS in any way."


class _FakeResponse:
    def __init__(self, content, status_ok=True):
        self.content = content.encode("utf-8")
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("simulated HTTP error")


def _patch_get(monkeypatch, response_map):
    """response_map: dict[url] -> _FakeResponse or an
    exception instance to raise."""

    def fake_get(self, url, headers=None, timeout=None):
        outcome = response_map[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests.Session, "get", fake_get)


def test_fetch_source_normalizes_entries_correctly(monkeypatch):
    source = NewsSource(name="TESTSRC", url="https://example.com/rss", enabled=True)
    _patch_get(monkeypatch, {source.url: _FakeResponse(_GOOD_RSS)})

    items = fetch_source(source)

    assert len(items) == 2
    first = items[0]
    assert first.source == "TESTSRC"
    assert first.title == "Reliance Industries reports strong Q1 profit"
    assert first.link == "https://example.com/reliance-q1"
    assert first.guid == "guid-reliance-q1"
    assert "refining margins" in first.summary

    # Second entry has no <guid> -- guid must fall back to link.
    second = items[1]
    assert second.guid == second.link == "https://example.com/second"


def test_fetch_source_skips_entries_missing_title_or_link(monkeypatch):
    source = NewsSource(name="TESTSRC", url="https://example.com/rss", enabled=True)
    _patch_get(monkeypatch, {source.url: _FakeResponse(_MISSING_LINK_RSS)})

    items = fetch_source(source)

    assert len(items) == 1
    assert items[0].title == "Good headline"


def test_fetch_source_raises_on_unparseable_feed(monkeypatch):
    source = NewsSource(name="TESTSRC", url="https://example.com/rss", enabled=True)
    _patch_get(monkeypatch, {source.url: _FakeResponse(_NOT_RSS_AT_ALL)})

    try:
        fetch_source(source)
        assert False, "expected SourceFetchError for unparseable feed"
    except SourceFetchError:
        pass


def test_fetch_source_raises_on_network_failure(monkeypatch):
    source = NewsSource(name="TESTSRC", url="https://example.com/rss", enabled=True)
    _patch_get(
        monkeypatch,
        {source.url: requests.ConnectionError("simulated connection failure")},
    )

    try:
        fetch_source(source)
        assert False, "expected SourceFetchError for network failure"
    except SourceFetchError:
        pass


def test_fetch_all_isolates_one_broken_source_from_the_rest(monkeypatch):
    good_source = NewsSource(name="GOOD", url="https://good.example.com/rss", enabled=True)
    bad_source = NewsSource(name="BAD", url="https://bad.example.com/rss", enabled=True)

    _patch_get(
        monkeypatch,
        {
            good_source.url: _FakeResponse(_GOOD_RSS),
            bad_source.url: requests.ConnectionError("simulated down source"),
        },
    )

    items = fetch_all(sources=[good_source, bad_source])

    # The good source's items must still come through even though
    # the bad source failed -- one dead feed must not zero out
    # ingestion entirely.
    assert len(items) == 2
    assert all(item.source == "GOOD" for item in items)


def test_fetch_all_dedupes_across_sources_by_guid_or_link(monkeypatch):
    source_a = NewsSource(name="A", url="https://a.example.com/rss", enabled=True)
    source_b = NewsSource(name="B", url="https://b.example.com/rss", enabled=True)

    # Same RSS content served by both sources -- same guids/links.
    _patch_get(
        monkeypatch,
        {
            source_a.url: _FakeResponse(_GOOD_RSS),
            source_b.url: _FakeResponse(_GOOD_RSS),
        },
    )

    items = fetch_all(sources=[source_a, source_b])

    # 2 distinct entries in the feed -- duplicates from source B
    # must be dropped, not double-counted.
    assert len(items) == 2


def test_fetch_all_returns_empty_list_with_no_enabled_sources():
    assert fetch_all(sources=[]) == []


# --------------------------------------------------
# fetch_everything() -- combines RSS + NSE + BSE
# --------------------------------------------------

def test_fetch_everything_combines_rss_and_exchange_sources(monkeypatch):
    import news_bot.ingestion as ingestion_module
    from news_bot.models import NewsItem

    rss_source = NewsSource(name="RSS", url="https://rss.example.com/feed", enabled=True)
    _patch_get(monkeypatch, {rss_source.url: _FakeResponse(_GOOD_RSS)})

    nse_item = NewsItem(
        source="NSE_ANNOUNCEMENTS", title="NSE headline", summary="", link="",
        published_raw="", guid="nse-1", known_symbol="TCS",
    )
    bse_item = NewsItem(
        source="BSE_ANNOUNCEMENTS", title="BSE headline", summary="", link="",
        published_raw="", guid="bse-1",
    )

    monkeypatch.setattr(
        ingestion_module, "fetch_nse_announcements", lambda **kw: [nse_item]
    )
    monkeypatch.setattr(
        ingestion_module, "fetch_bse_announcements", lambda **kw: [bse_item]
    )
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_NSE_ENABLED", True)
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_BSE_ENABLED", True)
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_BSE_PAGES_PER_POLL", 1)

    combined = ingestion_module.fetch_everything(rss_sources=[rss_source])

    sources_seen = {item.source for item in combined}
    assert sources_seen == {"RSS", "NSE_ANNOUNCEMENTS", "BSE_ANNOUNCEMENTS"}
    assert len(combined) == 4  # 2 RSS entries + 1 NSE + 1 BSE


def test_fetch_exchange_sources_respects_disabled_flags(monkeypatch):
    import news_bot.ingestion as ingestion_module

    called = {"nse": False, "bse": False}

    def fake_nse(**kw):
        called["nse"] = True
        return []

    def fake_bse(**kw):
        called["bse"] = True
        return []

    monkeypatch.setattr(ingestion_module, "fetch_nse_announcements", fake_nse)
    monkeypatch.setattr(ingestion_module, "fetch_bse_announcements", fake_bse)
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_NSE_ENABLED", False)
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_BSE_ENABLED", False)

    items = ingestion_module.fetch_exchange_sources()

    assert items == []
    assert called == {"nse": False, "bse": False}


def test_fetch_exchange_sources_isolates_nse_failure_from_bse(monkeypatch):
    import news_bot.ingestion as ingestion_module
    from news_bot.exchange_announcements import ExchangeFetchError
    from news_bot.models import NewsItem

    def failing_nse(**kw):
        raise ExchangeFetchError("simulated NSE failure")

    bse_item = NewsItem(
        source="BSE_ANNOUNCEMENTS", title="BSE headline", summary="", link="",
        published_raw="", guid="bse-1",
    )

    monkeypatch.setattr(ingestion_module, "fetch_nse_announcements", failing_nse)
    monkeypatch.setattr(
        ingestion_module, "fetch_bse_announcements", lambda **kw: [bse_item]
    )
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_NSE_ENABLED", True)
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_BSE_ENABLED", True)
    monkeypatch.setattr(ingestion_module.news_config, "EXCHANGE_BSE_PAGES_PER_POLL", 1)

    items = ingestion_module.fetch_exchange_sources()

    assert len(items) == 1
    assert items[0].source == "BSE_ANNOUNCEMENTS"
