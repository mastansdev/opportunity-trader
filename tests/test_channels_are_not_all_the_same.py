"""A quiet channel is only a fault if it was supposed to post.

    "how many times i need to tell you about Earnings Pulse = post data
     only at results time ... WLPulse bot = This channel will not give
     us updates daily , its premium bot with capacity of 100 stocks to
     track . Business Pulse = this channel will post whenever they
     receive updates about any company business updates."
    "daily focused channels: OrderBook Pulse, Day Trader Telugu ,
     RedboxGlobal India ... so delay in getting their data into bot
     will cost us money."
                                    -- operator, 24 August 2026

He has said this more than once. On 24 August I read a 4-day-old
watermark on Business Pulse and reported it as a broken feed.
"""

from datetime import date

from core.feed_clock import (DAILY_CHANNELS, EPISODIC_CHANNELS,
                             RESULTS_CHANNELS, channel_kind,
                             expected_today)

IN_SEASON = date(2026, 8, 14)       # Q1 deadline
OFF_SEASON = date(2026, 8, 24)      # ten days later


def test_the_three_daily_channels_are_named():
    assert set(DAILY_CHANNELS) == {
        "OrderBook Pulse", "Day Trader Telugu", "RedboxGlobal India"}


def test_a_daily_channel_is_always_expected():
    for name in DAILY_CHANNELS:
        assert channel_kind(name) == "daily"
        assert expected_today(name, OFF_SEASON) is True
        assert expected_today(name, IN_SEASON) is True


def test_an_episodic_channel_is_never_owed_a_post():
    # "will post whenever they receive updates" is not a schedule.
    for name in EPISODIC_CHANNELS:
        assert channel_kind(name) == "episodic"
        assert expected_today(name, OFF_SEASON) is False
        assert expected_today(name, IN_SEASON) is False


def test_business_pulse_quiet_for_days_is_not_a_broken_feed():
    assert expected_today("Business Pulse", OFF_SEASON) is False


def test_a_results_channel_follows_the_season():
    for name in RESULTS_CHANNELS:
        assert channel_kind(name) == "results"
        assert expected_today(name, IN_SEASON) is True
        assert expected_today(name, OFF_SEASON) is False


def test_an_unknown_channel_says_it_cannot_tell():
    # Not False. "I do not know" must not read as "expected silent".
    assert channel_kind("News Pulse") == "other"
    assert expected_today("News Pulse", OFF_SEASON) is None
    assert expected_today("", OFF_SEASON) is None


def test_gaps_marks_quiet_and_stale_apart():
    from core.feed_clock import gaps
    for row in gaps():
        assert "quiet" in row and "stale" in row and "kind" in row
        # Anything not expected to post can be quiet but never stale.
        if row["expected_today"] is False:
            assert row["stale"] is False


# ==========================================================
#  THE DAILY THREE ARE READ FIRST
# ==========================================================
#     "so delay in getting their data into bot will cost us money"

def test_the_daily_channels_are_polled_before_the_rest():
    """Using the strings the LIVE folder hands over, not display names.

    core/telegram_client.channels_in_folder() returns `username or
    title`. On 24 August the real ten were:

        Earnings Pro, Breakouts, daytradertelugu, news_pulse_ai,
        Earnings 360, orders_pulse, earnings_pulse, Business Pulse,
        Indiaredboxglobal, WLPulseBot

    Three of the names in DAILY_CHANNELS appear NOWHERE in that list.
    A test written with "OrderBook Pulse" would have passed while the
    live poller prioritised nothing.
    """
    from core.telegram_feed import TelegramFeed
    folder = ["Earnings Pro", "Breakouts", "daytradertelugu",
              "news_pulse_ai", "Earnings 360", "orders_pulse",
              "earnings_pulse", "Business Pulse", "Indiaredboxglobal",
              "WLPulseBot"]
    feed = TelegramFeed(channels=folder, db_path=":memory:")
    names = [c["name"] for c in feed.channels]
    assert set(names[:3]) == {"daytradertelugu", "orders_pulse",
                              "Indiaredboxglobal"}, names
    # Stable: the rest keep folder order.
    assert names[3:] == ["Earnings Pro", "Breakouts", "news_pulse_ai",
                         "Earnings 360", "earnings_pulse",
                         "Business Pulse", "WLPulseBot"]


def test_a_handle_and_its_title_are_the_same_channel():
    from core.feed_clock import canonical_channel, channel_kind
    for handle, title in (("orders_pulse", "OrderBook Pulse"),
                          ("daytradertelugu", "Day Trader Telugu"),
                          ("Indiaredboxglobal", "RedboxGlobal India"),
                          ("earnings_pulse", "Earnings Pulse")):
        assert canonical_channel(handle) == title
        assert channel_kind(handle) == channel_kind(title)


def test_every_daily_channel_is_reachable_by_a_live_handle():
    # The guard against this whole class of bug: each name in
    # DAILY_CHANNELS must be produced by some string the folder emits.
    from core.feed_clock import canonical_channel
    folder = ["daytradertelugu", "orders_pulse", "Indiaredboxglobal"]
    assert {canonical_channel(h) for h in folder} == set(DAILY_CHANNELS)


def test_nothing_is_dropped_by_the_reordering():
    from core.telegram_feed import TelegramFeed
    given = [{"handle": f"@c{i}", "name": f"Chan {i}", "kind": "text"}
             for i in range(6)]
    feed = TelegramFeed(channels=given, db_path=":memory:")
    assert len(feed.channels) == 6
