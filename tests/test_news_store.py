"""
==========================================================
Tests -- persistent news store (news_bot/news_store.py)
==========================================================

The store is the fix for the 24/7 engine's real problems, so the
tests pin exactly those guarantees:

  - the SAME story re-seen on later poll cycles is stored ONCE
    (the duplicate bug, proven live 2026-07-24),
  - one story matching many stocks makes one row PER stock,
  - the per-stock "brain" query returns a symbol's full history,
  - the freshness window controls what's actionable without
    deleting anything,
  - postgres:// URLs are normalized (the exact string Railway
    injects must work unedited).

All tests use a temp SQLite file -- identical code path to the
Railway Postgres, just a different URL.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime, timedelta, timezone

from news_bot.models import NewsItem
from news_bot.news_store import NewsStore, resolve_database_url


def _store(tmp_path):
    return NewsStore(url="sqlite:///" + os.path.join(str(tmp_path), "t.db"))


def _item(guid="g1", title="Some headline", link="http://x/1", source="ET"):
    return NewsItem(
        source=source, title=title, summary="", link=link,
        published_raw="", guid=guid,
    )


class _PR:
    """Minimal stand-in for a PriorityResult (the store only reads
    attributes, never constructs one)."""
    def __init__(self, symbol="TCS", priority="HIGH", direction="bullish",
                 confidence=85, materiality="material", reason="reason",
                 matched_field="COMPANY_NAME", tier="COMPANY",
                 classifier="haiku"):
        self.symbol = symbol
        self.priority = priority
        self.direction = direction
        self.confidence = confidence
        self.materiality = materiality
        self.reason = reason
        self.matched_field = matched_field
        self.tier = tier
        self.classifier = classifier


# ---------------------------------------------------------------
# Dedup -- the headline problem
# ---------------------------------------------------------------

def test_same_story_reseen_across_cycles_is_stored_once(tmp_path):
    store = _store(tmp_path)
    pr, item = _PR(symbol="RELIANCE"), _item("rel-1")

    assert store.record(pr, item) is True     # first poll: new
    assert store.record(pr, item) is False    # second poll: duplicate
    assert store.record(pr, item) is False    # third poll: duplicate
    assert store.count() == 1


def test_one_story_many_stocks_makes_one_row_per_stock(tmp_path):
    store = _store(tmp_path)
    item = _item("oil-1", title="Crude oil jumps 3%")
    store.record(_PR(symbol="RELIANCE", tier="BROAD", priority="MID"), item)
    store.record(_PR(symbol="ONGC", tier="BROAD", priority="MID"), item)

    assert store.count() == 2
    # ...but re-seeing that same story doesn't add more.
    store.record(_PR(symbol="RELIANCE", tier="BROAD", priority="MID"), item)
    assert store.count() == 2


def test_different_stories_same_stock_both_kept(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS"), _item("g1"))
    store.record(_PR(symbol="TCS"), _item("g2"))
    assert store.count() == 2


# ---------------------------------------------------------------
# Per-stock "brain"
# ---------------------------------------------------------------

def test_for_symbol_returns_that_stocks_full_history_newest_first(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", priority="MID", reason="older"), _item("g1"))
    store.record(_PR(symbol="TCS", priority="HIGH", reason="newer"), _item("g2"))
    store.record(_PR(symbol="INFY"), _item("g3"))

    hist = store.for_symbol("TCS")
    assert [r["reason"] for r in hist] == ["newer", "older"]   # newest first
    assert all(r["symbol"] == "TCS" for r in hist)             # only this stock


def test_classifier_field_round_trips(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", classifier="keyword"), _item("g1"))
    assert store.for_symbol("TCS")[0]["classifier"] == "keyword"


# ---------------------------------------------------------------
# Freshness window -- actionable vs stored-forever
# ---------------------------------------------------------------

def _backdate(store, hours):
    """Push every row's created_at back by `hours` so we can test the
    window without waiting."""
    from sqlalchemy import update
    older = datetime.now(timezone.utc) - timedelta(hours=hours)
    with store.engine.begin() as conn:
        conn.execute(update(store.news_items).values(created_at=older))


def test_high_priority_for_respects_the_freshness_window(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", priority="HIGH"), _item("g1"))

    # Inside the window -> actionable.
    assert len(store.high_priority_for("TCS", window_hours=72)) == 1
    # Backdate 100h, ask for a 72h window -> no longer actionable...
    _backdate(store, 100)
    assert store.high_priority_for("TCS", window_hours=72) == []
    # ...but it's NOT deleted -- the per-stock brain still has it.
    assert len(store.for_symbol("TCS")) == 1


def test_all_high_symbols_returns_latest_per_symbol_within_window(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", direction="bullish"), _item("g1"))
    store.record(_PR(symbol="TCS", direction="bearish"), _item("g2"))
    store.record(_PR(symbol="INFY", direction="bullish"), _item("g3"))

    latest = store.all_high_symbols(window_hours=72)
    assert set(latest) == {"TCS", "INFY"}
    assert latest["TCS"]["direction"] == "bearish"   # latest wins


def test_recent_includes_mid_and_high_newest_first(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", priority="MID"), _item("g1"))
    store.record(_PR(symbol="INFY", priority="HIGH"), _item("g2"))

    feed = store.recent(window_hours=72)
    assert {r["priority"] for r in feed} == {"MID", "HIGH"}
    assert feed[0]["symbol"] == "INFY"      # newest first


def test_recent_respects_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(10):
        store.record(_PR(symbol=f"S{i}", priority="MID"), _item(f"g{i}"))
    assert len(store.recent(limit=3, window_hours=72)) == 3


# ---------------------------------------------------------------
# Housekeeping + URL handling
# ---------------------------------------------------------------

def test_prune_older_than_deletes_only_old_rows(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="OLD"), _item("g1"))
    _backdate(store, 24 * 40)                     # 40 days old
    store.record(_PR(symbol="NEW"), _item("g2"))  # fresh

    removed = store.prune_older_than(days=30)
    assert removed == 1
    assert store.count() == 1
    assert store.for_symbol("NEW")


def test_exists_true_only_after_recording(tmp_path):
    store = _store(tmp_path)
    assert store.exists("g1", "TCS") is False
    store.record(_PR(symbol="TCS"), _item("g1"))
    assert store.exists("g1", "TCS") is True
    # Different stock, same story -> not yet recorded for it.
    assert store.exists("g1", "INFY") is False


def test_delete_neutral_removes_only_neutral(tmp_path):
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", direction="bullish"), _item("g1"))
    store.record(_PR(symbol="INFY", direction="neutral", confidence=40), _item("g2"))
    assert store.count() == 2
    removed = store.delete_neutral()
    assert removed == 1
    assert store.count() == 1
    assert store.exists("g1", "TCS") and not store.exists("g2", "INFY")


def test_neutral_rows_are_excluded_from_reads_but_kept_for_dedup(tmp_path):
    """A stored neutral row (e.g. a paid-once AI marker) must NOT show
    in the feed / per-stock brain, but exists() must still see it so we
    never re-classify or re-pay for it."""
    store = _store(tmp_path)
    store.record(_PR(symbol="TCS", direction="neutral", confidence=40,
                     classifier="haiku"), _item("g1"))
    store.record(_PR(symbol="TCS", priority="MID", direction="bullish",
                     confidence=55), _item("g2"))

    assert store.exists("g1", "TCS") is True         # remembered
    # ...but hidden from every display read:
    assert [r["direction"] for r in store.recent()] == ["bullish"]
    assert [r["direction"] for r in store.for_symbol("TCS")] == ["bullish"]
    assert store.stats()["mid"] == 1                 # neutral not counted


def test_resolve_database_url_normalizes_railway_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/railway")
    url = resolve_database_url()
    assert url.startswith("postgresql://")
    assert url == "postgresql://u:p@host:5432/railway"


def test_resolve_database_url_falls_back_to_sqlite_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_database_url().startswith("sqlite:///")


def test_explicit_url_beats_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db")
    assert resolve_database_url("sqlite:///data/x.db") == "sqlite:///data/x.db"
