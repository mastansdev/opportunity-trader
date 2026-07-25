"""
==========================================================
Tests -- standalone news dashboard (news_dashboard.py)
==========================================================

Read-only view over the store, so the tests just prove each
endpoint returns the right shape from a temp store: the page
loads, /api/news gives header stats + a HIGH board + the MID/HIGH
feed, and /api/stock/{symbol} returns that stock's full history.

Author : H&M Opportunity Trader
==========================================================
"""

import os

from fastapi.testclient import TestClient

from news_bot.models import NewsItem
from news_bot.news_store import NewsStore
from news_bot.priority import PriorityResult
from news_dashboard import build_app


def _store(tmp_path):
    return NewsStore(url="sqlite:///" + os.path.join(str(tmp_path), "d.db"))


def _item(guid):
    return NewsItem(source="ET", title="Headline " + guid, summary="",
                    link="http://x/" + guid, published_raw="", guid=guid)


def _pr(symbol="TCS", priority="HIGH", direction="bullish", confidence=85,
        classifier="haiku"):
    return PriorityResult(symbol=symbol, priority=priority, direction=direction,
                          confidence=confidence, materiality="material",
                          reason="reason " + symbol, matched_field="COMPANY_NAME",
                          tier="COMPANY", classifier=classifier)


def _client(store):
    return TestClient(build_app(store=store))


def test_index_page_loads(tmp_path):
    r = _client(_store(tmp_path)).get("/")
    assert r.status_code == 200
    assert "News Intelligence" in r.text
    assert r.headers.get("cache-control") == "no-store"


def test_api_news_reports_stats_high_board_and_feed(tmp_path):
    store = _store(tmp_path)
    store.record(_pr(symbol="TCS", priority="HIGH"), _item("g1"))
    store.record(_pr(symbol="INFY", priority="MID", confidence=55,
                     classifier="keyword"), _item("g2"))

    d = _client(store).get("/api/news").json()

    assert d["stats"]["high"] == 1
    assert d["stats"]["mid"] == 1
    assert d["stats"]["distinct_symbols"] == 2
    # HIGH board only lists actionable HIGH stocks.
    assert [r["symbol"] for r in d["high_board"]] == ["TCS"]
    # Feed carries both tiers, newest first.
    assert {r["symbol"] for r in d["feed"]} == {"TCS", "INFY"}
    assert d["feed"][0]["symbol"] == "INFY"          # recorded last
    infy = next(r for r in d["feed"] if r["symbol"] == "INFY")
    assert infy["classifier"] == "keyword"


def test_api_news_empty_store_is_graceful(tmp_path):
    d = _client(_store(tmp_path)).get("/api/news").json()
    assert d["stats"]["total_all_time"] == 0
    assert d["high_board"] == []
    assert d["feed"] == []


def test_api_stock_returns_full_history_newest_first(tmp_path):
    store = _store(tmp_path)
    store.record(_pr(symbol="RELIANCE", priority="MID", direction="bullish"),
                 _item("g1"))
    store.record(_pr(symbol="RELIANCE", priority="HIGH", direction="bearish"),
                 _item("g2"))
    store.record(_pr(symbol="TCS"), _item("g3"))

    d = _client(store).get("/api/stock/reliance").json()   # case-insensitive
    assert d["symbol"] == "RELIANCE"
    assert d["count"] == 2
    assert [r["direction"] for r in d["history"]] == ["bearish", "bullish"]
    assert all(r["symbol"] == "RELIANCE" for r in d["history"])


def test_api_stock_unknown_symbol_is_empty_not_error(tmp_path):
    d = _client(_store(tmp_path)).get("/api/stock/NOSUCH").json()
    assert d["count"] == 0
    assert d["history"] == []
