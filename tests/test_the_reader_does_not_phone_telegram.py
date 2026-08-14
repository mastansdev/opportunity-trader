"""
==========================================================
A read-only view must not open a Telegram session
==========================================================

    "[TELEGRAM] Folder 'PRO' is empty or unreadable. Check the name
     matches the app exactly..."          -- main.py, 12 August, 22:53

It was neither empty nor unreadable. Asked directly, one second later,
the folder returned all nine channels. What failed was WHO was asking.

main.py builds TelegramFeed(client=None) and says so in its own log:

    "Read-only view of data/telegram.db. This process does NOT collect."

But the constructor ran the folder lookup regardless, and
core/telegram_client.channels_in_folder() opens its own live Telethon
client. So a process that will never poll a channel opened a Telegram
API session at startup -- against the same session FILE the collector
holds open in the other terminal. Two clients, one SQLite session, a
race; the loser printed a warning telling the operator to go and check
a folder name that was perfectly correct.

It also cost a network round-trip on the startup path, which is the
path he was already waiting five minutes on.

THE FIX
-------
A read-only view takes its channel list from the store it reads.
core/feed_clock.py's feed_watermark table holds one row per channel,
written by the collector as it polls -- so it is the honest answer to
"which channels does this bot watch", and it is free.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import sqlite3

import pytest

from core.telegram_feed import TelegramFeed

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    """A telegram.db with a watermark, and nothing else."""
    path = tmp_path / "telegram.db"
    conn = sqlite3.connect(str(path))
    conn.execute("create table messages (id integer primary key, "
                 "channel text, text text, seen_at text)")
    conn.execute("create table feed_watermark (channel text primary key, "
                 "last_at_utc text, last_msg_id integer, "
                 "last_seen_ist text, last_poll_ist text, messages integer)")
    for name in ("Earnings 360", "Business Pulse", "Breakouts"):
        conn.execute("insert into feed_watermark (channel, messages) "
                     "values (?, ?)", (name, 10))
    conn.commit()
    conn.close()
    return str(path)


def test_a_reader_never_builds_a_telethon_client(store, monkeypatch):
    """THE REGRESSION. client=None must not reach channels_in_folder."""
    called = []

    import core.telegram_client as tc
    monkeypatch.setattr(tc, "channels_in_folder",
                        lambda *a, **k: called.append(a) or [])

    TelegramFeed(client=None, db_path=store)
    assert not called, (
        "a read-only TelegramFeed opened a Telegram folder lookup. That "
        "starts a live Telethon client against the same session file "
        "the collector is holding.")


def test_it_takes_its_channels_from_the_store(store):
    feed = TelegramFeed(client=None, db_path=store)
    names = {(c.get("name") or c.get("handle")) for c in feed.channels}
    for expected in ("Earnings 360", "Business Pulse", "Breakouts"):
        assert expected in names, (
            f"{expected} is in feed_watermark and not in the channel "
            f"list -- the store was not read")


def test_the_store_lookup_uses_the_path_it_was_given(store):
    """---- MY OWN BUG, SAME HOUR. ----

    First written as self._channels_from_store(), which __init__ calls
    BEFORE it assigns self.db_path. The AttributeError landed in the
    method's own except and it returned [] every time, silently. The
    channel list still looked plausible -- 4 from CHANNELS, 1 from
    config -- which is exactly why only a count caught it.
    """
    feed = TelegramFeed(client=None, db_path=store)
    assert feed._channels_from_store(store), "explicit path returns nothing"
    assert feed._channels_from_store(), "the attribute default is broken"


def test_a_missing_watermark_table_is_not_an_error(tmp_path):
    """A first run has no watermark. That is not a failure, it is a
    bot that has not read anything yet."""
    path = tmp_path / "empty.db"
    sqlite3.connect(str(path)).close()
    feed = TelegramFeed(client=None, db_path=str(path))
    assert feed._channels_from_store(str(path)) == []
    assert feed.channels, "the base CHANNELS list should still be there"


def test_the_collector_still_reads_the_folder():
    """The other half. A COLLECTOR (client set) must keep asking
    Telegram -- that is how a channel dragged into the folder starts
    being watched without anyone editing a file."""
    src = (ROOT / "core" / "telegram_feed.py").read_text(
        encoding="utf-8", errors="replace")
    assert "channels_in_folder(TELEGRAM_FOLDER)" in src, (
        "the folder lookup is gone entirely -- dragging a channel into "
        "PRO would no longer do anything")
    assert "if self.client is None:" in src, (
        "the reader/collector split that decides who may call it is gone")
