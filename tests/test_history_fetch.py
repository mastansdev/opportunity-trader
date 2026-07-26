"""
Tests for core/history_fetch.py -- the Dhan historical pull.

Written against the response shape in Dhan's own v2 docs (columnar
arrays + epoch timestamps), because the last time we wrote a parser
against a feed we had not looked at properly it took four attempts
(CALENDAR_AND_RESULTS.md). No network, no credentials: `post` is
injected.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from core import history_fetch
from core.history_fetch import (
    DAILY_URL, INTRADAY_URL, HistoryFetcher, RateLimiter, daily_body,
    in_session, intraday_body, parse_daily, parse_intraday,
    suspect_price_jumps, window_chunks,
)

IST = timezone(timedelta(hours=5, minutes=30))


def epoch(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=IST).timestamp())


def payload(times, o=None, h=None, l=None, c=None, v=None):
    n = len(times)
    return {
        "open": o if o is not None else [100.0] * n,
        "high": h if h is not None else [101.0] * n,
        "low": l if l is not None else [99.0] * n,
        "close": c if c is not None else [100.5] * n,
        "volume": v if v is not None else [1000] * n,
        "timestamp": times,
        "open_interest": [0] * n,
    }


# ----------------------------------------------------------
# parse_intraday -- the columnar -> row conversion
# ----------------------------------------------------------

def test_parses_the_documented_columnar_shape():
    rows = parse_intraday(
        payload([epoch(2026, 7, 24, 9, 15), epoch(2026, 7, 24, 9, 16)]),
        "PARAS")
    assert len(rows) == 2
    assert rows[0]["symbol"] == "PARAS"
    assert rows[0]["date"] == "2026-07-24"
    assert rows[0]["minute"] == "2026-07-24T09:15:00"
    assert rows[1]["minute"] == "2026-07-24T09:16:00"
    assert rows[0]["o"] == 100.0 and rows[0]["v"] == 1000.0


def test_minute_format_matches_the_live_recorder():
    """Historical and recorded bars must dedup against each other, so
    the `minute` string has to be byte-identical in shape."""
    rows = parse_intraday(payload([epoch(2026, 7, 24, 14, 3)]), "X")
    assert rows[0]["minute"] == "2026-07-24T14:03:00"
    assert len(rows[0]["minute"]) == 19


def test_epoch_is_read_as_IST_not_UTC():
    """A 5.5-hour error would put every candle in the wrong session and
    silently destroy the 09:15-09:30 opening range."""
    rows = parse_intraday(payload([epoch(2026, 7, 24, 9, 15)]), "X")
    assert rows[0]["minute"].endswith("09:15:00")


def test_bars_outside_trading_hours_are_dropped():
    """An 09:07 pre-open print inside the ORB window would poison the
    range the entire strategy is built on."""
    rows = parse_intraday(payload([
        epoch(2026, 7, 24, 9, 7),      # pre-open
        epoch(2026, 7, 24, 9, 15),     # first real minute
        epoch(2026, 7, 24, 15, 30),    # last real minute
        epoch(2026, 7, 24, 16, 2),     # post-close
    ]), "X")
    assert [r["minute"][-8:] for r in rows] == ["09:15:00", "15:30:00"]


def test_session_bounds_are_inclusive():
    assert in_session(datetime(2026, 7, 24, 9, 15, tzinfo=IST))
    assert in_session(datetime(2026, 7, 24, 15, 30, tzinfo=IST))
    assert not in_session(datetime(2026, 7, 24, 9, 14, tzinfo=IST))
    assert not in_session(datetime(2026, 7, 24, 15, 31, tzinfo=IST))


def test_impossible_candles_are_dropped():
    times = [epoch(2026, 7, 24, 9, 15), epoch(2026, 7, 24, 9, 16),
             epoch(2026, 7, 24, 9, 17)]
    rows = parse_intraday(payload(
        times,
        o=[100.0, 100.0, 500.0],      # 3rd: open above the high
        h=[101.0, 90.0, 101.0],       # 2nd: high below the low
        l=[99.0, 99.0, 99.0],
        c=[100.5, 100.5, 100.5],
    ), "X")
    assert len(rows) == 1
    assert rows[0]["minute"].endswith("09:15:00")


def test_missing_volume_still_yields_candles():
    p = payload([epoch(2026, 7, 24, 9, 15)])
    del p["volume"]
    rows = parse_intraday(p, "X")
    assert len(rows) == 1 and rows[0]["v"] is None


def test_length_mismatch_is_rejected_outright():
    """Zipping to the shortest array would mis-date every candle after
    the mismatch -- better to return nothing and be noticed."""
    p = payload([epoch(2026, 7, 24, 9, 15), epoch(2026, 7, 24, 9, 16)])
    p["high"] = [101.0]
    assert parse_intraday(p, "X") == []


@pytest.mark.parametrize("bad", [None, {}, [], "nope", {"open": 1}])
def test_malformed_payloads_return_empty_not_raise(bad):
    assert parse_intraday(bad, "X") == []
    assert parse_daily(bad, "X") == []


def test_a_single_unreadable_row_does_not_lose_the_rest():
    p = payload([epoch(2026, 7, 24, 9, 15), epoch(2026, 7, 24, 9, 16)])
    p["close"] = [100.5, "not-a-number"]
    rows = parse_intraday(p, "X")
    assert len(rows) == 1


# ----------------------------------------------------------
# parse_daily -- feeds core/daily_store.py
# ----------------------------------------------------------

def test_daily_rows_match_the_DailyStore_column_names():
    rows = parse_daily(payload([epoch(2026, 7, 24, 15, 30)]), "PARAS")
    assert rows[0]["symbol"] == "PARAS"
    assert rows[0]["date"] == "2026-07-24"
    assert set(rows[0]) == {"date", "symbol", "series", "open", "high",
                            "low", "close", "prev_close", "volume",
                            "turnover"}
    assert rows[0]["series"] == "EQ"


def test_daily_keeps_bars_outside_session_hours():
    """Daily bars are stamped at whatever hour Dhan chooses -- the
    intraday session filter must NOT apply here."""
    assert len(parse_daily(payload([epoch(2026, 7, 24, 0, 0)]), "X")) == 1


# ----------------------------------------------------------
# window_chunks -- the 90-day ceiling
# ----------------------------------------------------------

def test_a_short_range_is_one_request():
    assert window_chunks(date(2026, 5, 1), date(2026, 7, 24)) == [
        (date(2026, 5, 1), date(2026, 7, 24))]


def test_a_long_range_is_split_at_90_days():
    chunks = window_chunks(date(2025, 7, 26), date(2026, 7, 26))
    assert len(chunks) == 5
    assert chunks[0][0] == date(2025, 7, 26)
    assert chunks[-1][1] == date(2026, 7, 26)


def test_chunks_are_contiguous_and_never_overlap():
    chunks = window_chunks(date(2024, 1, 1), date(2026, 7, 26))
    for (_, end), (nxt, _) in zip(chunks, chunks[1:]):
        assert nxt == end + timedelta(days=1)
    assert all((e - s).days < 90 for s, e in chunks)


def test_an_inverted_range_yields_nothing():
    assert window_chunks(date(2026, 7, 26), date(2026, 1, 1)) == []


def test_a_single_day_is_one_chunk():
    d = date(2026, 7, 24)
    assert window_chunks(d, d) == [(d, d)]


# ----------------------------------------------------------
# request bodies
# ----------------------------------------------------------

def test_intraday_body_matches_the_documented_fields():
    body = intraday_body(1333, datetime(2026, 7, 24, 9, 15),
                         datetime(2026, 7, 24, 15, 30), interval="1")
    assert body == {
        "securityId": "1333", "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY", "interval": "1", "oi": False,
        "fromDate": "2026-07-24 09:15:00", "toDate": "2026-07-24 15:30:00",
    }


def test_daily_body_matches_the_documented_fields():
    body = daily_body("13061", date(2020, 1, 1), date(2026, 7, 26))
    assert body["securityId"] == "13061"
    assert body["fromDate"] == "2020-01-01"
    assert body["toDate"] == "2026-07-26"
    assert body["expiryCode"] == 0


def test_security_id_is_always_a_string():
    """master_stocks.csv gives ints; Dhan's docs show strings."""
    assert intraday_body(13061, datetime(2026, 7, 24, 9, 15),
                         datetime(2026, 7, 24, 15, 30))["securityId"] \
        == "13061"


# ----------------------------------------------------------
# rate limiting -- being throttled mid-run leaves a half-full DB
# ----------------------------------------------------------

def test_limiter_spaces_requests_out():
    slept, now = [], [0.0]
    lim = RateLimiter(per_second=4.0, sleep=slept.append,
                      clock=lambda: now[0])
    lim.wait()                     # first call is free
    assert slept == []
    lim.wait()                     # immediately after -> must wait 0.25s
    assert slept and slept[0] == pytest.approx(0.25)


def test_limiter_does_not_sleep_when_enough_time_has_passed():
    slept, now = [], [0.0]
    lim = RateLimiter(per_second=4.0, sleep=slept.append,
                      clock=lambda: now[0])
    lim.wait()
    now[0] = 10.0
    lim.wait()
    assert slept == []


# ----------------------------------------------------------
# HistoryFetcher -- retries, fail-open, request planning
# ----------------------------------------------------------

class FakeLimiter:
    def wait(self):
        pass


def fetcher(post, **kw):
    return HistoryFetcher(post, limiter=FakeLimiter(), sleep=lambda s: None,
                          **kw)


def test_intraday_issues_one_request_per_90_day_chunk():
    seen = []

    def post(url, body):
        seen.append((url, body))
        return payload([epoch(2026, 7, 24, 9, 15)])

    f = fetcher(post)
    f.intraday(1333, "X", date(2025, 7, 26), date(2026, 7, 26))
    assert len(seen) == 5
    assert all(u == INTRADAY_URL for u, _ in seen)


def test_daily_is_a_single_request_to_the_daily_url():
    seen = []

    def post(url, body):
        seen.append(url)
        return payload([epoch(2020, 1, 2, 15, 30)])

    f = fetcher(post)
    rows = f.daily(1333, "X", date(2015, 1, 1), date(2026, 7, 26))
    assert seen == [DAILY_URL]
    assert len(rows) == 1


def test_a_failing_symbol_is_retried_then_skipped(monkeypatch):
    """One dead symbol must cost that symbol, not the 545-symbol run."""
    monkeypatch.setattr(history_fetch, "warn", lambda *a, **k: None)
    calls = []

    def post(url, body):
        calls.append(body)
        raise RuntimeError("502 from Dhan")

    f = fetcher(post, retries=2)
    assert f.intraday(1333, "DEAD", date(2026, 7, 1), date(2026, 7, 24)) == []
    assert len(calls) == 3                 # 1 try + 2 retries
    assert f.failures and "DEAD" in f.failures[0][0]


def test_a_transient_failure_recovers_on_retry(monkeypatch):
    monkeypatch.setattr(history_fetch, "warn", lambda *a, **k: None)
    state = {"n": 0}

    def post(url, body):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("timeout")
        return payload([epoch(2026, 7, 24, 9, 15)])

    f = fetcher(post)
    assert len(f.intraday(1333, "X", date(2026, 7, 1), date(2026, 7, 24))) == 1
    assert f.failures == []


def test_request_count_is_tracked_against_the_daily_cap():
    """100,000 Data-API requests a day is the ceiling -- the runner needs
    to be able to see how close a pull gets."""
    f = fetcher(lambda url, body: payload([epoch(2026, 7, 24, 9, 15)]))
    f.intraday(1333, "X", date(2025, 7, 26), date(2026, 7, 26))
    assert f.requests_made == 5


def test_an_empty_payload_is_not_an_error():
    """A symbol listed after the window started simply has no bars."""
    f = fetcher(lambda url, body: payload([]))
    assert f.intraday(1333, "NEW", date(2026, 7, 1), date(2026, 7, 24)) == []
    assert f.failures == []


# ----------------------------------------------------------
# the split check
# ----------------------------------------------------------

def test_a_split_sized_gap_is_flagged():
    rows = [
        dict(symbol="JLHL", date="2026-07-22", close=500.0),
        dict(symbol="JLHL", date="2026-07-23", close=100.0),   # 2:10
        dict(symbol="OK", date="2026-07-22", close=100.0),
        dict(symbol="OK", date="2026-07-23", close=104.0),
    ]
    flagged = suspect_price_jumps(rows)
    assert len(flagged) == 1
    assert flagged[0]["symbol"] == "JLHL"
    assert flagged[0]["pct"] == pytest.approx(-80.0)


def test_ordinary_volatility_is_not_flagged():
    rows = [dict(symbol="X", date="2026-07-22", close=100.0),
            dict(symbol="X", date="2026-07-23", close=119.0)]
    assert suspect_price_jumps(rows) == []


def test_jumps_are_sorted_worst_first():
    rows = [dict(symbol="A", date="2026-07-22", close=100.0),
            dict(symbol="A", date="2026-07-23", close=60.0),
            dict(symbol="B", date="2026-07-22", close=100.0),
            dict(symbol="B", date="2026-07-23", close=10.0)]
    assert [f["symbol"] for f in suspect_price_jumps(rows)] == ["B", "A"]


def test_split_check_survives_missing_closes():
    assert suspect_price_jumps([dict(symbol="X", date="d", close=None)]) == []
