"""
Tests for tools/fetch_history.py -- the historical pull command.

Drives the whole run() with a fake `post`, a temp CandleStore and a temp
DailyStore, so the wiring is proven end to end with no network and no
credentials. The point of these is the boring stuff that would otherwise
be found at 2am mid-download: resumability, a dead symbol not killing
the run, and the daily bars landing in the shape trend_structure reads.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backtest.candle_store import CandleStore
from core.daily_store import DailyStore
from core.trend_structure import analyse
from tools import fetch_history

IST = timezone(timedelta(hours=5, minutes=30))


def epoch(y, m, d, hh=9, mm=15):
    return int(datetime(y, m, d, hh, mm, tzinfo=IST).timestamp())


class FakeLoader:
    """Stands in for MasterLoader."""

    def __init__(self, mapping):
        self.mapping = mapping

    def all_symbols(self, include_blocked=False):
        return list(self.mapping)

    def security_id(self, symbol):
        return self.mapping.get(symbol)


@pytest.fixture
def stores(tmp_path):
    return (CandleStore(url=f"sqlite:///{tmp_path}/hist.db"),
            DailyStore(url=f"sqlite:///{tmp_path}/daily.db"))


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(fetch_history, "decision", lambda *a, **k: None)
    monkeypatch.setattr(fetch_history, "warn", lambda *a, **k: None)


def session_payload(day, minutes=3, close=100.0):
    times = [epoch(day.year, day.month, day.day, 9, 15 + i)
             for i in range(minutes)]
    n = len(times)
    return {"open": [close] * n, "high": [close + 1] * n,
            "low": [close - 1] * n, "close": [close] * n,
            "volume": [500] * n, "timestamp": times}


def make_post(intraday_payload=None, daily_payload=None, seen=None):
    def post(url, body):
        if seen is not None:
            seen.append((url, body))
        if "intraday" in url:
            return intraday_payload if intraday_payload is not None else \
                session_payload(datetime(2026, 7, 24).date())
        return daily_payload if daily_payload is not None else \
            {"open": [100.0], "high": [101.0], "low": [99.0],
             "close": [100.5], "volume": [9999],
             "timestamp": [epoch(2026, 7, 24, 15, 30)]}
    return post


# ----------------------------------------------------------

def test_a_run_writes_both_stores(stores):
    candles, daily = stores
    rc = fetch_history.run(days=5, post=make_post(), candles=candles,
                           daily=daily,
                           loader=FakeLoader({"PARAS": "1234"}))
    assert rc == 0
    assert candles.count() == 3
    assert daily.stats()["bars"] == 1


def test_daily_rows_are_readable_by_trend_structure(stores):
    """The whole reason for pulling daily bars: core/trend_structure.py
    must be able to analyse them without any translation layer."""
    candles, daily = stores
    days = [datetime(2026, 7, d).date() for d in (20, 21, 22, 23, 24)]
    payload = {
        "open": [100.0 + i for i in range(5)],
        "high": [101.0 + i for i in range(5)],       # stepping up
        "low": [99.0 + i for i in range(5)],
        "close": [100.5 + i for i in range(5)],
        "volume": [1000] * 5,
        "timestamp": [epoch(d.year, d.month, d.day, 15, 30) for d in days],
    }
    fetch_history.run(days=5, daily_only=True,
                      post=make_post(daily_payload=payload),
                      candles=candles, daily=daily,
                      loader=FakeLoader({"PARAS": "1234"}))
    result = analyse(daily.history("PARAS", days=7))
    assert result["structure"] == "STRONG_UP"
    assert result["hh_streak"] == 4


def test_rerunning_does_not_duplicate_a_single_bar(stores):
    """Resumability after a network drop is the whole safety story."""
    candles, daily = stores
    loader = FakeLoader({"PARAS": "1234"})
    for _ in range(3):
        fetch_history.run(days=5, post=make_post(), candles=candles,
                          daily=daily, loader=loader)
    assert candles.count() == 3
    assert daily.stats()["bars"] == 1


def test_daily_only_skips_the_intraday_endpoint(stores):
    candles, daily = stores
    seen = []
    fetch_history.run(days=5, daily_only=True,
                      post=make_post(seen=seen), candles=candles,
                      daily=daily, loader=FakeLoader({"X": "1"}))
    assert all("intraday" not in url for url, _ in seen)
    assert candles.count() == 0
    assert daily.stats()["bars"] == 1


def test_intraday_only_skips_the_daily_endpoint(stores):
    candles, daily = stores
    seen = []
    fetch_history.run(days=5, intraday_only=True,
                      post=make_post(seen=seen), candles=candles,
                      daily=daily, loader=FakeLoader({"X": "1"}))
    assert all("historical" not in url for url, _ in seen)
    assert daily.stats()["bars"] == 0


def test_a_symbol_with_no_security_id_is_skipped_not_fatal(stores):
    candles, daily = stores
    rc = fetch_history.run(
        days=5, post=make_post(), candles=candles, daily=daily,
        loader=FakeLoader({"GHOST": None, "REAL": "1234"}))
    assert rc == 0
    assert candles.symbols_for("2026-07-24") == ["REAL"]


def test_one_dead_symbol_does_not_kill_the_run(stores):
    """545 symbols, one 502 -- the other 544 must still land."""
    candles, daily = stores

    def post(url, body):
        if body["securityId"] == "666":
            raise RuntimeError("502 Bad Gateway")
        return make_post()(url, body)

    rc = fetch_history.run(days=5, post=post, candles=candles,
                           daily=daily,
                           loader=FakeLoader({"DEAD": "666",
                                              "ALIVE": "1234"}))
    assert rc == 0
    assert candles.symbols_for("2026-07-24") == ["ALIVE"]


def test_no_symbols_is_an_error_not_a_silent_success(stores):
    candles, daily = stores
    assert fetch_history.run(days=5, post=make_post(), candles=candles,
                             daily=daily, loader=FakeLoader({})) == 1


def test_explicit_symbols_override_the_universe(stores):
    candles, daily = stores
    fetch_history.run(days=5, symbols=["ONLYME"], post=make_post(),
                      candles=candles, daily=daily,
                      loader=FakeLoader({"ONLYME": "7", "OTHER": "8"}))
    assert candles.symbols_for("2026-07-24") == ["ONLYME"]


def test_pre_open_bars_never_reach_the_store(stores):
    """An 09:07 print inside the store would corrupt the 09:15-09:30
    opening range on replay."""
    candles, daily = stores
    day = datetime(2026, 7, 24).date()
    payload = {
        "open": [100.0, 100.0], "high": [101.0, 101.0],
        "low": [99.0, 99.0], "close": [100.0, 100.0],
        "volume": [1, 1],
        "timestamp": [epoch(day.year, day.month, day.day, 9, 7),
                      epoch(day.year, day.month, day.day, 9, 15)],
    }
    fetch_history.run(days=5, intraday_only=True,
                      post=make_post(intraday_payload=payload),
                      candles=candles, daily=daily,
                      loader=FakeLoader({"X": "1"}))
    minutes = [c["minute"][-8:] for c in candles.candles_for("2026-07-24")]
    assert minutes == ["09:15:00"]


# ----------------------------------------------------------
# the split check
# ----------------------------------------------------------

def test_split_report_is_silent_when_data_looks_adjusted(monkeypatch):
    warned = []
    monkeypatch.setattr(fetch_history, "warn", warned.append)
    fetch_history._report_splits([
        dict(symbol="X", date="2026-07-22", close=100.0),
        dict(symbol="X", date="2026-07-23", close=104.0),
    ])
    assert warned == []


def test_split_report_warns_on_an_unexplained_jump(monkeypatch):
    warned = []
    monkeypatch.setattr(fetch_history, "warn", warned.append)
    fetch_history._report_splits([
        dict(symbol="JLHL", date="2026-07-22", close=500.0),
        dict(symbol="JLHL", date="2026-07-23", close=100.0),
    ])
    text = " ".join(warned)
    assert "JLHL" in text and "UNEXPLAINED" in text


def test_split_report_handles_no_rows(monkeypatch):
    warned = []
    monkeypatch.setattr(fetch_history, "warn", warned.append)
    fetch_history._report_splits([])
    assert warned == []


@pytest.mark.parametrize("a,b,expected", [
    ("2026-07-23", "2026-07-23", 0),
    ("2026-07-24", "2026-07-23", 1),
    ("2026-07-22", "2026-07-23", -1),
])
def test_days_between(a, b, expected):
    assert fetch_history._days_between(a, b) == expected


def test_days_between_never_matches_on_garbage():
    assert abs(fetch_history._days_between("", "2026-07-23")) > 1
    assert abs(fetch_history._days_between(None, "2026-07-23")) > 1
