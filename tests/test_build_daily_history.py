"""
Tests for the daily-history backfill, specifically its handling of
trading holidays.

The nag this fixes: 2026-06-26 is a Friday with no bhavcopy (25 and 29
June are both present, so it was a holiday). Every re-run re-downloaded
it and re-printed a WARNING, which trains you to ignore warnings.
"""

from datetime import datetime

import pytest

from core.daily_store import DailyStore
from tools import build_daily_history as bdh


@pytest.fixture
def store(tmp_path):
    return DailyStore(url=f"sqlite:///{tmp_path}/daily.db")


def fake_bhavcopy(available):
    """A stand-in for the NSE download. `available` is a set of
    YYYY-MM-DD strings that "have" a file."""
    calls = []

    def _fetch(date=None, folder="data", quiet=False):
        key = date.strftime("%Y-%m-%d")
        calls.append(key)
        if key not in available:
            return []
        return [{"TckrSymb": "X", "SctySrs": "EQ", "OpnPric": "100",
                 "HghPric": "110", "LwPric": "90", "ClsPric": "105",
                 "PrvsClsgPric": "99", "TtlTradgVol": "1000",
                 "TtlTrfVal": "105000"}]

    _fetch.calls = calls
    return _fetch


def test_a_holiday_is_recorded_and_never_retried(store, monkeypatch):
    # Mon 2026-06-22 .. Fri 2026-06-26; the Friday is a holiday.
    available = {"2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25"}
    fetch = fake_bhavcopy(available)
    monkeypatch.setattr(bdh, "fetch_bhavcopy", fetch)
    today = datetime(2026, 7, 24)

    bdh.build(days=4, store=store, today=today)
    assert "2026-06-26" in store.no_data_dates()

    # Second run: the holiday must not be downloaded again.
    fetch.calls.clear()
    bdh.build(days=4, store=store, today=today)
    assert "2026-06-26" not in fetch.calls


def test_a_recent_miss_stays_retryable(store, monkeypatch):
    """Within a few days, an empty result may just mean NSE hasn't
    published yet -- writing it off as a holiday would permanently
    lose a real session."""
    fetch = fake_bhavcopy(set())
    monkeypatch.setattr(bdh, "fetch_bhavcopy", fetch)
    today = datetime(2026, 7, 24)          # Friday

    bdh.build(days=2, store=store, today=today)
    # 07-23 and 07-22 are inside the retry window -> not written off
    assert "2026-07-23" not in store.no_data_dates()
    assert "2026-07-22" not in store.no_data_dates()


def test_already_stored_days_are_not_redownloaded(store, monkeypatch):
    store.upsert_many([dict(date="2026-07-23", symbol="X", high=1,
                            low=1, close=1)])
    fetch = fake_bhavcopy({"2026-07-22", "2026-07-21"})
    monkeypatch.setattr(bdh, "fetch_bhavcopy", fetch)

    bdh.build(days=3, store=store, today=datetime(2026, 7, 24))
    assert "2026-07-23" not in fetch.calls


def test_weekends_are_never_fetched(store, monkeypatch):
    fetch = fake_bhavcopy({"2026-07-24", "2026-07-23"})
    monkeypatch.setattr(bdh, "fetch_bhavcopy", fetch)

    bdh.build(days=2, store=store, today=datetime(2026, 7, 27))  # Monday
    assert "2026-07-25" not in fetch.calls      # Saturday
    assert "2026-07-26" not in fetch.calls      # Sunday


def test_mark_no_data_is_idempotent(store):
    store.mark_no_data("2026-06-26")
    store.mark_no_data("2026-06-26", note="different note")
    assert store.no_data_dates() == {"2026-06-26"}


def test_holidays_do_not_consume_the_day_budget(store, monkeypatch):
    """Asking for 3 days must yield 3 STORED days, not 3 attempts."""
    available = {"2026-07-23", "2026-07-22", "2026-07-20"}   # 07-21 missing
    monkeypatch.setattr(bdh, "fetch_bhavcopy", fake_bhavcopy(available))

    stats = bdh.build(days=3, store=store, today=datetime(2026, 7, 24))
    assert stats["days"] == 3
