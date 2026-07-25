"""
Decision-correctness tests for the News Bot -> Brain Bot
interface, now store-backed (news_bot/news_store.py):

  - record() writes a matched item into the store, deduped, and
    logs HIGH items,
  - a MID item is stored but never appears as a HIGH lookup,
  - the reader loads actionable HIGH + a recent feed from the store
    into memory (the hot path never touches the DB),
  - the classifier stamp survives the round-trip.

All tests use a temp SQLite store injected into record()/reader --
never the module default, so nothing touches data/news.db.
"""

import os

from news_bot.models import NewsItem
from news_bot.news_queue import NewsQueueReader, record
from news_bot.news_store import NewsStore
from news_bot.priority import PriorityResult


def _store(tmp_path):
    return NewsStore(url="sqlite:///" + os.path.join(str(tmp_path), "q.db"))


def _item(guid="g1"):
    return NewsItem(
        source="TEST", title="Some headline", summary="",
        link="https://example.com/" + guid, published_raw="", guid=guid,
    )


def _result(symbol="TCS", priority="HIGH", direction="bullish", confidence=85,
            classifier="haiku"):
    return PriorityResult(
        symbol=symbol, priority=priority, direction=direction,
        confidence=confidence, materiality="material",
        reason="Large new export order.", matched_field="COMPANY_NAME",
        tier="COMPANY", classifier=classifier,
    )


def test_record_writes_to_the_store_and_dedupes(tmp_path):
    store = _store(tmp_path)

    assert record(_result(), _item("g1"), store=store) is True
    # Same (guid, symbol) re-seen next cycle -> not written again.
    assert record(_result(), _item("g1"), store=store) is False
    assert store.count() == 1


def test_high_item_is_found_by_the_reader_for_the_right_symbol(tmp_path):
    store = _store(tmp_path)
    record(_result(symbol="TCS"), _item("g1"), store=store)
    record(_result(symbol="INFY"), _item("g2"), store=store)

    reader = NewsQueueReader(store=store)
    reader.refresh()

    assert len(reader.high_priority_for("TCS")) == 1
    assert reader.high_priority_for("TCS")[0]["direction"] == "bullish"
    assert len(reader.high_priority_for("INFY")) == 1
    assert reader.high_priority_for("RELIANCE") == []


def test_mid_item_is_stored_but_not_a_high_lookup(tmp_path):
    store = _store(tmp_path)
    record(_result(symbol="TCS", priority="MID"), _item("g1"), store=store)

    reader = NewsQueueReader(store=store)
    reader.refresh()

    assert reader.high_priority_for("TCS") == []      # not HIGH
    # ...but it IS in the store and in the display feed.
    assert store.count() == 1
    assert [r["symbol"] for r in reader.recent()] == ["TCS"]


def test_recent_feed_includes_mid_and_high_newest_first(tmp_path):
    store = _store(tmp_path)
    record(_result(symbol="TCS", priority="MID"), _item("g1"), store=store)
    record(_result(symbol="INFY", priority="HIGH"), _item("g2"), store=store)

    reader = NewsQueueReader(store=store)
    reader.refresh()

    feed = reader.recent()
    assert [r["symbol"] for r in feed] == ["INFY", "TCS"]   # newest first
    assert {r["priority"] for r in feed} == {"MID", "HIGH"}


def test_reader_with_empty_store_returns_empty_not_a_crash(tmp_path):
    reader = NewsQueueReader(store=_store(tmp_path))
    reader.refresh()
    assert reader.high_priority_for("TCS") == []
    assert reader.recent() == []
    assert reader.all_symbols_today() == {}


def test_all_symbols_today_returns_latest_high_item_per_symbol(tmp_path):
    store = _store(tmp_path)
    record(_result(symbol="TCS", direction="bullish"), _item("g1"), store=store)
    record(_result(symbol="TCS", direction="bearish"), _item("g2"), store=store)
    record(_result(symbol="INFY", direction="bullish"), _item("g3"), store=store)

    reader = NewsQueueReader(store=store)
    reader.refresh()

    all_today = reader.all_symbols_today()
    assert set(all_today.keys()) == {"TCS", "INFY"}
    assert all_today["TCS"]["direction"] == "bearish"   # latest, not first


def test_classifier_field_is_persisted_and_read_back(tmp_path):
    store = _store(tmp_path)
    record(_result(classifier="keyword"), _item("g1"), store=store)

    reader = NewsQueueReader(store=store)
    reader.refresh()
    assert reader.high_priority_for("TCS")[0]["classifier"] == "keyword"
