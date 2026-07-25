"""
Decision-correctness tests for the News Bot pipeline orchestrator.
Ingestion and matching are faked (they have their own tests) -- this
file proves the ORCHESTRATION and the 2026-07-24 BUDGET CONTROLS:

  - dummy items never get classified,
  - a (story, stock) already in the store is skipped BEFORE any
    classify/AI spend (never re-billed),
  - only COMPANY-tier news spends a paid AI call; BROAD fan-out uses
    the free keyword classifier,
  - over-budget falls back to free (doesn't drop the item),
  - free-keyword NEUTRAL noise is dropped; a PAID neutral verdict is
    stored (as a paid-once memory marker) but not shown as a signal,
  - a classification error is isolated and falls back to keyword.

Tests use a real temp SQLite store so the dedup/exists path is
exercised for real.
"""

import os

from news_bot import pipeline
from news_bot.classification import ClassificationError
from news_bot.models import MatchedNews, MatchResult, NewsItem
from news_bot.news_store import NewsStore


def _store(tmp_path):
    return NewsStore(url="sqlite:///" + os.path.join(str(tmp_path), "p.db"))


def _item(guid, title="headline"):
    return NewsItem(
        source="TEST", title=title, summary="", link="https://x/" + guid,
        published_raw="", guid=guid,
    )


def _match(symbol="TCS", tier="COMPANY"):
    return MatchResult(symbol=symbol, field="COMPANY_NAME",
                       matched_term=symbol, tier=tier)


class _FakeLoader:
    def get_by_symbol(self, symbol):
        return {"SYMBOL": symbol, "COMPANY NAME": "X", "SECTOR": "IT"}


class _FakeMatcher:
    def __init__(self, matched_list):
        self._matched = matched_list
        self.loader = _FakeLoader()

    def match_all(self, items):
        return self._matched


class _FakeBudget:
    def __init__(self, allow=True, limit=800):
        self.allow = allow
        self.calls = 0
        self.limit = limit

    def can_spend(self, n=1):
        return self.allow

    def record_call(self):
        self.calls += 1

    def count_today(self):
        return self.calls


def _patch_fetch(monkeypatch, items):
    monkeypatch.setattr(pipeline, "fetch_everything", lambda: items)


_BULLISH_HAIKU = {
    "direction": "bullish", "confidence": 90,
    "materiality": "material", "reason": "Big order.",
}


def test_dummy_items_are_never_classified(monkeypatch, tmp_path):
    _patch_fetch(monkeypatch, [_item("d1")])
    matcher = _FakeMatcher([MatchedNews(item=_item("d1"), matches=[])])

    called = []
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda *a, **kw: called.append(1) or {})

    summary = pipeline.run_once(matcher=matcher, budget=_FakeBudget(),
                               store=_store(tmp_path))
    assert summary["dummy"] == 1
    assert summary["matched"] == 0
    assert called == []


def test_company_tier_high_news_is_ai_classified_and_stored(monkeypatch, tmp_path):
    store = _store(tmp_path)
    _patch_fetch(monkeypatch, [_item("m1")])
    matcher = _FakeMatcher([MatchedNews(item=_item("m1"), matches=[_match("TCS")])])

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: True)
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda item, company, client=None: dict(_BULLISH_HAIKU))

    summary = pipeline.run_once(matcher=matcher, budget=_FakeBudget(), store=store)

    assert summary["ai_calls"] == 1            # COMPANY tier -> paid
    assert summary["high"] == 1
    stored = store.high_priority_for("TCS")
    assert len(stored) == 1 and stored[0]["classifier"] == "haiku"


def test_broad_tier_never_spends_ai_uses_free_keyword(monkeypatch, tmp_path):
    """The budget saver: a sector/theme fan-out match must NOT cost a
    paid call, even with the API configured."""
    store = _store(tmp_path)
    _patch_fetch(monkeypatch, [_item("m2", title="Company wins big order worth 500cr")])
    matcher = _FakeMatcher([MatchedNews(
        item=_item("m2", title="Company wins big order worth 500cr"),
        matches=[_match("TCS", tier="BROAD")],
    )])

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: True)
    haiku_called = []
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda *a, **kw: haiku_called.append(1) or {})

    budget = _FakeBudget()
    summary = pipeline.run_once(matcher=matcher, budget=budget, store=store)

    assert haiku_called == []                  # BROAD never hits the AI
    assert budget.calls == 0
    assert summary["ai_calls"] == 0
    assert summary["keyword_calls"] == 1


def test_already_stored_story_is_skipped_before_any_spend(monkeypatch, tmp_path):
    """The re-billing guard: a (story, stock) already in the store is
    skipped before classify -- no AI, no keyword, nothing."""
    store = _store(tmp_path)
    matched = MatchedNews(item=_item("m3"), matches=[_match("TCS")])
    matcher = _FakeMatcher([matched])
    _patch_fetch(monkeypatch, [_item("m3")])

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: True)
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda item, company, client=None: dict(_BULLISH_HAIKU))

    # First cycle: classified + stored, one paid call.
    s1 = pipeline.run_once(matcher=matcher, budget=_FakeBudget(), store=store)
    assert s1["ai_calls"] == 1 and s1["classified"] == 1

    # Second cycle, SAME story: skipped before spending anything.
    b2 = _FakeBudget()
    s2 = pipeline.run_once(matcher=matcher, budget=b2, store=store)
    assert s2["already_seen"] == 1
    assert s2["classified"] == 0
    assert s2["ai_calls"] == 0
    assert b2.calls == 0                        # nothing billed the 2nd time


def test_over_budget_company_item_falls_back_to_free(monkeypatch, tmp_path):
    store = _store(tmp_path)
    _patch_fetch(monkeypatch, [_item("m4", title="Firm wins order worth 900cr")])
    matcher = _FakeMatcher([MatchedNews(
        item=_item("m4", title="Firm wins order worth 900cr"),
        matches=[_match("TCS")],
    )])

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: True)
    haiku_called = []
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda *a, **kw: haiku_called.append(1) or {})

    summary = pipeline.run_once(matcher=matcher, budget=_FakeBudget(allow=False),
                               store=store)

    assert summary["skipped_budget"] == 1
    assert haiku_called == []                   # never spent
    assert summary["ai_calls"] == 0
    assert summary["classified"] == 1           # still classified, for free
    assert summary["keyword_calls"] == 1


def test_paid_neutral_is_stored_as_marker_but_not_shown(monkeypatch, tmp_path):
    """A paid neutral verdict is stored (so we never pay for it again)
    but is excluded from the feed and not counted as HIGH/MID."""
    store = _store(tmp_path)
    _patch_fetch(monkeypatch, [_item("m5")])
    matcher = _FakeMatcher([MatchedNews(item=_item("m5"), matches=[_match("TCS")])])

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: True)
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda item, company, client=None: {
                            "direction": "neutral", "confidence": 30,
                            "materiality": "routine", "reason": "Routine.",
                        })

    summary = pipeline.run_once(matcher=matcher, budget=_FakeBudget(), store=store)

    assert summary["ai_calls"] == 1
    assert summary["high"] == 0 and summary["mid"] == 0
    assert store.exists("m5", "TCS")            # remembered (won't re-pay)
    assert store.recent() == []                 # but never shown


def test_free_keyword_neutral_noise_is_dropped_not_stored(monkeypatch, tmp_path):
    """Free-keyword neutral items (the 78% junk) are dropped and never
    stored."""
    store = _store(tmp_path)
    _patch_fetch(monkeypatch, [_item("m6", title="Please refer attachment")])
    matcher = _FakeMatcher([MatchedNews(
        item=_item("m6", title="Please refer attachment"),
        matches=[_match("TCS", tier="BROAD")],
    )])

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: False)

    summary = pipeline.run_once(matcher=matcher, budget=_FakeBudget(), store=store)

    assert summary["dropped_neutral"] == 1
    assert store.count() == 0                   # nothing stored
    assert not store.exists("m6", "TCS")


def test_haiku_mode_skips_when_not_configured(monkeypatch, tmp_path):
    store = _store(tmp_path)
    _patch_fetch(monkeypatch, [_item("m7")])
    matcher = _FakeMatcher([MatchedNews(
        item=_item("m7"), matches=[_match("TCS"), _match("INFY")]
    )])

    monkeypatch.setattr(pipeline, "NEWS_CLASSIFIER_MODE", "haiku")
    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: False)
    called = []
    monkeypatch.setattr(pipeline.classification, "classify",
                        lambda *a, **kw: called.append(1) or {})

    b = _FakeBudget()
    summary = pipeline.run_once(matcher=matcher, budget=b, store=store)

    assert summary["skipped_not_configured"] == 2
    assert summary["classified"] == 0
    assert called == []
    assert b.calls == 0


def test_classification_error_falls_back_to_keyword(monkeypatch, tmp_path):
    store = _store(tmp_path)
    title = "Firm wins order worth 700cr"
    _patch_fetch(monkeypatch, [_item("m8", title=title)])
    matcher = _FakeMatcher([MatchedNews(
        item=_item("m8", title=title), matches=[_match("TCS")]
    )])

    def boom(item, company, client=None):
        raise ClassificationError("boom")

    monkeypatch.setattr(pipeline.classification, "is_configured", lambda: True)
    monkeypatch.setattr(pipeline.classification, "classify", boom)

    b = _FakeBudget()
    summary = pipeline.run_once(matcher=matcher, budget=b, store=store)

    # Paid call attempted (and billed), failed, fell back to keyword.
    assert summary["ai_calls"] == 1
    assert b.calls == 1
    assert summary["errors"] == 1
    assert summary["keyword_calls"] == 1
    assert summary["classified"] == 1
    # The keyword read of "wins order" is bullish -> stored, not dropped.
    assert store.for_symbol("TCS")
    assert store.for_symbol("TCS")[0]["classifier"] == "keyword"
