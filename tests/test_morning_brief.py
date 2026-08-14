"""
Tests for core/morning_brief.py -- the AI layer.

The operator's architecture, drawn six months ago:

    AI + NEWS ENGINE + BOT MEMORY + MY EXPERIENCE + EARNING PULSE DATA

Three of those were built. The AI never existed -- a grep on 2026-07-28
returned zero hits for anthropic, openai, claude, llm or gpt.

The rule this module is held to: it ADVISES, it never ACTS. And when it
cannot say anything honest, it says nothing at all. A confident brief
generated from no data is worse than a blank space, because a blank
space cannot mislead anyone.
"""

import json

import pytest

from core.morning_brief import MorningBrief

PREMARKET = """OVERNIGHT PICTURE  (collected 2026-07-29 08:05:00)

  US
    S&P 500            6,141.00  +0.67%
    Nasdaq            20,110.00  +1.10%
"""


class FakeMessage:
    def __init__(self, text):
        self.content = [type("P", (), {"text": text})()]


class FakeClient:
    def __init__(self, text="US markets closed higher overnight.",
                 raises=False):
        self.calls = []
        self._text = text
        self._raises = raises
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("api down")
        return FakeMessage(self._text)


def _brief(tmp_path, client):
    return MorningBrief(client=client, store_path=str(tmp_path / "b.json"))


# ---------------------------------------------------------------
# It writes a brief
# ---------------------------------------------------------------

def test_it_writes_a_brief_from_the_overnight_numbers(tmp_path):
    client = FakeClient("US markets closed higher. Crude was quiet.")
    text = _brief(tmp_path, client).generate(PREMARKET)
    assert "US markets closed higher" in text
    assert PREMARKET in client.calls[0]["messages"][0]["content"]


def test_the_system_prompt_forbids_naming_stocks(tmp_path):
    """The one instruction that keeps it a briefing rather than a tip."""
    client = FakeClient()
    _brief(tmp_path, client).generate(PREMARKET)
    system = client.calls[0]["system"].lower()
    assert "never name a stock" in system
    assert "never predict a direction" in system


# ---------------------------------------------------------------
# NO BRIEF is a valid answer -- and always better than a made-up one
# ---------------------------------------------------------------

def test_no_client_means_no_brief_not_a_generic_paragraph(tmp_path):
    assert _brief(tmp_path, None).generate(PREMARKET) is None


def test_no_overnight_data_means_no_brief(tmp_path):
    """A brief written from nothing would be fiction."""
    client = FakeClient()
    result = _brief(tmp_path, client).generate("No overnight data collected.")
    assert result is None
    assert client.calls == []          # never even asked


def test_an_api_failure_produces_no_brief(tmp_path):
    assert _brief(tmp_path, FakeClient(raises=True)).generate(PREMARKET) is None


def test_an_empty_response_produces_no_brief(tmp_path):
    assert _brief(tmp_path, FakeClient(text="")).generate(PREMARKET) is None


def test_a_failed_brief_leaves_today_empty(tmp_path):
    brief = _brief(tmp_path, FakeClient(raises=True))
    brief.generate(PREMARKET)
    assert brief.today() is None
    assert brief.snapshot()["available"] is False


# ---------------------------------------------------------------
# Every brief is RECORDED so it can be judged
# ---------------------------------------------------------------

def test_each_brief_is_stored_with_what_it_saw(tmp_path):
    """In a month there will be twenty, and they can be read back
    against what actually happened. Same discipline as the reason
    gate: it earns a vote only once the numbers say so."""
    path = str(tmp_path / "b.json")
    MorningBrief(client=FakeClient("Quiet night."), store_path=path).generate(PREMARKET)
    saved = json.load(open(path, encoding="utf-8"))
    assert saved[0]["brief"] == "Quiet night."
    assert "S&P 500" in saved[0]["context"]
    assert saved[0]["date"] and saved[0]["model"]


def test_history_keeps_the_newest_first(tmp_path):
    path = str(tmp_path / "b.json")
    for text in ("first", "second", "third"):
        MorningBrief(client=FakeClient(text), store_path=path).generate(PREMARKET)
    history = MorningBrief(client=None, store_path=path).history()
    assert [h["brief"] for h in history] == ["third", "second", "first"]


def test_history_is_capped(tmp_path):
    path = str(tmp_path / "b.json")
    for i in range(70):
        MorningBrief(client=FakeClient(f"day {i}"), store_path=path).generate(PREMARKET)
    assert len(MorningBrief(client=None, store_path=path).history(limit=999)) == 60


def test_a_broken_store_never_breaks_the_brief(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("not json", encoding="utf-8")
    brief = MorningBrief(client=FakeClient("still works"), store_path=str(path))
    assert brief.generate(PREMARKET) == "still works"


# ---------------------------------------------------------------
# It ADVISES. It never ACTS.
# ---------------------------------------------------------------

def test_nothing_in_the_engine_reads_the_brief():
    """If the engine ever imports this, an unvalidated opinion has
    started spending money."""
    import os
    for name in ("core/engine.py", "core/strategy.py",
                 "core/results_gate.py", "trading/live_execution.py"):
        if os.path.exists(name):
            assert "morning_brief" not in open(name, encoding="utf-8").read()


def test_the_snapshot_labels_it_as_opinion(tmp_path):
    brief = _brief(tmp_path, FakeClient("Quiet night."))
    brief.generate(PREMARKET)
    snap = brief.snapshot()
    assert "opinion" in snap["note"].lower()
    assert "nothing in the bot acts on this" in snap["note"].lower()
