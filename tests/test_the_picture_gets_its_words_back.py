"""
==========================================================
The picture was stored. Its words were not.
==========================================================

    "Telegram OCR Failed"                 -- operator, 10 September 2026

A photo that Telegram PUSHES arrives inside pump()'s running event loop,
so telethon hands back an un-awaited coroutine instead of bytes. Half 1
(core/telegram_client._photo_bytes) stopped that crashing the reader by
returning None. It did not get the words back.

The message is still stored with an EMPTY ocr_text, and nothing revisits
it, for two independent reasons:

    poll()     skip_known=True with a floor of _newest_stored_id(), so a
               stored post is never asked for again.
    _store()   INSERT OR IGNORE on (channel, message_id) -- so even when
               catch_up() re-fetches the post and re-reads the picture,
               the write is DROPPED and the empty column stays empty.

Measured 10 Sep: 125 pictures that day, 125 with no transcript; ~410
across 7-10 Sep. Day Trader Telugu posts market-hours news AS
screenshots, so that is the whole of that channel's content.

reread_missing_photos() is the repair. It runs on the POLLER thread,
where the loop is not running and the download can be driven; it asks
Telegram for those exact post ids; and it writes with UPDATE, which is
the one path that can fill a column INSERT OR IGNORE refuses to touch.

WHY IT MATTERS FOR TRADING, not for a panel: a published reason is
mandatory before the ranker will look at a stock at all. A screenshot
whose words never arrived is a stock silently refused.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.telegram_feed import TelegramFeed


CHANNEL = "Day Trader Telugu"
HANDLE = "daytradertelugu"


class _Client:
    """Records what was asked for, and answers with photo bytes."""

    def __init__(self, serve=True, boom=False):
        self.asked = []
        self.serve = serve
        self.boom = boom

    def fetch(self, channel, limit=30, before=None, since_id=None, ids=None):
        self.asked.append({"channel": channel, "ids": ids,
                           "limit": limit, "since_id": since_id})
        if self.boom:
            raise RuntimeError("Telegram said no")
        out = []
        for message_id in (ids or []):
            out.append({
                "id": message_id,
                "at": "2026-09-10T10:31:00+05:30",
                "text": "",
                "url": f"https://t.me/{HANDLE}/{message_id}",
                "photos": [f"https://t.me/{HANDLE}/{message_id}"],
                "photo_data": [b"PNGBYTES"] if self.serve else [],
            })
        return out


def _db(tmp_path, rows):
    """A store holding `rows` of (message_id, photos, ocr_text)."""
    path = str(tmp_path / "telegram.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE messages (channel TEXT, message_id TEXT, at TEXT, "
        "text TEXT, photos TEXT, url TEXT, ocr_text TEXT, ocr_boxes TEXT, "
        "PRIMARY KEY (channel, message_id))")
    for message_id, photos, ocr_text in rows:
        conn.execute(
            "INSERT INTO messages (channel, message_id, at, text, photos, "
            "url, ocr_text) VALUES (?,?,?,?,?,?,?)",
            (CHANNEL, str(message_id), f"2026-09-10T10:{message_id:02d}:00",
             "", photos, f"https://t.me/{HANDLE}/{message_id}", ocr_text))
    conn.commit()
    conn.close()
    return path


def _feed(tmp_path, rows, client=None, transcript="ADANI wins Rs 755 cr order"):
    import threading
    feed = TelegramFeed.__new__(TelegramFeed)
    feed.client = client if client is not None else _Client()
    feed.read_images = True
    feed.db_path = _db(tmp_path, rows)
    feed._lock = threading.Lock()
    feed.channels = [{"handle": HANDLE, "name": CHANNEL, "kind": "image"}]
    feed._ocr_boxes = {}
    feed.filed = []
    # The OCR engine itself is core/image_text.py's business and has its
    # own tests. What is on trial here is the repair path around it.
    feed._read_photo = lambda url, data=None: transcript
    feed._file_events = lambda filed: feed.filed.extend(filed) or len(filed)
    return feed


def _ocr_of(path, message_id):
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT ocr_text FROM messages WHERE channel = ? AND message_id = ?",
        (CHANNEL, str(message_id))).fetchone()
    conn.close()
    return row[0]


# ---------------------------------------------------------------
# THE REPAIR
# ---------------------------------------------------------------

def test_a_pushed_picture_gets_its_words_back(tmp_path):
    """THE CASE. Stored with a photo and an empty transcript."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")])
    assert feed.reread_missing_photos() == 1
    assert _ocr_of(feed.db_path, 11) == "ADANI wins Rs 755 cr order"


def test_an_empty_column_and_a_null_one_both_count(tmp_path):
    """Half 1 writes `ocr or None`, so a lost transcript is NULL on one
    path and '' on another. Both are the same hole."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", ""),
                            (12, "https://t.me/x/12", None)])
    assert feed.reread_missing_photos() == 2


def test_it_asks_for_those_exact_posts(tmp_path):
    """ONE request, by id. A page walk cannot reliably reach a hole in
    the middle -- that is why fetch(ids=...) exists."""
    client = _Client()
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", ""),
                            (12, "https://t.me/x/12", "")], client=client)
    feed.reread_missing_photos()
    assert len(client.asked) == 1, "one request, not one per post"
    assert sorted(client.asked[0]["ids"]) == [11, 12]
    assert client.asked[0]["since_id"] is None, (
        "a watermark would filter out the very posts being repaired")


def test_the_recovered_words_reach_the_matcher(tmp_path):
    """Words that stop at the database are worth nothing. A published
    reason is what lets the ranker look at the stock."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")])
    feed.reread_missing_photos()
    assert len(feed.filed) == 1
    assert feed.filed[0]["ocr_text"] == "ADANI wins Rs 755 cr order"
    assert feed.filed[0]["channel"] == CHANNEL
    assert feed.filed[0]["from_image"] is True


# ---------------------------------------------------------------
# WHAT IT MUST NOT TOUCH
# ---------------------------------------------------------------

def test_a_picture_that_already_has_words_is_left_alone(tmp_path):
    """Re-reading a good transcript would pay full OCR every cycle --
    the 29 August complaint, "re running multiple same info"."""
    client = _Client()
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "already read")],
                 client=client)
    assert feed.reread_missing_photos() == 0
    assert client.asked == [], "Telegram was asked about a post we can read"
    assert _ocr_of(feed.db_path, 11) == "already read"


def test_a_message_with_no_picture_is_not_a_gap(tmp_path):
    """A text post has no transcript because there is nothing to read."""
    client = _Client()
    feed = _feed(tmp_path, [(11, "", "")], client=client)
    assert feed.reread_missing_photos() == 0
    assert client.asked == []


def test_a_channel_no_longer_configured_is_skipped(tmp_path):
    """The store outlives the channel list. An unknown channel has no
    handle to ask, and must not raise."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")])
    feed.channels = [{"handle": "somethingelse", "name": "Other"}]
    assert feed.reread_missing_photos() == 0


# ---------------------------------------------------------------
# IT MUST NOT BE ABLE TO STOP THE COLLECTION
# ---------------------------------------------------------------

def test_no_bytes_this_time_leaves_the_row_for_the_next_pass(tmp_path):
    """Telegram not serving images is the state half 1 already gives up
    on cleanly. The row keeps its hole and is asked for again."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")],
                 client=_Client(serve=False))
    assert feed.reread_missing_photos() == 0
    assert (_ocr_of(feed.db_path, 11) or "") == ""


def test_an_unreadable_picture_is_not_written_as_empty(tmp_path):
    """OCR returning nothing must not overwrite the column with '' --
    that would look repaired and never be retried."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")], transcript="")
    assert feed.reread_missing_photos() == 0
    assert (_ocr_of(feed.db_path, 11) or "") == ""


def test_a_failed_fetch_never_raises(tmp_path):
    """This runs on the polling thread of a live session."""
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")],
                 client=_Client(boom=True))
    assert feed.reread_missing_photos() == 0


def test_it_does_nothing_without_a_client_or_with_images_off(tmp_path):
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", "")])
    feed.client = None
    assert feed.reread_missing_photos() == 0
    feed.client = _Client()
    feed.read_images = False
    assert feed.reread_missing_photos() == 0


def test_it_is_bounded_per_pass(tmp_path):
    """OCR is the expensive thing in this loop. A backlog of 410 must
    not starve the next poll -- it is taken a slice at a time."""
    rows = [(i, f"https://t.me/x/{i}", "") for i in range(10, 40)]
    feed = _feed(tmp_path, rows)
    assert feed.reread_missing_photos(limit=5) == 5


def test_the_newest_hole_is_repaired_first(tmp_path):
    """Today's news is worth more than Tuesday's. The slice is taken
    newest-first so a backlog never delays the current session."""
    client = _Client()
    feed = _feed(tmp_path, [(11, "https://t.me/x/11", ""),
                            (39, "https://t.me/x/39", "")], client=client)
    feed.reread_missing_photos(limit=1)
    assert client.asked[0]["ids"] == [39]


# ---------------------------------------------------------------
# WHERE IT RUNS
# ---------------------------------------------------------------

def test_it_runs_on_the_poller_thread(tmp_path):
    """It MUST NOT be called from pump(). Inside that running loop the
    download cannot be driven and the coroutine comes back again --
    which is the fault this whole file exists for. The poll loop is the
    place where the loop is not running."""
    import io
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "telegram_feed.py").read_text(encoding="utf-8")
    loop = src[src.index("        def _loop():"):]
    loop = loop[:loop.index("self._thread = threading.Thread")]
    assert "self.reread_missing_photos()" in loop
    assert loop.index("self.poll(") < loop.index("self.reread_missing_photos()"), (
        "a fresh post must be stored before an old one is repaired")
