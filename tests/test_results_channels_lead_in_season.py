"""In results season the results channels lead. Out of it they wait.

    "this is n times i told you. bot must follow the NSE calendar -
     follow results period . (only that time bot prioritizes the
     result channels from telegram too)"
                                        -- operator, 30 August 2026

SLOW_KINDS held "results" unconditionally, so Earnings Pulse,
Earnings 360 and Earnings Pro sat on the five minute loop on 14
August -- the Q1 deadline and the busiest filing day of the quarter --
for precisely the same reason they sit there on a quiet Tuesday in
September. 269 of the 275 companies that reported between 13 and 29
August filed on the 13th and 14th.

core/results_calendar.in_results_season() has known the answer since
it was written, off the SEBI Regulation 33 deadlines:

    Q3  15 Jan - 14 Feb        Q1  15 Jul - 14 Aug
    Q4  15 Apr - 30 May        Q2  15 Oct - 14 Nov

Only core/feed_clock.py ever asked it, and only to decide whether a
quiet channel counted as a fault. The poller never asked at all.

The calendar is consulted TWICE, because neither reading alone is
enough. The window catches the bulk; symbols_on() catches a straggler
filing outside it -- one company is scheduled for 31 August 2026, and
the Q1 window closed on the 14th.
"""

import datetime

import pytest

from core.telegram_feed import TelegramFeed


@pytest.fixture
def feed():
    got = TelegramFeed.__new__(TelegramFeed)
    got.channels = [
        {"handle": "orders_pulse", "name": "OrderBook Pulse"},
        {"handle": "daytradertelugu", "name": "Day Trader Telugu"},
        {"handle": "earnings_pulse", "name": "Earnings Pulse"},
        {"handle": "WLPulseBot", "name": "WLPulseBot"},
    ]
    return got


def _names(rows):
    return [r["name"] for r in rows]


# ------------------------------------------------------- the calendar itself

def test_the_deadline_week_is_in_season():
    feed = TelegramFeed.__new__(TelegramFeed)
    assert feed._results_matter_today(datetime.date(2026, 8, 14)) is True
    assert feed._results_matter_today(datetime.date(2026, 10, 20)) is True
    assert feed._results_matter_today(datetime.date(2026, 2, 10)) is True


def test_a_quiet_late_august_is_not():
    """His own example from the module: 24 August is not results
    season, 14 August is. By the 24th the filings are done."""
    feed = TelegramFeed.__new__(TelegramFeed)
    assert feed._results_matter_today(datetime.date(2026, 8, 24)) is False


def test_a_straggler_outside_the_window_still_counts(feed, monkeypatch):
    """One company is scheduled for 31 August 2026 and the Q1 window
    shut on the 14th. A date-range test alone would read that day as
    off-season and leave the results channels on the slow loop on the
    one morning they had something to say."""
    import core.results_calendar as rc

    monkeypatch.setattr(rc, "in_results_season", lambda day=None: False)

    class OneReports:
        def symbols_on(self, day=None):
            return {"SOMECO"}

    monkeypatch.setattr(rc, "ResultsCalendar", OneReports)
    assert feed._results_matter_today(datetime.date(2026, 8, 31)) is True


# ----------------------------------------------------- what the loop then reads

def test_out_of_season_the_results_channel_waits(feed, monkeypatch):
    monkeypatch.setattr(feed, "_results_matter_today", lambda day=None: False)
    got = _names(feed._channels_for(fast=True))
    assert "Earnings Pulse" not in got
    assert "OrderBook Pulse" in got and "Day Trader Telugu" in got


def test_in_season_the_results_channel_leads(feed, monkeypatch):
    monkeypatch.setattr(feed, "_results_matter_today", lambda day=None: True)
    got = _names(feed._channels_for(fast=True))
    assert "Earnings Pulse" in got, (
        "the Q1 deadline is the busiest filing day of the quarter and "
        "the results channel was still on the five minute loop")


def test_season_never_promotes_an_episodic_channel(feed, monkeypatch):
    """"only that time bot prioritizes the RESULT channels." Season is
    not a reason to read WLPulseBot more often."""
    monkeypatch.setattr(feed, "_results_matter_today", lambda day=None: True)
    assert "WLPulseBot" not in _names(feed._channels_for(fast=True))


def test_the_full_pass_is_unchanged_either_way(feed, monkeypatch):
    """fast=None reads everything. The season decides ORDER of
    attention, never whether a channel is read at all."""
    for answer in (True, False):
        monkeypatch.setattr(feed, "_results_matter_today",
                            lambda day=None, a=answer: a)
        assert len(feed._channels_for(None)) == 4


def test_a_broken_calendar_does_not_make_the_pass_blind(feed, monkeypatch):
    """Out of season is the behaviour that has shipped for weeks. An
    error must fall back to that, not drop channels."""
    import core.results_calendar as rc

    def boom(day=None):
        raise RuntimeError("calendar unreadable")

    monkeypatch.setattr(rc, "in_results_season", boom)
    assert feed._results_matter_today() is False
    assert len(feed._channels_for(fast=True)) == 2


def test_a_single_reporting_company_promotes_the_results_channels():
    """---- CAUGHT BY THE CALENDAR ITSELF. 31 August 2026. ----

    MILKYMIST reported on 31 August -- one company, outside the Q1
    window, which shut on the 14th. symbols_on() saw it, the results
    channels moved to the 90-second loop, and three tests written on
    30 August failed because they had assumed the quiet Sunday they
    were written on.

    The feature was right and the tests were dated. This pins the
    behaviour that surprised them, so a one-company day is a case the
    suite states rather than stumbles into.
    """
    import datetime

    from core.telegram_feed import TelegramFeed
    from core.results_calendar import ResultsCalendar

    day = datetime.date(2026, 8, 31)
    reporting = ResultsCalendar().symbols_on(day)
    assert reporting, "31 August 2026 had a reporter; the fixture is stale"

    feed = TelegramFeed.__new__(TelegramFeed)
    assert feed._results_matter_today(day) is True, (
        "a company reporting today must lift the results channels onto "
        "the fast loop, whatever the SEBI window says")
