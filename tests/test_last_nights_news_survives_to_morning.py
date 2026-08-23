"""Evidence published after the close must count for the next session.

    "for bot from 09 - 15:30 complete trading whenever opportunity saw
     & after market hours news/telegram channels updates will recevie ,
     store & use them when the opportunity occurs"
                                        -- operator, 23 August 2026

The defect: both the PRO-channel lookup and the filing lookup carried
the session an item was POSTED in, not the session it acts on. 62% of
the stored channel feed (5,350 of 8,661 stock events) is posted outside
09:15-15:30 and was discarded every morning.
"""

from datetime import datetime

from core.why_moving import (from_events, from_filing,
                             previous_trading_close)

TUE = "2026-08-25"          # Tuesday
MON = "2026-08-24"          # Monday


def _event(at):
    return [{"symbol": "SBIN", "at": at, "kind": "ORDER",
             "source": "orderbook pulse",
             "headline": "SBIN bags Rs 500 crore order from NHAI"}]


def _filing(at):
    return {"symbol": "SBIN", "kind": "ORDER_WIN", "filed_at": at,
            "subject": "bags order worth Rs 500 cr from NHAI"}


# ---- the channels ----

def test_last_nights_channel_post_is_the_reason_this_morning():
    assert from_events(_event("2026-08-24T21:00:00"), on_date=TUE)


def test_a_post_minutes_after_the_close_survives():
    assert from_events(_event("2026-08-24T16:10:00"), on_date=TUE)


def test_the_weekend_does_not_erase_friday_evening():
    assert from_events(_event("2026-08-21T18:30:00"), on_date=MON)
    assert from_events(_event("2026-08-22T11:00:00"), on_date=MON)


def test_yesterdays_in_session_news_is_still_not_todays_reason():
    # The docstring rule that was there before, unchanged: a stock that
    # moved on Monday at 14:00 already moved on it.
    assert from_events(_event("2026-08-24T14:00:00"), on_date=TUE) is None
    assert from_events(_event("2026-08-21T14:00:00"), on_date=MON) is None


def test_todays_own_session_still_counts():
    assert from_events(_event("2026-08-25T10:30:00"), on_date=TUE)


def test_next_weeks_post_cannot_explain_this_morning():
    assert from_events(_event("2026-08-26T10:00:00"), on_date=TUE) is None


def test_an_undated_event_does_not_slip_through():
    rows = _event("")
    assert from_events(rows, on_date=TUE) is None


# ---- filings, the same window ----

def test_a_filing_after_the_close_counts_tomorrow():
    assert from_filing(_filing("2026-08-24T21:00:00"),
                       now=datetime(2026, 8, 25, 11, 0))


def test_a_friday_evening_filing_counts_on_monday():
    assert from_filing(_filing("2026-08-21T18:30:00"),
                       now=datetime(2026, 8, 24, 11, 0))


def test_a_previous_session_filing_does_not():
    assert from_filing(_filing("2026-08-24T14:00:00"),
                       now=datetime(2026, 8, 25, 11, 0)) is None


# ---- the shared rule ----

def test_the_window_starts_at_the_previous_trading_close():
    monday = previous_trading_close(datetime(2026, 8, 25, 11, 0))
    assert (monday.hour, monday.minute) == (15, 30)
    assert monday.date() == datetime(2026, 8, 24).date()


def test_across_a_weekend_it_reaches_back_to_friday():
    friday = previous_trading_close(datetime(2026, 8, 24, 11, 0))
    assert friday.date() == datetime(2026, 8, 21).date()
    assert (friday.hour, friday.minute) == (15, 30)


def test_it_never_raises_on_a_bad_clock():
    # This runs on the trading loop.
    assert previous_trading_close(datetime(2026, 1, 1, 9, 0)) is not None


# ==========================================================
#  THE STAMPS ARE UTC. THE SESSION IS NOT.
# ==========================================================
# 16,247 of 16,407 stored events carry "+00:00". Deleting the offset
# instead of applying it moves every stamp 5h30m earlier and lands on
# exactly the window this file is about: 20:00 IST is 14:30 UTC, which
# read naively falls BEFORE a 15:30 close.

from core.why_moving import _local_naive


def test_a_utc_stamp_is_converted_not_truncated():
    got = _local_naive("2026-08-21T14:30:00+00:00")
    assert (got.hour, got.minute) == (20, 0)
    assert got.day == 21


def test_a_naive_stamp_is_already_local():
    got = _local_naive("2026-08-21T20:00:00")
    assert (got.hour, got.minute) == (20, 0)


def test_a_utc_evening_post_survives_the_weekend():
    # Friday 20:00 IST, stored as 14:30 UTC.
    assert from_events(_utc_event("2026-08-21T14:30:00+00:00"),
                       on_date=MON)


def test_a_utc_in_session_post_still_does_not():
    # Friday 14:00 IST, stored as 08:30 UTC.
    assert from_events(_utc_event("2026-08-21T08:30:00+00:00"),
                       on_date=MON) is None


def test_rubbish_stamps_do_not_raise():
    assert _local_naive("not a date") is None
    assert _local_naive("") is None
    assert _local_naive(None) is None


def _utc_event(at):
    return [{"symbol": "SBIN", "at": at, "kind": "ORDER",
             "source": "orderbook pulse",
             "headline": "SBIN bags Rs 500 crore order from NHAI"}]
