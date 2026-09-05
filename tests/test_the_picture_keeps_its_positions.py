"""
==========================================================
Where each word was, kept
==========================================================

    "for me all info must be tagged properly & never mis ,
     duplicate , thats it"
                                -- the operator, 5 September 2026

TWO THINGS IN ONE FILE, because they are one idea: the picture-reader
should be asked twice when it saw nothing, and what it DID see should
not be thrown away.

---- THE POSITIONS ----

Tesseract walks a picture COLUMN BY COLUMN, so the flat transcript of a
grid comes out in an order that has nothing to do with what belongs to
what. Earnings Pulse's week-ahead card is exactly that shape:

    EARNINGS PULSE - THE WEEK AHEAD
    SAT ... MOLBIO       13,355 Cr   MID CAP
    MON ... SHIPROCKET    9,894 Cr   MID CAP
            BLEL          1,925 Cr   SMALL CAP

Every company right. Every figure right -- 13,355 / 9,894 / 1,925,
commas and all. And WHICH DAY each one reports is lost, because the day
headers and the company cards are separate columns.

On 2 August that put NINE companies reporting during market hours into
the after-the-close bucket. core/recap_card.rows_from_grid() fixes it
from the word coordinates, and image_text.words_with_positions()
produces them for free -- image_to_data runs the same recognition pass
image_to_string already did.

They were then held in memory for ninety seconds and thrown away. So
nothing could re-group a card afterwards, nothing could check a bad
read, and every REBUILD of the event store re-made the bug: the rebuild
passed no positions at all, and quietly produced a worse answer than
the session that first read the picture.

This matters to trades, not to panels. The bot records
days_since_results on every trade and the results grade gates entry, so
a company put on the wrong day is a stock watched on the wrong day.

---- THE SECOND LOOK ----

Claude vision used to run only when Tesseract was ABSENT. That is
backwards. An installed reader that returns nothing is exactly the case
where a second opinion is worth paying for, and it was the one case
that never got one.

Measured on data/telegram.db, 30 July to 5 September: of 1,321
pictures, 138 came back blank. Most had a caption carrying the news --
but SIX had nothing at all, no caption and no transcript.

The free reader still goes first on every image. The paid one is asked
only when the free one produced nothing usable, which on the measured
history is about one image in ten and on most days none. Paying to
re-read what is already right would be spending for no gain: 2,489
crore figures have been read out of these pictures and not one of them
is impossible.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

import pytest

from core import image_text
from core.telegram_feed import TelegramFeed, boxes_from_json, _boxes_json


# ------------------------------------------------------------------
# the positions survive
# ------------------------------------------------------------------

BOXES = [
    {"text": "MON", "left": 10, "top": 100, "width": 40, "height": 12},
    {"text": "SHIPROCKET", "left": 10, "top": 130, "width": 90, "height": 12},
    {"text": "9,894", "left": 10, "top": 150, "width": 40, "height": 12},
]


def test_the_positions_round_trip():
    back = boxes_from_json(_boxes_json(BOXES))
    assert [b["text"] for b in back] == ["MON", "SHIPROCKET", "9,894"]
    assert back[1]["top"] == 130 and back[1]["left"] == 10


def test_nothing_is_stored_when_there_is_nothing_to_store():
    assert _boxes_json(None) is None
    assert _boxes_json([]) is None
    assert boxes_from_json(None) == []


def test_a_picture_that_cannot_be_serialised_still_stores_its_text():
    """Never let the positions be the thing that loses a message."""
    class Awkward:
        def get(self, _k, _d=None):
            raise ValueError("no")

    assert _boxes_json([Awkward()]) is None


def test_the_positions_reach_the_database(monkeypatch):
    # _store() reads the picture itself, so the reader is what has to
    # be stubbed -- seeding the cache would be overwritten by the real
    # read, which is the correct behaviour and worth not breaking.
    monkeypatch.setattr(image_text, "available", lambda: True)
    monkeypatch.setattr(image_text, "fetch", lambda _u: b"an image")
    monkeypatch.setattr(image_text, "read",
                        lambda _d: "MON SHIPROCKET 9,894 Cr MID CAP")
    monkeypatch.setattr(image_text, "words_with_positions", lambda _d: BOXES)

    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    feed = TelegramFeed(db_path=path,
                        channels=[{"name": "Earnings Pulse",
                                   "handle": "earnings_pulse"}])
    url = "https://t.me/earnings_pulse/1"
    feed._store({"name": "Earnings Pulse", "handle": "earnings_pulse"},
                [{"id": 1, "at": datetime.now(timezone.utc),
                  "text": "THE WEEK AHEAD", "photos": [url],
                  "photo_data": [], "links": [], "hashtags": [],
                  "url": url}])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM messages").fetchone()
    conn.close()
    assert row is not None
    assert "ocr_boxes" in row.keys()
    assert [b["text"] for b in boxes_from_json(row["ocr_boxes"])] == \
        ["MON", "SHIPROCKET", "9,894"]


def test_the_rebuild_reads_them_back():
    """The live session had the positions and the rebuild did not, so a
    rebuild produced a worse answer than the run that first read the
    picture."""
    src = io.open("tools/build_stock_events.py", encoding="utf-8").read()
    assert "word_boxes=boxes" in src
    assert "boxes_from_json" in src


# ------------------------------------------------------------------
# the second look
# ------------------------------------------------------------------

def test_the_paid_reader_is_asked_only_when_the_free_one_saw_nothing(
        monkeypatch):
    calls = {"tesseract": 0, "claude": 0}

    def fake_tess(_data):
        calls["tesseract"] += 1
        return ""

    def fake_claude(_data, budget=None):
        calls["claude"] += 1
        return ("BREAKING: Bharat Electronics wins order worth Rs 2,210 "
                "crore from Ministry of Defence")

    monkeypatch.setattr(image_text, "backend", lambda: "tesseract")
    monkeypatch.setattr(image_text, "_read_tesseract", fake_tess)
    monkeypatch.setattr(image_text, "_read_claude", fake_claude)
    monkeypatch.setattr(image_text, "claude_available", lambda: True)

    out = image_text.read(b"an image")
    assert "Bharat Electronics" in out
    assert calls == {"tesseract": 1, "claude": 1}


def test_the_paid_reader_is_not_asked_when_the_free_one_worked(monkeypatch):
    """It costs money per picture and adds a round trip during market
    hours. Paying to re-read what is already right is spending for no
    gain."""
    calls = {"claude": 0}

    monkeypatch.setattr(image_text, "backend", lambda: "tesseract")
    monkeypatch.setattr(
        image_text, "_read_tesseract",
        lambda _d: "HAL wins order worth Rs 2,205 crore from MoD")
    monkeypatch.setattr(image_text, "_read_claude",
                        lambda *_a, **_k: calls.__setitem__(
                            "claude", calls["claude"] + 1) or "")
    monkeypatch.setattr(image_text, "claude_available", lambda: True)

    assert "2,205" in image_text.read(b"an image")
    assert calls["claude"] == 0


def test_no_key_means_no_second_look(monkeypatch):
    calls = {"claude": 0}
    monkeypatch.setattr(image_text, "backend", lambda: "tesseract")
    monkeypatch.setattr(image_text, "_read_tesseract", lambda _d: "")
    monkeypatch.setattr(image_text, "_read_claude",
                        lambda *_a, **_k: calls.__setitem__(
                            "claude", calls["claude"] + 1) or "x")
    monkeypatch.setattr(image_text, "claude_available", lambda: False)
    assert image_text.read(b"an image") == ""
    assert calls["claude"] == 0


def test_a_failing_second_look_is_still_safe(monkeypatch):
    """Nothing about a chat feed may stop a trading session."""
    monkeypatch.setattr(image_text, "backend", lambda: "tesseract")
    monkeypatch.setattr(image_text, "_read_tesseract", lambda _d: "")
    monkeypatch.setattr(image_text, "claude_available", lambda: True)

    def boom(*_a, **_k):
        raise RuntimeError("the API is down")

    monkeypatch.setattr(image_text, "_read_claude", boom)
    assert image_text.read(b"an image") == ""


def test_the_key_is_what_decides(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert image_text.claude_available() is False
