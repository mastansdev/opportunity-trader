"""The three channels that cost money were waiting for seven that don't.

    "daily focused channels: OrderBook Pulse, Day Trader Telugu,
     RedboxGlobal India = these channels will get posted on daily &
     event occuring times. so delay in getting their data into bot
     will cost us money."             -- operator, 24 August 2026
    "fix the telegram collector delay"           -- 29 August 2026

On 24 August those three were moved to the front of the pass. It did
not work, and the stored timestamps say so -- measured over 18-29
August, posted (`at`) against stored (`created_at`):

    Day Trader Telugu   958 messages   median 5.5m   p90 24.9m
    Breakouts           240            median 5.5m   p90  9.4m
    RedboxGlobal        171            median 5.6m   p90 12.9m

Because the poller was `wait(90s) -> poll() -> wait(90s)`, and poll()
walked EVERY channel and OCR-ed every image. The cycle was never 90
seconds; it was 90 plus the length of a whole pass. Being read first
does not help when you are still waiting for the previous pass to
finish reading seven channels you did not need.

So the daily channels get their own loop at POLL_SECONDS and the rest
get SLOW_POLL_SECONDS. Nothing is read less often than the exchange
publishes it -- the full pass still runs, it just no longer stands in
front of the order wins.
"""

import threading

import pytest

from core import telegram_feed
from core.telegram_feed import POLL_SECONDS, SLOW_POLL_SECONDS, TelegramFeed


@pytest.fixture
def feed(tmp_path):
    got = TelegramFeed(db_path=str(tmp_path / "tg.db"))
    got.channels = [
        {"handle": "orders_pulse", "name": "OrderBook Pulse"},
        {"handle": "daytradertelugu", "name": "Day Trader Telugu"},
        {"handle": "Indiaredboxglobal", "name": "RedboxGlobal India"},
        {"handle": "news_pulse_ai", "name": "News Pulse"},
        {"handle": "earnings_pulse", "name": "Earnings Pulse"},
        {"handle": "WLPulseBot", "name": "WLPulseBot"},
    ]
    return got


# ------------------------------------------------- who the fast loop reads

def test_the_fast_loop_reads_everything_that_posts_through_the_day(feed):
    """Not just the "daily" three -- everything not known to be quiet.

    ---- THE DEFAULT WAS THE WRONG WAY ROUND. 29 August 2026. ----
    This first selected FOR "daily", and he caught it at once:
    "telegram channels are still getting news, orderbook, business
    updates." News Pulse is not one of the daily three -- it resolves
    to "other" -- so it went to the five minute loop while posting
    news all day, 109 messages in the 18-29 August sample.

    An unclassified channel is one nobody has looked at, not one known
    to be quiet. Reading it too often costs seconds; reading it too
    rarely costs a trade.
    """
    picked = {c["handle"] for c in feed._channels_for(fast=True)}
    assert picked == {"orders_pulse", "daytradertelugu",
                      "Indiaredboxglobal", "news_pulse_ai"}
    assert "earnings_pulse" not in picked      # results season only
    assert "WLPulseBot" not in picked          # episodic by design


def test_a_channel_nobody_has_classified_is_read_fast(feed):
    """The fault above, as a rule. New channel, no entry in
    feed_clock -- it must land on the fast loop, not the slow one."""
    feed.channels.append({"handle": "brandnew", "name": "Brand New Feed"})
    picked = {c["handle"] for c in feed._channels_for(fast=True)}
    assert "brandnew" in picked


def test_the_slow_loop_still_reads_everything(feed):
    assert len(feed._channels_for(None)) == len(feed.channels)


def test_an_unresolvable_kind_reads_everything_rather_than_nothing(feed):
    """A slow pass is a cost. A blind pass is a fault.

    If channel_kind() ever stops recognising these names, the filter
    must fall back to the whole list -- never to an empty one.
    """
    feed.channels = [{"handle": "somethingnew", "name": "Something New"}]
    assert len(feed._channels_for(fast=True)) == 1


# ------------------------------------------------- the pass honours it

def test_a_filtered_pass_touches_only_those_channels(feed, monkeypatch):
    asked = []

    class _Client:
        def fetch(self, handle, limit=30):
            asked.append(handle)
            return []

    feed.client = _Client()
    monkeypatch.setattr(feed, "_prune", lambda: None)
    feed.poll(fast=True)
    assert asked == ["orders_pulse", "daytradertelugu",
                     "Indiaredboxglobal", "news_pulse_ai"]

    asked.clear()
    feed.poll()
    assert len(asked) == len(feed.channels), "the full pass lost a channel"


def test_one_channel_failing_does_not_cost_the_others(feed, monkeypatch):
    seen = []

    class _Client:
        def fetch(self, handle, limit=30):
            seen.append(handle)
            if handle == "daytradertelugu":
                raise RuntimeError("t.me returned 502")
            return []

    feed.client = _Client()
    monkeypatch.setattr(feed, "_prune", lambda: None)
    feed.poll(fast=True)
    assert seen == ["orders_pulse", "daytradertelugu",
                    "Indiaredboxglobal", "news_pulse_ai"]


# ------------------------------------------------- two loops, both stopped

def test_both_loops_start_and_both_stop(feed, monkeypatch):
    """A daemon thread nobody joins is how a session hangs on Ctrl+C."""
    monkeypatch.setattr(feed, "poll", lambda **kw: 0)
    before = threading.active_count()
    feed.start(every_seconds=0.05)
    assert feed._thread is not None and feed._thread.is_alive()
    assert feed._slow_thread is not None and feed._slow_thread.is_alive()
    feed.stop()
    assert feed._thread is None and feed._slow_thread is None
    assert threading.active_count() <= before + 1


def test_the_full_pass_is_never_faster_than_the_daily_one(feed, monkeypatch):
    """Two loops reading the same channels at the same rate is just the
    old behaviour with an extra thread."""
    assert SLOW_POLL_SECONDS >= POLL_SECONDS

    seconds = []
    real = threading.Thread

    class _Spy(real):
        def __init__(self, *a, **kw):
            if kw.get("args"):
                seconds.append(kw["args"][1])
            super().__init__(*a, **kw)
            self.daemon = True

    monkeypatch.setattr(telegram_feed.threading, "Thread", _Spy)
    monkeypatch.setattr(feed, "poll", lambda **kw: 0)
    feed.start(every_seconds=POLL_SECONDS)
    feed.stop()
    assert seconds == [POLL_SECONDS, SLOW_POLL_SECONDS]
