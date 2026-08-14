"""
==========================================================
main.py reads. The collector fetches. Nothing overlaps.
==========================================================

    "why still NEWS is printing in main.py terminal ? ... in live
     markets only 2 terminals - main.py & news (news+rss++nse+bse+9 pro
     channels)"
    "PLS DO NOT COMBINE MAIN.PY"
                                    -- operator, 2-3 August 2026

WHY THIS TOOK DAYS LONGER THAN THE TELEGRAM SPLIT
-------------------------------------------------
Telegram already had a database. The collector wrote
data/stock_events.db, main.py read it, and neither knew about the
other -- the move was an afternoon.

These two had no database at all. AnnouncementWatcher kept `self._today`
in a list and NewsWatcher kept `self._items` in another, so lifting the
polling out of main.py would have lifted the DATA out with it. And
results_gate reads those filings to decide whether 83 reporting stocks
may be traded: not a panel going blank, the trading loop losing an
input it gates on.

core/feed_store.py is the home they were missing.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import tempfile

import pytest

from core.feed_store import (FeedStore, StoredAnnouncements, StoredNews)


@pytest.fixture
def store(tmp_path):
    return FeedStore(str(tmp_path / "feeds.db"))


FILINGS = [
    {"symbol": "TITAN", "filed_at": "09:16", "kind": "RESULTS",
     "subject": "Board approves results"},
    {"symbol": "BPCL", "filed_at": "09:40", "kind": "ORDER_WIN",
     "subject": "Order win of Rs 500 cr"},
]


def ident(row):
    return f"{row['symbol']}{row['filed_at']}"


# ---------------------------------------------------------------
# 1. main.py DOES NOT FETCH
# ---------------------------------------------------------------
def test_main_builds_readers_not_watchers():
    src = open("main.py", encoding="utf-8").read()
    assert "StoredAnnouncements()" in src
    assert "StoredNews()" in src
    assert "announcement_watcher.start()" not in src
    assert "news_watcher.start()" not in src


def test_main_never_constructs_a_live_watcher():
    """Constructing one is harmless; STARTING one puts an HTTP poll
    loop back inside the process that places orders."""
    src = open("main.py", encoding="utf-8").read()
    code = "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))
    assert "AnnouncementWatcher(" not in code
    assert "NewsWatcher(" not in code


def test_the_collector_starts_both():
    src = open("tools/collector.py", encoding="utf-8").read()
    assert "def start_feeds" in src
    assert "AnnouncementWatcher(" in src and "NewsWatcher(" in src
    assert "watcher.start()" in src and "news.start()" in src


def test_the_collector_hands_them_the_shared_store():
    src = open("tools/collector.py", encoding="utf-8").read()
    block = src[src.index("def start_feeds"):src.index("def world_watcher")]
    assert block.count("store=store") == 2


def test_a_reader_refuses_to_pretend_it_collects():
    """If something ever calls start() on the reader, it must say so
    loudly rather than quietly collecting nothing."""
    reader = StoredNews(store=FeedStore(":memory:"))
    with pytest.raises(NotImplementedError) as caught:
        reader.start()
    assert "collector" in str(caught.value)


# ---------------------------------------------------------------
# 2. THE READER LOOKS EXACTLY LIKE THE WATCHER
# ---------------------------------------------------------------
def test_it_answers_the_three_methods_the_rest_of_the_code_calls(store):
    """results_gate, the engine and the dashboard between them call
    for_symbol(), snapshot() and symbols_today(). Nothing downstream
    may need changing."""
    store.save("announcement", FILINGS, ident)
    reader = StoredAnnouncements(store=store)
    assert reader.for_symbol("TITAN")["subject"] == "Board approves results"
    assert reader.symbols_today() == {"TITAN", "BPCL"}
    assert reader.snapshot()["count_today"] == 2


def test_nothing_filed_is_none_not_an_error(store):
    """results_gate reads None as 'nothing filed' and that is what
    decides whether a reporting stock is blocked."""
    assert StoredAnnouncements(store=store).for_symbol("NOTHING") is None
    assert StoredAnnouncements(store=store).for_symbol(None) is None


def test_the_two_feeds_never_read_each_others_rows(store):
    store.save("announcement", FILINGS, ident)
    store.save("news", [{"symbol": "TITAN", "headline": "x", "link": "l1"}],
               lambda r: r["link"])
    assert StoredNews(store=store).for_symbol("TITAN")["headline"] == "x"
    assert "subject" in StoredAnnouncements(store=store).for_symbol("TITAN")


def test_the_snapshot_says_who_collects_it(store):
    """"No rows" and "the collector is not running" are different
    sentences, and only one of them is his to fix."""
    assert StoredNews(store=store).snapshot()["collected_by"] \
        == "py tools/collector.py"


# ---------------------------------------------------------------
# 3. THE STORE ITSELF
# ---------------------------------------------------------------
def test_the_same_filing_twice_is_stored_once(store):
    assert store.save("announcement", FILINGS, ident) == 2
    assert store.save("announcement", FILINGS, ident) == 0
    assert store.count("announcement") == 2


def test_newest_first(store):
    store.save("announcement", FILINGS, ident)
    rows = store.rows("announcement")
    assert rows[0]["symbol"] == "BPCL"          # 09:40 before 09:16


def test_an_unwritable_store_is_survivable_and_loud(tmp_path):
    """A broken database must cost the panels, never the session.

    My first version pointed at a non-existent directory and the store
    simply created it -- makedirs(exist_ok=True) does that. A FILE
    where a directory belongs is a path that genuinely cannot be
    opened."""
    blocker = tmp_path / "notadir"
    blocker.write_text("x", encoding="utf-8")
    bad = FeedStore(str(blocker / "f.db"))
    assert bad.rows("news") == []
    assert bad.for_symbol("news", "TITAN") is None
    assert bad.count("news") == 0
    assert bad.save("news", [{"symbol": "X"}], lambda r: "k") == 0


def test_a_row_without_an_identity_is_skipped_not_crashed(store):
    assert store.save("news", [{"symbol": "X"}], lambda r: None) == 0


# ---------------------------------------------------------------
# 4. THE WATCHERS STILL WORK WITHOUT A STORE
# ---------------------------------------------------------------
def test_a_watcher_with_no_store_behaves_exactly_as_before():
    """The store is optional on purpose -- every existing test builds
    these watchers without one."""
    from core.announcement_watcher import AnnouncementWatcher
    from core.news_watcher import NewsWatcher
    assert AnnouncementWatcher().store is None
    assert NewsWatcher().store is None


def test_the_watchers_write_when_they_are_given_one():
    ann = open("core/announcement_watcher.py", encoding="utf-8").read()
    news = open("core/news_watcher.py", encoding="utf-8").read()
    assert 'self.store.save("announcement", fresh,' in ann
    assert 'self.store.save("news", fresh,' in news
    assert "if self.store is not None:" in ann
    assert "if fresh and self.store is not None:" in news
