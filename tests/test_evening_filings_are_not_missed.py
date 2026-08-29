"""Board meetings finish after the close, and the bot never looked.

    "fix the announcement lookback so evening filings are not missed"
                                    -- operator, 29 August 2026

Every poll asked NSE for the last ANNOUNCEMENT_LOOKBACK_HOURS (8). At
a 09:00 start that reaches 01:00, so everything filed the previous
evening was invisible -- and 16:00 to 22:00 is exactly when
preferential issues, order wins and results get filed.

PRECWIRE is the case. A preferential issue published about 20:24 on
27 August; the bot's only copy arrived as a Telegram card at 12:24 the
NEXT day, by which time the stock was +8% on its way to a 20% upper
circuit. NSE had it sixteen hours earlier and nobody asked.

A bigger constant does not fix it. Eight hours misses Tuesday evening;
eighteen still misses FRIDAY evening on a Monday morning. The boundary
that is always right is the previous SESSION's close -- the same one
core/why_moving.py uses for every other evidence source.

Only on the FIRST pass, though: that window is 66 hours on a Monday,
and asking NSE for it every 60 seconds would get the bot blocked.
"""

from datetime import datetime, timedelta

import pytest

from core.announcement_watcher import AnnouncementWatcher

# 2026: Mon 31 Aug, Tue 1 Sep. Fri 28 Aug is the session before Monday.
MONDAY = datetime(2026, 8, 31, 9, 0)
TUESDAY = datetime(2026, 9, 1, 9, 0)


@pytest.fixture
def watcher():
    return AnnouncementWatcher(known_symbols=set(), lookback_hours=8)


def test_the_first_pass_reaches_the_previous_session_close(watcher):
    got = watcher._from_date(TUESDAY)
    assert got == datetime(2026, 8, 31, 15, 30), got


def test_a_monday_reaches_back_over_the_weekend(watcher):
    """Eighteen hours would stop at Sunday afternoon and miss every
    filing made on Friday evening."""
    got = watcher._from_date(MONDAY)
    assert got == datetime(2026, 8, 28, 15, 30), got
    assert (MONDAY - got) > timedelta(hours=60)


def test_the_precwire_filing_would_have_been_caught(watcher):
    """The case this was written for.

    Filed about 20:24 on Thursday 27 August; the bot starts Friday
    morning. Under the old 8-hour window it reached 01:00 and missed
    it by five hours.
    """
    filed = datetime(2026, 8, 27, 20, 24)
    start = datetime(2026, 8, 28, 9, 0)
    assert watcher._from_date(start) <= filed
    # and the old rule really did miss it
    assert start - timedelta(hours=8) > filed


def test_later_passes_go_back_to_the_ordinary_window(watcher):
    """A 66-hour ask every 60 seconds would be rude and would get us
    blocked. Nothing published since the last pass can be older than a
    minute anyway."""
    watcher._from_date(MONDAY)          # the deep one
    watcher._deep_pass_done = True
    got = watcher._from_date(MONDAY)
    assert got == MONDAY - timedelta(hours=watcher.lookback_hours)


def test_a_restart_at_noon_looks_deep_again(watcher):
    """A bot started at 14:00 has seen nothing yet -- it must not
    assume the morning's poller covered the evening for it."""
    afternoon = datetime(2026, 9, 1, 14, 0)
    assert watcher._from_date(afternoon) == datetime(2026, 8, 31, 15, 30)


def test_it_never_asks_for_less_than_the_ordinary_window(watcher):
    """The deep pass widens the window; it must never narrow it.

    Late in a session the previous close is more recent than
    now - lookback_hours, and taking the session boundary there would
    shrink the ask.
    """
    late = datetime(2026, 9, 1, 23, 30)
    got = watcher._from_date(late)
    assert got <= late - timedelta(hours=watcher.lookback_hours)


def test_a_broken_calendar_still_polls(watcher, monkeypatch):
    """Fail-open. No calendar means the ordinary window, never nothing."""
    import core.why_moving as wm

    def _boom(clock):
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(wm, "previous_trading_close", _boom)
    got = watcher._from_date(TUESDAY)
    assert got == TUESDAY - timedelta(hours=watcher.lookback_hours)
