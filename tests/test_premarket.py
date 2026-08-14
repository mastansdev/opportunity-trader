"""
Tests for core/premarket.py.

    "why can't we use bot for collecting the information from every
     source & store them into memory? in this era of AI! again why
     human needs to manual check?"          -- operator, 2026-07-28

The rule this module is held to: a number the bot could not fetch is
reported as MISSING, never guessed and never shown as zero. A pre-market
panel displaying crude at 0.00 is worse than one saying "could not
fetch", because zero looks like data.
"""

import json

import pytest

from core.premarket import PreMarket, parse_yahoo, SOURCES

# Real shape of Yahoo's v8/chart response, trimmed. Stooq was tried
# first (2026-07-28) and every quote URL 404'd across six variants --
# the endpoint is gone, not the symbols.
GOOD = json.dumps({"chart": {"result": [{"meta": {
    "regularMarketPrice": 7428.78,
    "chartPreviousClose": 7411.98,
    "previousClose": 7411.98,
    "currency": "USD",
    "marketState": "CLOSED",
}}], "error": None}})

NO_DATA = json.dumps({"chart": {"result": None,
                                "error": {"code": "Not Found"}}})


def _pm(tmp_path, fetcher):
    return PreMarket(fetcher=fetcher, store_path=str(tmp_path / "pm.json"))


# ---------------------------------------------------------------
# Reading a quote
# ---------------------------------------------------------------

def test_it_reads_a_real_yahoo_response():
    """The numbers are from a live call on 2026-07-28."""
    quote = parse_yahoo(GOOD)
    assert quote["last"] == 7428.78
    assert quote["change_pct"] == pytest.approx(0.23, abs=0.01)
    assert quote["previous"] == 7411.98


def test_an_error_response_is_MISSING_not_zero():
    """Yahoo returns result:null for an unknown symbol. That must read
    as missing, never as a number."""
    assert parse_yahoo(NO_DATA) is None


def test_junk_never_becomes_a_number():
    for junk in (None, "", "garbage", "{}", "[]", '{"chart":{}}'):
        assert parse_yahoo(junk) is None


def test_a_zero_price_is_refused():
    row = json.dumps({"chart": {"result": [{"meta": {
        "regularMarketPrice": 0, "chartPreviousClose": 0}}]}})
    assert parse_yahoo(row) is None


def test_a_missing_previous_close_still_gives_the_price():
    """No % change is honest. Refusing the whole quote would not be."""
    row = json.dumps({"chart": {"result": [{"meta": {
        "regularMarketPrice": 7428.78}}]}})
    quote = parse_yahoo(row)
    assert quote["last"] == 7428.78
    assert "change_pct" not in quote


def test_the_change_uses_the_PRIOR_SESSION_not_the_range_start():
    """chartPreviousClose is the close before the requested range began.
    With range=5d that is six sessions back -- it reported crude at
    -10.65% and the Nikkei at -7.13% "overnight" on 2026-07-28. Neither
    happened. previousClose is the prior SESSION and must win."""
    row = json.dumps({"chart": {"result": [{"meta": {
        "regularMarketPrice": 100.0,
        "previousClose": 99.0,             # yesterday -- the right one
        "chartPreviousClose": 110.0,       # six days ago -- the wrong one
    }}]}})
    quote = parse_yahoo(row)
    assert quote["change_pct"] == pytest.approx(1.01, abs=0.01)
    assert quote["previous"] == 99.0


def test_a_market_that_has_not_opened_falls_back_to_previous_close():
    """At 06:00 IST the Nikkei may have no regularMarketPrice yet.
    Yesterday's close is real data; zero is not."""
    row = json.dumps({"chart": {"result": [{"meta": {
        "previousClose": 39500.0, "chartPreviousClose": 39500.0}}]}})
    assert parse_yahoo(row)["last"] == 39500.0


# ---------------------------------------------------------------
# Collecting
# ---------------------------------------------------------------

def test_a_full_collection_stores_everything(tmp_path):
    pm = _pm(tmp_path, lambda symbol: GOOD)
    assert pm.refresh() == len(SOURCES)
    assert pm.get("sp500")["last"] == 7428.78
    assert pm.get("crude")["last"] == 7428.78


def test_it_survives_a_restart(tmp_path):
    """A restart at 09:10 must not mean eighteen fresh HTTP requests
    before the feed can start."""
    path = str(tmp_path / "pm.json")
    PreMarket(fetcher=lambda s: GOOD, store_path=path).refresh()
    reloaded = PreMarket(fetcher=None, store_path=path)
    assert reloaded.get("sp500")["last"] == 7428.78


def test_one_dead_source_does_not_lose_the_others(tmp_path):
    def fetcher(symbol):
        if symbol == "CL=F":
            raise RuntimeError("stooq down")
        return GOOD
    pm = _pm(tmp_path, fetcher)
    assert pm.refresh() == len(SOURCES) - 1
    assert pm.get("sp500") is not None
    assert pm.get("crude") is None


def test_a_source_that_fails_LATER_keeps_its_old_value_but_is_marked(tmp_path):
    """Blanking the panel loses information. Showing a stale price as if
    it were live is worse. So: keep it, and mark it."""
    path = str(tmp_path / "pm.json")
    PreMarket(fetcher=lambda s: GOOD, store_path=path).refresh()

    def only_sp500(symbol):
        if symbol == "^GSPC":
            return GOOD
        raise RuntimeError("down")

    pm = PreMarket(fetcher=only_sp500, store_path=path)
    pm.refresh()
    assert pm.get("crude")["last"] == 7428.78
    assert pm.get("crude")["stale"] is True
    assert pm.get("sp500").get("stale") is not True


def test_no_fetcher_collects_nothing_rather_than_crashing(tmp_path):
    assert _pm(tmp_path, None).refresh() == 0


def test_a_fetcher_that_always_raises_is_survivable(tmp_path):
    def explode(symbol):
        raise RuntimeError("no network")
    pm = _pm(tmp_path, explode)
    assert pm.refresh() == 0
    assert pm.snapshot()["available"] is False


# ---------------------------------------------------------------
# What the dashboard gets
# ---------------------------------------------------------------

def test_the_snapshot_is_grouped_and_json_safe(tmp_path):
    pm = _pm(tmp_path, lambda s: GOOD)
    pm.refresh()
    snap = pm.snapshot()
    # AGAINST SOURCES, not a copy of it. 4 August 2026 -- this listed
    # the six groups by hand and went red the moment EUROPE was added,
    # which is a test failing because the feature worked. What matters
    # is that every group in SOURCES reaches the snapshot and none is
    # invented on the way.
    from core.premarket import SOURCES
    assert set(snap["groups"]) == {source[3] for source in SOURCES}
    assert "EUROPE" in snap["groups"]
    json.dumps(snap)


def test_an_unfetched_row_is_marked_unavailable_not_zero(tmp_path):
    """The whole point. A blank must never render as a number."""
    pm = _pm(tmp_path, lambda s: NO_DATA)
    pm.refresh()
    for rows in pm.snapshot()["groups"].values():
        for row in rows:
            assert row["available"] is False
            assert row["last"] is None


def test_the_text_briefing_reads_like_english(tmp_path):
    pm = _pm(tmp_path, lambda s: GOOD)
    pm.refresh()
    text = pm.as_text()
    assert "OVERNIGHT PICTURE" in text
    assert "S&P 500" in text
    assert "Crude oil" in text


def test_the_text_briefing_says_so_when_there_is_nothing(tmp_path):
    assert "No overnight data" in _pm(tmp_path, None).as_text()


def test_failures_are_named_in_the_snapshot(tmp_path):
    def no_crude(symbol):
        if symbol == "CL=F":
            raise RuntimeError("down")
        return GOOD
    pm = _pm(tmp_path, no_crude)
    pm.refresh()
    assert "Crude oil" in pm.snapshot()["failed"]


# ---------------------------------------------------------------
# EIGHTEEN REQUESTS IN A ROW IS WHY IT FAILED, 3 August 2026
# ---------------------------------------------------------------
#
# data/premarket.json was found with fetched_at 17:24:38 and ALL
# EIGHTEEN sources in "failed" -- crude, gold, the dollar, both US
# yields, every index. Run again by hand minutes later it collected all
# eighteen first time:
#
#     py -c "from core.premarket import PreMarket, requests_fetcher; \
#            PreMarket(fetcher=requests_fetcher()).refresh()"
#     [PREMARKET] 18 overnight numbers collected.
#
# Nothing was broken. The loop fired eighteen requests at Yahoo with no
# pause and no second attempt, and Yahoo throttles that. It is
# all-or-nothing, and the thing lost is the whole overnight picture --
# the exact inputs the operator asked to be watched continuously.

def test_a_source_that_fails_once_is_retried(tmp_path):
    """One refused request must not cost the number for the session."""
    seen = {"n": 0}

    def flaky(symbol):
        seen["n"] += 1
        if seen["n"] == 1:
            raise RuntimeError("429 too many requests")
        return GOOD

    pm = _pm(tmp_path, flaky)
    assert pm.refresh() == len(SOURCES)
    assert pm.snapshot()["failed"] == []


def test_it_gives_up_after_a_few_tries_rather_than_hanging(tmp_path):
    from core.premarket import RETRIES
    tries = {"n": 0}

    def dead(symbol):
        tries["n"] += 1
        raise RuntimeError("down")

    pm = _pm(tmp_path, dead)
    pm.refresh()
    assert tries["n"] == len(SOURCES) * RETRIES


def test_only_the_live_fetcher_waits_between_requests():
    """The pause belongs on the network path only. A test double that
    slept 0.4s eighteen times per call would add minutes to the suite,
    and a slow suite is a suite that stops being run."""
    from core.premarket import requests_fetcher
    assert getattr(requests_fetcher(), "throttle", False) is True
    assert getattr(lambda s: GOOD, "throttle", False) is False


def test_a_run_that_collects_nothing_does_not_look_fresh(tmp_path):
    """     The file said fetched_at 17:24 while every number in it was
            hours older, so it read as current at a glance.

    fetched_at answers "when did we last try". Only last_success_at
    answers "when did data last arrive", and a failed run must never
    move it."""
    path = str(tmp_path / "pm.json")
    good = PreMarket(fetcher=lambda s: GOOD, store_path=path)
    good.refresh()
    first = json.load(open(path))["last_success_at"]
    assert first

    def dead(symbol):
        raise RuntimeError("throttled")

    PreMarket(fetcher=dead, store_path=path).refresh()
    after = json.load(open(path))
    assert after["last_success_at"] == first, "a failed run moved it"
    assert len(after["failed"]) == len(SOURCES)
    # And it is not simply frozen -- a run that DOES collect moves it.
    PreMarket(fetcher=lambda s: GOOD, store_path=path).refresh()
    assert json.load(open(path))["last_success_at"]
    assert json.load(open(path))["failed"] == []


def test_a_total_failure_keeps_the_old_numbers_but_marks_every_one(tmp_path):
    path = str(tmp_path / "pm.json")
    PreMarket(fetcher=lambda s: GOOD, store_path=path).refresh()

    def dead(symbol):
        raise RuntimeError("throttled")

    pm = PreMarket(fetcher=dead, store_path=path)
    pm.refresh()
    quotes = json.load(open(path))["quotes"]
    assert quotes, "the previous picture was thrown away"
    assert all(q["stale"] for q in quotes.values())


# ---------------------------------------------------------------
# It interprets NOTHING -- deliberately
# ---------------------------------------------------------------

def test_it_offers_no_opinion_anywhere():
    """The operator's own chart draws 'crude up -> banks benefit'. Every
    arrow in that chain is obvious backwards and unreliable forwards.
    This module reports facts; the AI briefing that reads them comes
    later, marked as opinion and recorded so it can be judged."""
    source = open("core/premarket.py", encoding="utf-8").read()
    for word in ("bullish", "bearish", "should rise", "will fall",
                 "recommend", "buy signal"):
        assert word not in source.lower().replace("-- see", "")
