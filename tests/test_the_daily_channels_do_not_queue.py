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


# ------------------------------------------------- and it says how late

def _store_message(feed, channel, posted, seen):
    """One row, straight in -- the shapes the store actually holds."""
    import sqlite3
    conn = sqlite3.connect(feed.db_path)
    conn.execute(
        "INSERT OR IGNORE INTO messages (channel, message_id, at, text,"
        " symbols, seen_at) VALUES (?,?,?,?,?,?)",
        (channel, f"{channel}-{posted}", posted, "x", "", seen))
    conn.commit()
    conn.close()


def test_it_reports_how_late_the_messages_were(feed):
    """It knew and never said.

    Every row carries `at` and `seen_at`, and core/feed_clock.py's own
    note calls the difference pure collection lag. Nothing read it --
    the 5.7-minute median that split this poller in two was measured
    by hand, off the store, weeks after the fact.
    """
    from datetime import datetime

    _store_message(feed, "OrderBook Pulse",
                   "2026-08-31T04:00:00+00:00", "2026-08-31T09:33:00")
    _store_message(feed, "News Pulse",
                   "2026-08-31T04:10:00+00:00", "2026-08-31T09:45:00")
    feed._lags = []
    feed._report_lag(datetime(2026, 8, 31, 9, 0))
    got = feed.lag_summary()
    assert got["messages"] == 2
    assert 3.0 <= got["median_min"] <= 6.0, got


def test_a_backfill_is_not_reported_as_a_lag(feed):
    """The bot was off on 28 August and stored 227 messages from the
    day before when it came back. Measured naively that is a
    1,440-minute delay and a warning about a feed that is fine."""
    from datetime import datetime

    _store_message(feed, "Day Trader Telugu",
                   "2026-08-30T04:00:00+00:00", "2026-08-31T09:33:00")
    feed._lags = []
    feed._report_lag(datetime(2026, 8, 31, 9, 0))
    assert feed.lag_summary() == {}, "a catch-up was counted as lateness"


def test_a_clock_that_runs_backwards_is_ignored(feed):
    from datetime import datetime

    _store_message(feed, "News Pulse",
                   "2026-08-31T10:00:00+00:00", "2026-08-31T09:33:00")
    feed._lags = []
    feed._report_lag(datetime(2026, 8, 31, 9, 0))
    assert feed.lag_summary() == {}


def test_the_two_stamps_are_read_on_the_same_clock(feed):
    """`at` carries a UTC offset and `seen_at` does not. Comparing them
    raw reports every message as five and a half hours late."""
    from datetime import datetime

    _store_message(feed, "OrderBook Pulse",
                   "2026-08-31T04:00:00+00:00", "2026-08-31T09:32:00")
    feed._lags = []
    feed._report_lag(datetime(2026, 8, 31, 9, 0))
    got = feed.lag_summary()
    assert got["median_min"] < 60, (
        f"the offset was not applied: {got}")


def test_no_summary_before_anything_arrives(feed):
    feed._lags = []
    assert feed.lag_summary() == {}


# ------------------------------- reaching back over the shut market

def test_the_first_pass_asks_for_more_than_the_rest(feed):
    """Nothing collects while the market is shut.

    main.py exits on a non-trading day -- "Nothing to do -- exiting" --
    and the collector goes with it. He noticed: the store's last row
    one Saturday evening was 18:09 and he had seen a message at 21:29.

    Everything posted between then and Monday's open arrives only when
    the next session starts and the first pass reaches back for it.
    Thirty was not far enough: over 14-17 August, Earnings Pulse posted
    42 messages in that window, so the twelve OLDEST -- Friday
    evening's, the ones that decide Monday's gaps -- were dropped.
    """
    from core.telegram_feed import DEFAULT_LIMIT, FIRST_PASS_LIMIT

    assert FIRST_PASS_LIMIT > DEFAULT_LIMIT
    assert feed._next_limit() == FIRST_PASS_LIMIT
    assert feed._next_limit() == DEFAULT_LIMIT
    assert feed._next_limit() == DEFAULT_LIMIT


def test_the_deep_ask_covers_a_weekend_of_the_busiest_channel(feed):
    """42 was the most any channel posted over a Friday-to-Monday gap
    in the store. The first ask has to clear that with room."""
    from core.telegram_feed import FIRST_PASS_LIMIT

    assert FIRST_PASS_LIMIT >= 60, (
        "a first pass that cannot cover a weekend loses Friday evening")


def test_the_poller_uses_the_deep_ask_on_its_first_cycle(feed, monkeypatch):
    """The limit has to reach poll(), not just exist."""
    asked = []
    monkeypatch.setattr(feed, "poll",
                        lambda **kw: asked.append(kw.get("limit")) or 0)
    feed.start(every_seconds=0.05)
    import time
    time.sleep(0.35)
    feed.stop()
    assert asked, "the poller never ran"
    from core.telegram_feed import DEFAULT_LIMIT, FIRST_PASS_LIMIT
    assert FIRST_PASS_LIMIT in asked, asked
    assert asked.count(FIRST_PASS_LIMIT) == 1, (
        f"the deep ask repeated: {asked}")
    assert DEFAULT_LIMIT in asked, asked


# ------------------------------- not re-reading what is already held

class _Impact:
    def __init__(self):
        self.seen = []

    def record(self, **kw):
        self.seen.append(kw.get("headline"))


def _msg(post_id, text, at="2026-08-31T04:00:00+00:00"):
    return {"id": str(post_id), "text": text, "at": at}


def test_a_post_already_on_file_is_skipped_before_any_parsing(feed):
    """His words: "the bot is doing over than asked to do in this
    telegram data getting by re running multiple same info".

    Rows were never duplicated -- the insert is OR IGNORE on
    (channel, message_id). But everything BEFORE the insert ran on all
    thirty messages every ninety seconds: hashtag matching,
    symbols_in() over the text, and a news_impact database round trip
    for each.
    """
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    impact = _Impact()
    feed.news_impact = impact

    first = [_msg(100, "GOLDIAM INTERNATIONAL: CO WINS EXPORT ORDER RS 50 CR")]
    assert feed._store(channel, first) == 1
    assert len(impact.seen) == 1

    # the very next pass sees the same post again
    impact.seen.clear()
    assert feed._store(channel, first) == 0
    assert impact.seen == [], "the story was filed a second time"


def test_a_newer_post_is_still_stored(feed):
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    feed._store(channel, [_msg(100, "an older story, long enough to count")])
    assert feed._store(
        channel, [_msg(101, "HCC secures Rs 524 crore NHPC contract")]) == 1


def test_the_floor_does_not_block_a_catch_up(feed):
    """A gap NEWER than what we hold is stored either way."""
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    feed._store(channel, [_msg(100, "what we had when the bot stopped")])
    gap = [_msg(103, "posted while the collector was down, three"),
           _msg(102, "posted while the collector was down, two"),
           _msg(101, "posted while the collector was down, one")]
    assert feed._store(channel, gap) == 3


def test_a_hole_in_the_middle_is_still_fillable(feed):
    """The case I got WRONG, and the one that matters.

    I reasoned that a gap is always newer than what we hold, so the id
    floor was safe everywhere. It is not.
    tests/test_telegram_catchup.py caught it in one run -- "49 posts
    inside the range were never recovered", "630 posts from the
    weekend were lost".

    Hold 1000-1050 from before a stop and 1100-1150 from after the
    restart: the newest id is 1150, so a floor of 1150 skips the whole
    1051-1099 hole -- which is exactly what catch_up() exists to fill.

    So catch_up passes skip_known=False, and the live poll keeps the
    floor. This is the test my own first version did not have.
    """
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    feed._store(channel, [_msg(100, "before the bot stopped, long enough")])
    feed._store(channel, [_msg(150, "after the restart, also long enough")])

    hole = [_msg(120, "inside the hole, posted while it was down")]
    # the live poll skips it -- id is under the newest we hold
    assert feed._store(channel, hole) == 0
    # the catch-up walk must not
    assert feed._store(channel, hole, skip_known=False) == 1


def test_the_floor_is_taken_once_per_page(feed):
    """A row stored earlier in a page must not raise the bar on the
    rest of that same page."""
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    feed._store(channel, [_msg(100, "the newest thing already on file")])
    page = [_msg(105, "newest of the batch, plenty of words here"),
            _msg(104, "middle of the batch, plenty of words here"),
            _msg(103, "oldest of the batch, plenty of words here")]
    assert feed._store(channel, page) == 3


def test_an_unreadable_post_id_is_not_skipped(feed):
    """Skipping is an optimisation, never a requirement. A channel
    whose ids are not numbers keeps the old behaviour."""
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    feed._store(channel, [_msg(100, "something already on file here")])
    assert feed._store(
        channel, [_msg("abc-xyz", "a post whose id is not a number")]) == 1


def test_an_empty_store_has_no_floor(feed):
    channel = {"name": "News Pulse", "handle": "news_pulse_ai"}
    assert feed._store(channel, [_msg(7, "the first thing ever seen here")]) == 1


# --------------------------------- not re-reading pictures it has read

def test_a_picture_already_transcribed_is_not_read_again(feed, monkeypatch):
    """It knew, and it re-read them anyway.

        "timestamps for this purpose right? does bot knows about last
         arrival of msgs/news/events from telegram"    -- operator

    It does: feed_watermark holds the last post id and time per
    channel, and every stored message carries its own ocr_text. But
    _ocr_cache lives in MEMORY and dies with the process, so
    catch_up() -- which walks back over pages it has mostly seen --
    paid full OCR on every screenshot again.

    Measured on a Sunday-morning restart: 3.5 minutes at 35% CPU, still
    on page 1 of 7, of the first of ten channels. Day Trader Telugu had
    581 transcripts already on disk.
    """
    channel = {"name": "Day Trader Telugu", "handle": "daytradertelugu"}
    reads = []

    def _never(url, data=None):
        reads.append(url)
        return "SHOULD NOT HAVE BEEN READ"

    post = {"id": "5001", "text": "", "at": "2026-08-31T04:00:00+00:00",
            "photos": ["https://cdn.example/a.jpg"]}
    monkeypatch.setattr(feed, "_read_photo",
                        lambda url, data=None: "GOLDIAM WINS RS 50 CR ORDER")
    assert feed._store(channel, [post]) == 1

    # second pass, fresh process: the transcript is on disk
    feed._ocr_cache = {}
    monkeypatch.setattr(feed, "_read_photo", _never)
    feed._store(channel, [post], skip_known=False)
    assert reads == [], "the picture was read again from the image"


def test_the_transcript_lookup_is_one_query_not_one_per_message(feed):
    """A per-message lookup would trade OCR for a database round trip
    thirty times a pass."""
    channel = {"name": "OrderBook Pulse", "handle": "orders_pulse"}
    got = feed._stored_ocr("OrderBook Pulse")
    assert isinstance(got, dict)
    assert got == {}, "an empty store should have no transcripts"


def test_a_picture_never_read_before_is_still_read(feed, monkeypatch):
    """Reusing what is on disk must not stop it reading what is not."""
    channel = {"name": "Day Trader Telugu", "handle": "daytradertelugu"}
    reads = []
    monkeypatch.setattr(
        feed, "_read_photo",
        lambda url, data=None: reads.append(url) or "HCC BAGS RS 524 CR")
    post = {"id": "6001", "text": "", "at": "2026-08-31T04:00:00+00:00",
            "photos": ["https://cdn.example/new.jpg"]}
    assert feed._store(channel, [post]) == 1
    assert reads == ["https://cdn.example/new.jpg"]
