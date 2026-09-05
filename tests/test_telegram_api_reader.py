"""
==========================================================
One source for every channel, public and private
==========================================================

    "i have pro channels in my telegram, API _ID & HASH . whats the
     issue if we club all these telegram as one complete source?"

No issue. It is the better design, and the objection raised against it
was wrong -- it described the STUB in core/telegram_client.py, not the
approach.

WHAT THE STUB DID
-----------------
    def fetch(self, channel, limit=30):
        for message in client.iter_messages(channel, limit=limit):
            text = getattr(message, "message", None)
            if not text:
                continue            # <-- every photo, gone

Day Trader Telugu is 77% pictures. That one line would have silently
emptied the channel the operator most wanted. It also dropped the
filing links -- the BSE URLs that turned out to be the only way to
reach half of a day's results.

WHY THE API IS THE BETTER SOURCE
--------------------------------
  private channels    impossible on the web view, routine here
  history             unlimited, instead of 20 per page walked back
  links               structured, instead of scraped out of HTML
  stability           a documented interface, instead of a courtesy
                      web page Telegram may redesign any morning --
                      and 358 missing messages already showed how
                      quietly that fails

WHY THE WEB READER STAYS
------------------------
Single source for CAPABILITY, not a single point of failure. The
session can expire, the number can be re-verified, the rate limit can
bite. When that happens the four PUBLIC channels are still readable by
anyone with a browser, and the bot should keep reading them rather
than go dark on the day it matters.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.telegram_client import FallbackReader


class Web:
    """The public reader. Cannot see private channels, never fails."""

    def __init__(self):
        self.asked = []

    def fetch(self, channel, limit=30, before=None):
        self.asked.append(channel)
        return [{"id": 1, "text": f"web copy of {channel}", "photos": []}]


class Api:
    def __init__(self, fail=False):
        self.fail = fail
        self.asked = []

    def fetch(self, channel, limit=30, before=None):
        self.asked.append(channel)
        if self.fail:
            raise RuntimeError("FloodWaitError: wait 300 seconds")
        return [{"id": 9, "text": f"api copy of {channel}", "photos": []}]


# ---------------------------------------------------------------
# 1. THE API LEADS
# ---------------------------------------------------------------
def test_the_api_is_used_when_it_works():
    api, web = Api(), Web()
    got = FallbackReader(primary=api, secondary=web).fetch("earnings_pulse")
    assert got[0]["text"].startswith("api copy")
    assert web.asked == [], "the web view must not be touched needlessly"


def test_the_web_view_is_used_when_there_is_no_session():
    """How it runs before the operator logs in, and how it ran for
    every session until 1 August."""
    web = Web()
    got = FallbackReader(primary=None, secondary=web).fetch("earnings_pulse")
    assert got[0]["text"].startswith("web copy")


# ---------------------------------------------------------------
# 2. A FAILING API MUST NOT TAKE THE PUBLIC CHANNELS DOWN
# ---------------------------------------------------------------
def test_a_failing_api_falls_back_instead_of_going_dark():
    """A rate limit or an expired session must cost the PRIVATE
    channels only. The public four are readable by anyone with a
    browser and must keep arriving."""
    api, web = Api(fail=True), Web()
    got = FallbackReader(primary=api, secondary=web).fetch("earnings_pulse")
    assert got[0]["text"].startswith("web copy")
    assert web.asked == ["earnings_pulse"]


def test_the_fallback_warns_once_per_channel_not_once_per_poll():
    """The poller runs every 90 seconds. A rate limit that fires on
    every cycle would print the same line 400 times a day and bury
    everything else in the log."""
    api, web = Api(fail=True), Web()
    reader = FallbackReader(primary=api, secondary=web)
    for _ in range(5):
        reader.fetch("earnings_pulse")
    assert reader._fell_back == {"earnings_pulse"}


def test_each_channel_falls_back_independently():
    api, web = Api(fail=True), Web()
    reader = FallbackReader(primary=api, secondary=web)
    reader.fetch("earnings_pulse")
    reader.fetch("daytradertelugu")
    assert reader._fell_back == {"earnings_pulse", "daytradertelugu"}


# ---------------------------------------------------------------
# 3. THE ARGUMENTS REACH BOTH READERS
# ---------------------------------------------------------------
def test_history_arguments_are_passed_through():
    """catch_up() walks backwards with `before`. If that were dropped
    the walk would fetch page one forever and never fill a gap."""
    seen = {}

    class Recorder:
        def fetch(self, channel, limit=30, before=None):
            seen["limit"], seen["before"] = limit, before
            return []

    FallbackReader(primary=Recorder(), secondary=Web()).fetch(
        "earnings_pulse", limit=None, before=12587)
    assert seen == {"limit": None, "before": 12587}


# ---------------------------------------------------------------
# 4. THE STUB'S BUG MUST NOT COME BACK
# ---------------------------------------------------------------
def test_the_api_reader_does_not_drop_photo_only_messages():
    """The line that would have emptied Day Trader Telugu:

        if not text: continue

    77% of that channel is pictures with no caption at all.
    """
    # ---- IT MOVED TO _shape(). 5 September 2026. ----
    # This scanned the body of fetch(). When Telegram was allowed to
    # PUSH messages as well as answer for them, the record-building was
    # lifted into _shape() so both doors build the identical record --
    # which is the whole reason that method exists. The invariant below
    # is unchanged; only its address is.
    src = open("core/telegram_client.py", encoding="utf-8").read()
    body = src[src.index("    def _shape(self, client, message, handle):"):]
    body = body[:body.index("\n    def ")] if "\n    def " in body else body
    assert "if not text and photo is None:" in body, (
        "a message with a photo and no caption must be kept")
    for field in ("photo_data", "hashtags", "links"):
        assert field in body, (
            f"the API reader must return {field} -- without it it is a "
            f"lesser reader than the web view it replaces")


def test_documents_on_an_inline_keyboard_are_captured():
    """@WLPulseBot puts its documents on BUTTONS, not in the text:

        Q4 results filed.  GREAT
        Revenue +8.4% YoY ...
        [ Brief PDF ]  [ Filing ]

    Those are reply_markup buttons, invisible to a text-entity scan.
    The filing link is exactly what proved worth having on 31 July --
    it was the only route to half a day's results, because the
    announcement watcher polls NSE and those companies file to BSE.

    A Mini App button carries no plain URL and must be skipped: it is
    a webview with its own login, and it is where the watchlist is
    MANAGED rather than where the data arrives.
    """
    # ---- IT MOVED TO _shape(). 5 September 2026. ----
    # This scanned the body of fetch(). When Telegram was allowed to
    # PUSH messages as well as answer for them, the record-building was
    # lifted into _shape() so both doors build the identical record --
    # which is the whole reason that method exists. The invariant below
    # is unchanged; only its address is.
    src = open("core/telegram_client.py", encoding="utf-8").read()
    body = src[src.index("    def _shape(self, client, message, handle):"):]
    body = body[:body.index("\n    def ")] if "\n    def " in body else body
    assert "reply_markup" in body, (
        "the bot's documents live on an inline keyboard; a text-only "
        "scan misses every one of them")
    assert 'getattr(button, "url", None)' in body
    assert 'url.startswith("http")' in body, (
        "a Mini App button has no URL and must not be stored as one")


def test_a_private_channel_can_be_named_by_its_title():
    """A private channel has no @handle and shows no share link. The
    only name the operator can read off his screen is the title."""
    src = open("core/telegram_client.py", encoding="utf-8").read()
    assert "def resolve(self, spec)" in src
    assert "iter_dialogs" in src, (
        "resolving a title means looking through what this account has "
        "actually joined")
