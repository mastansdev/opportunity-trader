"""
==========================================================
One clock, and a mark for how far the feed has read
==========================================================

    "can u confirm the clock , time is standard IST accross telegram,
     bot. create a mechanism if bot doesn't know & also create the time
     stamps like bot can identify while getting back data in the
     weekends = if bot knows upto which time on what day it recvd msgs
     from telegram then the remaining after that time to current can be
     tracked & get them."
                                -- operator, 10 August 2026

WHAT IS ACTUALLY STORED TODAY -- MEASURED, NOT ASSUMED
------------------------------------------------------
data/telegram.db carries TWO clocks in the SAME table:

    messages.at        2026-08-09T16:14:15+00:00     UTC, tagged
    messages.seen_at   2026-08-09T21:46:09           IST, untagged

Across 400 messages the difference never fell below 5.51 hours, so the
offset is a clean +5:30 and `seen_at` is IST local. Both are correct.
Neither is labelled in a way code can tell apart, which is why
core/catalysts.py and core/supply_events.py each had to learn the same
IST_OFFSET separately, and why a naive comparison of `at` against
datetime.now() is FIVE AND A HALF HOURS WRONG.

    at      = when the CHANNEL published it        (the market's clock)
    seen_at = when OUR COLLECTOR stored it         (our clock)

Both matter and they answer different questions. This module stops
anyone having to guess which is which.

WHAT THE LAG ACTUALLY LOOKS LIKE
--------------------------------
seen_at - at, minus the 5:30 offset, is pure collection lag:

    median      6.8 minutes      healthy
    90th      565   minutes      overnight, collector not running
    worst    3214   minutes      a weekend

The median says the collector is fine when it is up. The tail says
nothing knew how much had been missed while it was down -- which is
exactly what he is asking to fix.

THE WATERMARK
-------------
Until now data/telegram.db held one table, `messages`, and NOTHING
recorded how far each channel had been read. So "have we got
everything?" could only be answered by looking at the newest message
and hoping -- and a channel that has simply been quiet is
indistinguishable from a channel we stopped reading.

This adds a per-channel high-water mark: the newest message time we
have, its id, and when we last successfully looked. From that, the gap
between "last read" and "now" is arithmetic instead of a guess, and a
Monday catch-up can ask for exactly the missing window per channel
rather than a blanket 96 hours.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3
from datetime import datetime, timedelta, timezone

TELEGRAM_DB = "data/telegram.db"

# India has one timezone and no daylight saving. Stated once, here, so
# no other module has to rediscover it a third time.
IST = timezone(timedelta(hours=5, minutes=30), "IST")
IST_OFFSET = timedelta(hours=5, minutes=30)

# Past this with no message AND no successful poll, a channel is not
# quiet, it is not being read. Telegram channels used here post many
# times a day during the week.
STALE_HOURS = 6.0

# ---- NOT EVERY CHANNEL IS SUPPOSED TO POST TODAY. 24 Aug 2026 ----
#
#     "how many times i need to tell you about Earnings Pulse = post
#      data only at results time ... WLPulse bot = This channel will
#      not give us updates daily , its premium bot with capacity of
#      100 stocks to track . Business Pulse = this channel will post
#      whenever they receive updates about any company business
#      updates."
#     "daily focused channels: OrderBook Pulse, Day Trader Telugu ,
#      RedboxGlobal India = these channels will get posted on daily &
#      event occuring times. so delay in getting their data into bot
#      will cost us money."
#                                    -- operator, 24 August 2026
#
# He has said this more than once. I read a 4-day-old watermark on
# Business Pulse and reported it as a broken feed, when a quiet
# Business Pulse means only that no company published a business
# update. Calling that an outage is noise, and noise beside a real
# outage is how a real one gets ignored.
#
# Written down here so it stops depending on my memory.

# Post every session. Silence here is a FAULT, and lateness costs
# money -- these carry the order wins and the news the bot trades on.
DAILY_CHANNELS = (
    "OrderBook Pulse",
    "Day Trader Telugu",
    "RedboxGlobal India",
)

# Results season only. Between seasons they are quiet or promotional,
# and that is correct. See core/results_calendar.in_results_season(),
# which is day-level off the SEBI Regulation 33 deadlines.
RESULTS_CHANNELS = (
    "Earnings Pulse",
    "Earnings 360",
    "Earnings Pro",
)

# Episodic by design. They post when there is something to post.
# WLPulseBot is a premium tracker capped at 100 stocks; Business Pulse
# fires only when a company publishes a business update.
EPISODIC_CHANNELS = (
    "WLPulseBot",
    "Business Pulse",
)


# ---- THE FOLDER GIVES USERNAMES, THE STORE GIVES TITLES ----
#      24 August 2026.
#
# core/telegram_client.channels_in_folder() returns `username or
# title`, so the poller sees "orders_pulse" while data/telegram.db
# stores "OrderBook Pulse". Matching the lists above against the
# poller's names alone would have matched NOTHING for the three
# channels that matter, and the prioritisation would have been a
# change that never ran -- the second time in two days I nearly
# shipped one. Read off the live folder, not guessed.
CHANNEL_ALIASES = {
    "orders_pulse": "OrderBook Pulse",
    "daytradertelugu": "Day Trader Telugu",
    "indiaredboxglobal": "RedboxGlobal India",
    "earnings_pulse": "Earnings Pulse",
    "news_pulse_ai": "News Pulse",
}


def canonical_channel(channel):
    """The display name for any handle or title we might be handed."""
    name = str(channel or "").strip()
    return CHANNEL_ALIASES.get(name.lower(), name)


def channel_kind(channel):
    """"daily", "results", "episodic", or "other"."""
    name = canonical_channel(channel)
    if name in DAILY_CHANNELS:
        return "daily"
    if name in RESULTS_CHANNELS:
        return "results"
    if name in EPISODIC_CHANNELS:
        return "episodic"
    return "other"


def expected_today(channel, day=None):
    """Should this channel have posted by now? None = cannot say.

    Only a "daily" channel going quiet is a fault. A results channel
    is expected in season and not out of it; an episodic one is never
    expected on a schedule.
    """
    kind = channel_kind(channel)
    if kind == "daily":
        return True
    if kind == "episodic":
        return False
    if kind == "results":
        try:
            from core.results_calendar import in_results_season
            return bool(in_results_season(day))
        except Exception:                                      # noqa: BLE001
            return None
    return None


def now_ist():
    """The one clock. Timezone-aware, always IST."""
    return datetime.now(IST)


def to_ist(value):
    """Any stored timestamp -> aware IST, or None.

    Handles all three shapes actually present in the store:
        '2026-08-09T16:14:15+00:00'   tagged UTC   -> +5:30
        '2026-08-09 21:46:09'         naive        -> already IST
        datetime                      as given
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip().replace(" ", "T")
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            try:
                moment = datetime.fromisoformat(text[:19])
            except ValueError:
                return None
    if moment.tzinfo is None:
        # Naive means seen_at, which the collector writes in local IST.
        return moment.replace(tzinfo=IST)
    return moment.astimezone(IST)


def _connect(db_path=TELEGRAM_DB):
    con = sqlite3.connect(db_path)
    con.execute(
        "create table if not exists feed_watermark ("
        " channel text primary key,"
        " last_at_utc text,"        # newest PUBLISHED time we hold
        " last_msg_id integer,"     # so a catch-up can resume by id
        " last_seen_ist text,"      # when we last STORED anything
        " last_poll_ist text,"      # when we last LOOKED, even if empty
        " messages integer)")
    return con


# ---------------------------------------------------------------
def record(channel, at=None, message_id=None, db_path=TELEGRAM_DB):
    """Called by the collector. Never raises -- a broken bookmark must
    not stop the collection it is bookmarking."""
    # ---- A NAME, NEVER A REPR. 10 August 2026. ----
    # core/telegram_feed.py passes a plain name from the poll path and
    # the whole {"handle","name",...} record from the catch-up path.
    # The first version stored whichever it was given, so the table
    # grew rows keyed on "{'handle': 'orders_pulse'..." beside the real
    # ones and every count was split in two. Fixed at the caller on
    # 10 August; refused here as well, because a bookmark that can be
    # corrupted by a caller's mistake is not a bookmark.
    if isinstance(channel, dict):
        channel = channel.get("name") or channel.get("handle") or ""
    channel = str(channel or "").strip()
    if not channel or channel.startswith("{"):
        return False

    try:
        con = _connect(db_path)
        seen = now_ist().isoformat()
        row = con.execute(
            "select last_at_utc, messages from feed_watermark "
            "where channel = ?", (str(channel),)).fetchone()
        count = (row[1] if row and row[1] else 0) + (1 if at else 0)
        newest = str(at) if at else (row[0] if row else None)
        if row and row[0] and at and str(at) < str(row[0]):
            newest = row[0]                      # never move backwards
        con.execute(
            "insert into feed_watermark"
            " (channel, last_at_utc, last_msg_id, last_seen_ist,"
            "  last_poll_ist, messages) values (?,?,?,?,?,?)"
            " on conflict(channel) do update set"
            "  last_at_utc = excluded.last_at_utc,"
            "  last_msg_id = coalesce(excluded.last_msg_id, last_msg_id),"
            "  last_seen_ist = case when ? is not null"
            "      then excluded.last_seen_ist else last_seen_ist end,"
            "  last_poll_ist = excluded.last_poll_ist,"
            "  messages = excluded.messages",
            (str(channel), newest, message_id,
             seen if at else None, seen, count, at))
        con.commit()
        con.close()
        return True
    except Exception:                                          # noqa: BLE001
        return False


def backfill(db_path=TELEGRAM_DB):
    """Seed the watermark from messages already stored.

    So this works the first time it runs instead of pretending every
    channel is unread.
    """
    try:
        con = _connect(db_path)
        rows = con.execute(
            "select channel, max(at), count(*) from messages "
            "where channel is not null group by channel").fetchall()
        for channel, newest, count in rows:
            con.execute(
                "insert into feed_watermark"
                " (channel, last_at_utc, last_seen_ist, messages)"
                " values (?,?,?,?)"
                " on conflict(channel) do update set"
                "  last_at_utc = max(coalesce(last_at_utc,''),"
                "                    excluded.last_at_utc),"
                "  messages = excluded.messages",
                (channel, newest, None, count))
        con.commit()
        con.close()
        return len(rows)
    except Exception:                                          # noqa: BLE001
        return 0


def gaps(now=None, db_path=TELEGRAM_DB, stale_hours=STALE_HOURS):
    """Per channel: how far behind are we, and since when.

    Returns rows sorted worst first:
        {"channel", "last_at_ist", "behind_hours", "stale", "messages"}

    `behind_hours` is measured from the newest PUBLISHED message, in
    IST, against the IST clock -- the comparison that was 5.5 hours
    wrong everywhere it was written by hand.
    """
    moment = now or now_ist()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IST)
    out = []
    try:
        con = _connect(db_path)
        rows = con.execute(
            "select channel, last_at_utc, last_seen_ist, last_poll_ist,"
            " messages from feed_watermark").fetchall()
        con.close()
    except Exception:                                          # noqa: BLE001
        return out
    for channel, last_at, last_seen, last_poll, count in rows:
        when = to_ist(last_at)
        behind = (moment - when).total_seconds() / 3600.0 if when else None
        late = behind is None or behind >= stale_hours
        # A quiet channel is only STALE if it was supposed to post.
        # See DAILY_CHANNELS above -- reporting Business Pulse as a
        # broken feed because nobody published a business update is
        # noise, and noise beside a real outage hides the real one.
        expected = expected_today(channel)
        out.append({
            "channel": channel,
            "kind": channel_kind(channel),
            "expected_today": expected,
            "last_at_ist": when.strftime("%d %b %H:%M") if when else None,
            "behind_hours": round(behind, 2) if behind is not None else None,
            "last_poll_ist": last_poll,
            "messages": count or 0,
            "quiet": late,
            "stale": bool(late and expected is not False),
        })
    out.sort(key=lambda r: -(r["behind_hours"] or 1e9))
    return out


def catch_up_window(channel=None, now=None, db_path=TELEGRAM_DB):
    """The exact window to re-read: (from_ist, to_ist, hours).

    His weekend case. Instead of a blanket 96-hour sweep of nine
    channels -- which on 3 August was on channel 2 of 9 at 3.5 minutes
    a page with the market opening -- ask each channel only for what it
    is actually missing.

    None means the channel has never been read and needs a full pull.
    """
    moment = now or now_ist()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IST)
    rows = gaps(now=moment, db_path=db_path)
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
        if not rows:
            return None
    if not rows:
        return None
    worst = rows[0]
    if worst["behind_hours"] is None:
        return None
    try:
        con = _connect(db_path)
        got = con.execute(
            "select last_at_utc from feed_watermark where channel = ?",
            (worst["channel"],)).fetchone() if channel else con.execute(
            "select min(last_at_utc) from feed_watermark "
            "where last_at_utc is not null").fetchone()
        con.close()
    except Exception:                                          # noqa: BLE001
        return None
    start = to_ist(got[0] if got else None)
    if start is None:
        return None
    return {"from_ist": start, "to_ist": moment,
            "hours": round((moment - start).total_seconds() / 3600.0, 2)}
