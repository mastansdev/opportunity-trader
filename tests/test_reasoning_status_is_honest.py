"""
==========================================================
"Reasoning ON" must mean reasoning is on
==========================================================

    "bot is getting results, news. but i'm not sure whether bot knows
     it. stores it and reuses when ever the same situation arises."
                                -- operator, 12 August 2026

He was right to be unsure, and the screen was actively telling him the
wrong thing.

core/news_impact.py's status() computed:

    "reasoning_on": bool(os.environ.get("ANTHROPIC_API_KEY"))

_get_client() checks TWO things -- the key AND config.AI_ENABLED, the
master switch turned off on 10 August after every call came back
"credit balance is too low". status() checked only the key, which was
still sitting in .env. So main.py printed

    [IMPACT] 3736 stories, 5163 stock links, reasoning ON

every morning while the true count was zero.

Measured on data/news_memory.db:

    4 Aug    461 stories    361 reasoned
    5 Aug    430 stories      6 reasoned      <- collapse
    6-11 Aug 1561 stories     0 reasoned

Every impact link in that window is `how = keyword`, `direction =
UNKNOWN`. That is not cosmetic: core/ranker.py refuses a keyword match
outright -- "reason is a lookup, not a mechanism" -- so the ranked
entry lane was starved of reasons for a week, while the log said the
reasoning was running.

This is the same fault as "report success when the broker never
answered", which BOT_SPEC.md lists under what the bot must never do.

Author : H&M Opportunity Trader
==========================================================
"""

import os

import pytest

from core.news_impact import NewsImpact


@pytest.fixture
def impact(tmp_path):
    return NewsImpact(db_path=str(tmp_path / "n.db"))


def test_the_master_switch_being_off_means_reasoning_is_off(
        impact, monkeypatch):
    """THE REGRESSION. Key present, switch off -> OFF, not ON."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    import config
    monkeypatch.setattr(config, "AI_ENABLED", False)
    got = impact.status()
    assert got["reasoning_on"] is False, (
        "status() says reasoning is ON while config.AI_ENABLED is False. "
        "No client is ever built, so nothing reasons.")
    assert got["has_key"] is True
    assert got["ai_enabled"] is False


def test_a_missing_key_also_means_off(impact, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import config
    monkeypatch.setattr(config, "AI_ENABLED", True)
    got = impact.status()
    assert got["reasoning_on"] is False
    assert got["has_key"] is False


def test_both_true_means_on(impact, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    import config
    monkeypatch.setattr(config, "AI_ENABLED", True)
    assert impact.status()["reasoning_on"] is True


def test_it_names_which_switch_is_the_blocker(impact, monkeypatch):
    """"OFF" with no cause sends him to check the API key, which was
    never the problem. The panel has to say WHICH one to fix."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    import config
    monkeypatch.setattr(config, "AI_ENABLED", False)
    blocked = impact.status()["blocked_by"]
    assert blocked and "AI_ENABLED" in blocked

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "AI_ENABLED", True)
    blocked = impact.status()["blocked_by"]
    assert blocked and "ANTHROPIC_API_KEY" in blocked


def test_nothing_is_blocking_reads_as_no_blocker(impact, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    import config
    monkeypatch.setattr(config, "AI_ENABLED", True)
    assert impact.status()["blocked_by"] is None


def test_status_agrees_with_whether_a_client_can_be_built(
        impact, monkeypatch):
    """The two must never disagree again -- that disagreement IS the
    bug. If _get_client() would return None, status() must say OFF."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    import config
    monkeypatch.setattr(config, "AI_ENABLED", False)
    assert impact._get_client() is None
    assert impact.status()["reasoning_on"] is False


def test_the_startup_line_warns_rather_than_reporting_normally():
    """main.py printed this at decision() level -- the same level as
    everything that is working. A capability that is off belongs in
    warn(), where he actually looks."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8", errors="replace")
    block = src[src.index("[IMPACT]") - 200:]
    block = block[:block.index("_optional_morning_brief")]
    assert "REASONING OFF" in block
    assert "warn(" in block, (
        "an off capability is being reported as normal output")
