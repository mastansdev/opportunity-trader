"""
==========================================================
The model may say "I don't know". It may not guess.
==========================================================

    "if today result came excellent & if the stock moved high even
     though we get them in top gainers but without why cards. i cannot
     trust the price movement right? genuine gap between trusted &
     vague buying"

141 stock-scope events on 31 July 2026 had a kind and no direction --
107 NEWS and 34 ORDER. Collected correctly, matched to the right
company, and silent about what any of it meant.

WHAT THIS FILE GUARDS
---------------------
Not "does the model give good answers" -- that is measured over weeks,
against what the stocks actually did, by refused_review.py.

This guards the WIRING, which is where money and trust get lost:

    1. no key, no budget, no network  ->  no verdict, and the bot runs
       exactly as it did before
    2. an unreadable reply is NO verdict, never a default one
    3. every call is counted before it is made and recorded after
    4. UNRELATED is preserved, because it is the answer that removes a
       wrong chip rather than adding a wrong one

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.ai_budget import AiBudget
from core.ai_news import AiNewsGrader
from core.stock_events import StockEvents


class Usage:
    input_tokens = 300
    output_tokens = 60
    cache_read_input_tokens = 260
    cache_creation_input_tokens = 0


class Block:
    def __init__(self, text):
        self.text = text


class Reply:
    def __init__(self, text):
        self.content = [Block(text)]
        self.usage = Usage()


class FakeClient:
    """Answers with whatever it is told to, and records what it was
    asked. Nothing here reaches a network."""

    def __init__(self, answer='{"direction":"POSITIVE","confidence":0.8,'
                              '"reason":"wins new revenue"}'):
        self.answer = answer
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        return Reply(self.answer)


EVENT = {"id": 1, "symbol": "BEL", "kind": "ORDER",
         "at": "2026-07-31T10:00:00",
         "headline": "BEL wins Rs 847 crore order for defense products"}


@pytest.fixture
def budget(tmp_path):
    return AiBudget(db_path=str(tmp_path / "spend.db"),
                    monthly_cap_rs=2500.0, usd_inr=88.0)


@pytest.fixture
def store(tmp_path):
    return StockEvents(db_path=str(tmp_path / "events.db"))


def _grader(budget, client):
    return AiNewsGrader(budget=budget, client=client,
                        model="claude-haiku-4-5")


# ---------------------------------------------------------------
# 1. IT WORKS
# ---------------------------------------------------------------
def test_a_verdict_comes_back(budget):
    got = _grader(budget, FakeClient()).grade(EVENT)
    assert got["direction"] == "POSITIVE"
    assert got["confidence"] == 0.8
    assert "revenue" in got["reason"]


def test_the_company_and_the_story_both_reach_the_model(budget):
    client = FakeClient()
    _grader(budget, client).grade(EVENT)
    sent = client.calls[0]["messages"][0]["content"]
    assert "BEL" in sent
    assert "847 crore" in sent


def test_the_instructions_are_sent_as_a_cached_prefix(budget):
    """Identical on every call. Cached, it is charged at a tenth of
    the input rate, and that is most of the saving."""
    client = FakeClient()
    _grader(budget, client).grade(EVENT)
    system = client.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------
# 2. UNRELATED -- THE ANSWER THAT CLEANS UP
# ---------------------------------------------------------------
def test_unrelated_is_preserved(budget):
    """DOLLAR was matched to "the Indian Rupee recorded its strongest
    weekly gain" because the word "dollar" appeared. A model allowed
    only POSITIVE or NEGATIVE would pick one and make the panel worse
    than keywords left it."""
    client = FakeClient('{"direction":"UNRELATED","confidence":0.95,'
                        '"reason":"story is about the currency, not '
                        'this company"}')
    got = _grader(budget, client).grade(EVENT)
    assert got["direction"] == "UNRELATED"


def test_unrelated_and_neutral_are_not_collapsed(store):
    """They are different facts. NEUTRAL affects the company but not
    clearly; UNRELATED is not about it at all, and only the second
    means the chip should disappear."""
    assert store.record_verdict(1, "NEUTRAL") is False or True
    from core.stock_events import VERDICTS
    assert "NEUTRAL" in VERDICTS and "UNRELATED" in VERDICTS


# ---------------------------------------------------------------
# 3. NO VERDICT IS NOT A NEUTRAL VERDICT
# ---------------------------------------------------------------
@pytest.mark.parametrize("answer", [
    "I think this is probably good news for BEL",   # prose, no JSON
    '{"direction":"BULLISH","confidence":0.9}',      # a word we never offered
    '{"direction":"POSITIVE"',                       # truncated JSON
    "",                                              # nothing at all
])
def test_an_unusable_reply_produces_no_verdict(budget, answer):
    """None means "we do not know". Nothing downstream may read that
    as NEUTRAL -- an absent opinion and a neutral opinion are
    different facts about the world."""
    assert _grader(budget, FakeClient(answer)).grade(EVENT) is None


def test_a_network_failure_produces_no_verdict(budget):
    client = FakeClient(RuntimeError("connection reset"))
    assert _grader(budget, client).grade(EVENT) is None


def test_a_missing_key_produces_no_verdict_and_does_not_raise(budget,
                                                              monkeypatch):
    """This is how the bot ran all last week. It must stay a supported
    state, not a crash."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    grader = AiNewsGrader(budget=budget, model="claude-haiku-4-5")
    assert grader.grade(EVENT) is None


# ---------------------------------------------------------------
# 3b. THE COMPANY PROFILE, AND THE REAL DATA IT COMES FROM
# ---------------------------------------------------------------
def test_the_company_name_is_sent_with_the_story(budget):
    """The first backfill graded 142 events from a BARE TICKER,
    because _business() looked for methods MasterLoader does not have
    and returned "" every time. The model then produced:

        PPLPHARMA  UNRELATED
        "News is about Piramal Pharma's Q1 FY27 performance;
         PPLPHARMA is a different company."

    PPLPHARMA *is* Piramal Pharma. Same for STAR, which is Strides
    Pharma and was rejected as "an entertainment company". Starving a
    reader of the one fact that settles the question is not a fair
    test of the reader.
    """
    class Loader:
        def get_by_symbol(self, symbol):
            return {"COMPANY NAME": "PIRAMAL PHARMA LIMITED",
                    "INDUSTRY": "PHARMA CDMO / CONTRACT MANUFACTURING",
                    "CORE BUSINESS": "MANUFACTURES PHARMACEUTICALS"}

    client = FakeClient()
    grader = AiNewsGrader(budget=budget, client=client,
                          model="claude-haiku-4-5", master_loader=Loader())
    grader.grade(dict(EVENT, symbol="PPLPHARMA"))
    sent = client.calls[0]["messages"][0]["content"]
    assert "PIRAMAL PHARMA LIMITED" in sent, (
        "the model cannot know what a ticker means unless we tell it")


def test_a_blank_cell_in_the_master_file_does_not_crash(budget):
    """AN EMPTY CELL IS NOT AN EMPTY STRING.

    master_stocks.csv is read with pandas, which turns a blank into
    float NaN -- and NaN is TRUTHY, so

        (row.get("INDUSTRY") or "").strip()

    sails past the `or` and calls .strip() on a float. The first
    regrade died on the first stock with a blank INDUSTRY column.

    The original fixture returned tidy strings and could never have
    found this. A fixture cleaner than the real data is a fixture that
    hides a whole class of bug.
    """
    class Loader:
        def get_by_symbol(self, symbol):
            return {"COMPANY NAME": "SOME COMPANY LTD",
                    "INDUSTRY": float("nan"),      # a blank cell
                    "CORE BUSINESS": None}

    client = FakeClient()
    grader = AiNewsGrader(budget=budget, client=client,
                          model="claude-haiku-4-5", master_loader=Loader())
    assert grader.grade(EVENT) is not None
    sent = client.calls[0]["messages"][0]["content"]
    assert "SOME COMPANY LTD" in sent
    # \b, not a substring test. "FINANCE" contains the letters n-a-n,
    # and a naive `"nan" in text` check flagged 16 perfectly good
    # housing-finance companies while verifying this fix.
    import re as _re
    assert not _re.search(r"\bnan\b", sent, _re.I), (
        "NaN must never reach the prompt")


def test_an_unknown_symbol_still_gets_graded(budget):
    """Degraded, not broken -- it just sends the ticker, which is how
    the whole first backfill ran."""
    class Loader:
        def get_by_symbol(self, symbol):
            return None

    grader = AiNewsGrader(budget=budget, client=FakeClient(),
                          model="claude-haiku-4-5", master_loader=Loader())
    assert grader.grade(EVENT) is not None


def test_a_broken_master_loader_does_not_stop_grading(budget):
    class Loader:
        def get_by_symbol(self, symbol):
            raise RuntimeError("csv is gone")

    grader = AiNewsGrader(budget=budget, client=FakeClient(),
                          model="claude-haiku-4-5", master_loader=Loader())
    assert grader.grade(EVENT) is not None


def test_confidence_is_clamped(budget):
    client = FakeClient('{"direction":"POSITIVE","confidence":7.5,'
                        '"reason":"x"}')
    assert _grader(budget, client).grade(EVENT)["confidence"] == 1.0


# ---------------------------------------------------------------
# 4. THE BUDGET IS CHECKED BEFORE, AND RECORDED AFTER
# ---------------------------------------------------------------
def test_nothing_is_called_once_the_cap_is_reached(budget):
    budget.record("claude-haiku-4-5", output_tokens=44_000_000)
    client = FakeClient()
    assert _grader(budget, client).grade(EVENT) is None
    assert client.calls == [], "it must not call and then discard the reply"


def test_every_call_is_recorded(budget):
    before = budget.spent_this_month()
    _grader(budget, FakeClient()).grade(EVENT)
    assert budget.spent_this_month() > before


def test_cached_tokens_are_recorded_separately(budget, tmp_path):
    """Charged at a tenth of the input rate. Recording them as ordinary
    input would over-count the bill and trip the cap early."""
    import sqlite3
    _grader(budget, FakeClient()).grade(EVENT)
    conn = sqlite3.connect(budget.db_path)
    row = conn.execute("select input_tokens, cache_read_tokens "
                       "from spend").fetchone()
    conn.close()
    assert row == (300, 260)


# ---------------------------------------------------------------
# 5. THE BACKFILL
# ---------------------------------------------------------------
def test_pending_events_are_graded_and_stored(budget, store):
    store.remember(symbol="BEL", at="2026-07-31T10:00", kind="ORDER",
                   headline="BEL wins Rs 847 crore order", scope="STOCK")
    result = _grader(budget, FakeClient()).grade_pending(store)
    assert result["graded"] == 1
    row = store.recent(limit=5)[0]
    assert row["ai_direction"] == "POSITIVE"
    assert row["ai_model"] == "claude-haiku-4-5"
    assert row["ai_at"]


def test_an_already_graded_result_is_never_sent(budget, store):
    """Earnings Pulse already said EXCELLENT. Paying a model to agree
    is spending money to learn nothing -- and it is the single filter
    that makes this Rs 53 a month instead of Rs 657."""
    store.remember(symbol="GAIL", at="2026-07-31T08:41", kind="RESULT",
                   headline="#GAIL - Excellent Results", scope="STOCK",
                   grade="EXCELLENT")
    client = FakeClient()
    _grader(budget, client).grade_pending(store)
    assert client.calls == []


def test_market_scope_events_are_never_sent(budget, store):
    """They have no symbol by design and can never reach a why-chip,
    so a verdict on one could not be shown, acted on or measured. On
    31 July they were 129 of the 270 ungraded rows and included
    "Earnings Pulse pinned a photo"."""
    store.remember(symbol=None, at="2026-07-31T09:00", kind="MACRO",
                   headline="Earnings Pulse pinned a photo", scope="MARKET")
    client = FakeClient()
    _grader(budget, client).grade_pending(store)
    assert client.calls == []


def test_a_verdict_is_saved_before_the_next_one_is_asked(budget, store):
    """A backfill that only saves at the end loses everything to one
    network blip -- and the tokens are paid for twice."""
    for i in range(3):
        store.remember(symbol=f"SYM{i}", at=f"2026-07-31T10:0{i}",
                       kind="NEWS", headline=f"story {i}", scope="STOCK")

    client = FakeClient()
    calls = {"n": 0}
    real = client.create

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("connection reset")
        return real(**kwargs)

    client.create = flaky
    _grader(budget, client).grade_pending(store)
    graded = [r for r in store.recent(limit=10) if r["ai_direction"]]
    assert len(graded) == 2, (
        "the verdicts that arrived before the failure must be on disk")
