"""
High-conviction news -- only what can actually move a stock.

The previous news subsystem (~3,200 lines) was deleted on 2026-07-26:

    "NO PLACE FOR ANY ITEM/FILE WHICH DOESN'T PROVIDE ENOUGH TOWARDS
     GOAL REACHING BY BOT."

It ran a thread through every session and nothing read the output. The
operator asked for it back the same day with a far tighter brief: news,
but ONLY key events that can move a stock.

THE GAP, from the real session of 2026-07-27
--------------------------------------------
core/announcement_watcher.py reads EXCHANGE FILINGS. It would have
missed both of that day's biggest single moves:

    GANDHAR    -11.6%   flood damage at its Silvassa plant
    CARTRADE   +10.8%   UBS initiated Buy, target Rs 4,000

One is a news story, the other a broker note. Neither is a filing.

The headlines below are written as those two events would have been
reported. Every rejection case is a real shape of Indian market
journalism -- "stocks to watch", "should you buy", technical calls,
listicles -- which is what drowned the last system.
"""

import pytest

from core.news_watcher import (NewsWatcher, classify_impact, match_symbols,
                               build_name_index, parse_rss, _clean_name)

INDEX = {
    "gandhar oil refinery": "GANDHAR", "cartrade tech": "CARTRADE",
    "tata power": "TATAPOWER", "laurus labs": "LAURUSLABS",
    "kpr mill": "KPRMILL", "bharat electronics": "BEL",
    "mold tek packaging": "MOLDTKPAC",
}


# ----------------------------------------------------------------
# The two the filings feed missed
# ----------------------------------------------------------------

def test_the_gandhar_plant_flood_is_caught():
    """2026-07-27's worst mover, -11.6%. Not a filing."""
    h = ("Gandhar Oil Refinery assesses flood damage at Silvassa plant "
         "after heavy rainfall")
    assert classify_impact(h) == "DISASTER"
    assert match_symbols(h, INDEX) == ["GANDHAR"]


def test_the_cartrade_broker_initiation_is_caught():
    """2026-07-27's best mover, +10.8%. Not a filing either."""
    h = ("CarTrade Tech zooms 70% since June; UBS initiates coverage with "
         "target price of Rs 4,000")
    assert classify_impact(h) == "BROKER"
    assert match_symbols(h, INDEX) == ["CARTRADE"]


# ----------------------------------------------------------------
# The nine categories
# ----------------------------------------------------------------

@pytest.mark.parametrize("headline,kind", [
    ("Tata Power bags Rs 2,300 crore order from Maharashtra discom",
     "ORDER_WIN"),
    ("Laurus Labs receives USFDA warning letter for its Visakhapatnam unit",
     "REGULATORY"),
    ("KPR Mill promoter sells 10.5 million shares in block deal", "DEAL"),
    ("Bharat Electronics CEO steps down with immediate effect", "MANAGEMENT"),
    ("Mold Tek Packaging raises Rs 400 crore via QIP", "FUND_RAISE"),
    ("Tata Power cuts FY27 guidance on weaker demand", "GUIDANCE"),
    ("NCLT admits insolvency plea against Gandhar Oil Refinery", "LEGAL"),
    ("Fire breaks out at Laurus Labs API facility", "DISASTER"),
    ("Jefferies downgrades Tata Power to Hold", "BROKER"),
])
def test_every_category_fires(headline, kind):
    assert classify_impact(headline) == kind


# ----------------------------------------------------------------
# What must be thrown away -- this is what killed the last system
# ----------------------------------------------------------------

@pytest.mark.parametrize("headline", [
    "Stocks to watch today: Tata Power, Laurus Labs, CarTrade Tech",
    "Should you buy Gandhar Oil Refinery at current levels?",
    "Top 5 multibagger stocks for 2026",
    "Sensex closes 776 points higher, Nifty at 23,996",
    "Technical view: Laurus Labs may test Rs 1800",
    "Market wrap: IT and banks lead the rally",
    "Here's what experts say about Tata Power",
    "Trading strategy for Bharat Electronics this week",
])
def test_opinion_and_filler_are_rejected(headline):
    assert classify_impact(headline) is None


def test_a_real_event_inside_a_listicle_is_still_rejected():
    """'Stocks in focus: XYZ bags order' is a column, not an event. Noise
    is checked FIRST and wins, deliberately."""
    assert classify_impact(
        "Stocks in focus: Tata Power bags Rs 2,300 crore order") is None


# ----------------------------------------------------------------
# Matching companies
# ----------------------------------------------------------------

def test_the_longest_company_name_wins():
    """'Tata Power' must not resolve to some other Tata company."""
    idx = dict(INDEX, tata="TATASTEEL")
    assert match_symbols("Tata Power bags an order", idx)[0] == "TATAPOWER"


def test_a_headline_naming_nobody_we_trade_yields_nothing():
    assert match_symbols("Some Unlisted Pvt Ltd wins a contract", INDEX) == []


def test_company_suffixes_are_stripped():
    assert _clean_name("GANDHAR OIL REFINERY (INDIA) LIMITED") == \
        "GANDHAR OIL REFINERY"


def test_the_real_master_list_builds_an_index():
    idx = build_name_index()
    assert len(idx) > 500
    assert idx.get("route mobile") == "ROUTE"


def test_a_symbol_with_no_real_company_name_still_matches_on_the_ticker():
    """DATA-QUALITY NOTE, found 2026-07-28. data/master_stocks.csv has
    COMPANY NAME = 'GANDHAR' for GANDHAR -- the ticker, not the name. So
    a headline reading "Gandhar Oil Refinery assesses flood damage"
    resolves only because the bare ticker is long enough to match
    case-insensitively. Any such symbol shorter than 7 characters would
    be missed entirely until the CSV is filled in properly."""
    idx = build_name_index()
    assert idx.get("gandhar") == "GANDHAR"
    assert match_symbols(
        "Gandhar Oil Refinery assesses flood damage at Silvassa plant",
        idx) == ["GANDHAR"]


def test_short_tickers_that_are_english_words_do_not_match_lowercase():
    """'ROUTE' (Route Mobile), 'AXIS', 'TRENT' are real symbols AND real
    words. Matching them lowercase would tag every headline containing
    "the route to profitability"."""
    idx = build_name_index()
    assert match_symbols("The route to profitability is unclear", idx) == []
    assert match_symbols("ROUTE bags a Rs 200 crore order", idx) == ["ROUTE"]


# ----------------------------------------------------------------
# Feeds
# ----------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Tata Power bags Rs 2,300 crore order from Maharashtra discom</title>
<link>http://x/1</link><pubDate>Tue, 28 Jul 2026 08:00:00 +0530</pubDate></item>
<item><title>Top 5 multibagger stocks for 2026</title>
<link>http://x/2</link><pubDate>Tue, 28 Jul 2026 08:01:00 +0530</pubDate></item>
</channel></rss>"""


def test_rss_is_parsed():
    items = parse_rss(RSS)
    assert len(items) == 2
    assert items[0][0].startswith("Tata Power bags")


def test_malformed_xml_returns_nothing_rather_than_raising():
    assert parse_rss("<not xml") == []


def test_only_the_real_event_survives_a_poll(monkeypatch):
    import core.news_watcher as nw
    monkeypatch.setattr(nw, "build_name_index", lambda *a, **k: dict(INDEX))
    w = NewsWatcher(feeds=["http://x"], fetcher=lambda url: RSS)
    w.index = dict(INDEX)
    fresh = w.poll_once()
    assert [r["symbol"] for r in fresh] == ["TATAPOWER"]
    assert fresh[0]["kind"] == "ORDER_WIN"


def test_the_same_headline_is_not_reported_twice():
    w = NewsWatcher(feeds=["http://x"], fetcher=lambda url: RSS)
    w.index = dict(INDEX)
    assert len(w.poll_once()) == 1
    assert w.poll_once() == []


def test_a_dead_feed_says_so_rather_than_looking_quiet():
    """'No big news today' and 'the feed is down' must never look the
    same to someone deciding whether to buy."""
    def boom(url):
        raise RuntimeError("connection refused")
    w = NewsWatcher(feeds=["http://x"], fetcher=boom)
    w.poll_once()
    assert "connection refused" in (w.snapshot()["error"] or "")


def test_one_dead_feed_does_not_stop_the_others():
    def flaky(url):
        if "dead" in url:
            raise RuntimeError("down")
        return RSS
    w = NewsWatcher(feeds=["http://dead", "http://alive"], fetcher=flaky)
    w.index = dict(INDEX)
    assert len(w.poll_once()) == 1
    assert w.snapshot()["error"]


def test_snapshot_is_json_safe():
    import json
    w = NewsWatcher(feeds=["http://x"], fetcher=lambda url: RSS)
    w.index = dict(INDEX)
    w.poll_once()
    json.dumps(w.snapshot())


# ----------------------------------------------------------------
# Reaching the shortlist
# ----------------------------------------------------------------

def test_a_broker_note_lifts_a_stock_above_a_bigger_mover(tmp_path):
    """CARTRADE rose 10.8% with a reason; SWIGGY rose 10.9% with none.
    The reason should win, because the move is usually its consequence."""
    from core.shortlist import ShortlistBuilder

    class News:
        def for_symbol(self, s):
            if s == "CARTRADE":
                return {"kind": "BROKER",
                        "headline": "UBS initiates coverage, target Rs 4,000"}
            return None

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"), news_watcher=News())
    out = b.rank([{"symbol": "SWIGGY", "ltp": 400, "change_pct": 10.9,
                   "volume": 1},
                  {"symbol": "CARTRADE", "ltp": 2986, "change_pct": 10.8,
                   "volume": 1}])
    assert out["rows"][0]["symbol"] == "CARTRADE"


def test_a_disaster_pushes_a_stock_down_the_list(tmp_path):
    """For a longs-only book, knowing a plant is on fire matters as much
    as knowing an order was won."""
    from core.shortlist import ShortlistBuilder

    class News:
        def for_symbol(self, s):
            return ({"kind": "DISASTER", "headline": "Flood at Silvassa plant"}
                    if s == "GANDHAR" else None)

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"), news_watcher=News())
    out = b.rank([{"symbol": "GANDHAR", "ltp": 246, "change_pct": -11.6,
                   "volume": 1},
                  {"symbol": "OTHER", "ltp": 100, "change_pct": -6.0,
                   "volume": 1}])
    assert out["rows"][-1]["symbol"] == "GANDHAR"


def test_a_broken_news_watcher_cannot_break_the_panel(tmp_path):
    from core.shortlist import ShortlistBuilder

    class Broken:
        def for_symbol(self, s):
            raise RuntimeError("exploded")

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         news_watcher=Broken())
    assert len(b.rank([{"symbol": "X", "ltp": 100, "change_pct": 5.0,
                        "volume": 1}])["rows"]) == 1
