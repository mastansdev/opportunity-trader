"""
==========================================================
5h30m behind, and nothing was late
==========================================================

    "Telegram OCR Failed, Bot is showing delayed time"
                                    -- the operator, 10 September 2026

The Telegram tab read five and a half hours behind all session. The
feed was not behind: the real arrival lag is 0.2 minutes at the median,
and the "late" column beside it said so, because _late_by() puts both
stamps through core.feed_clock.to_ist().

The "Last message" column never did. `at` is stored tagged UTC:

    at        2026-09-10T05:11:03+00:00
    seen_at   2026-09-10 10:41:30          (naive, local IST)

and dashboard/static/desk.html prints last_post exactly as it arrives.
So the column showed 05:11 for a post that landed at 10:41. The offset
was being displayed as a delay.

That is the same fault as every other one this week: one fact -- when
did this arrive -- kept on two clocks, and the screen reading the
wrong copy. A column he cannot trust is a column he stops reading, and
this one is how he tells a dead channel from a quiet one.

Author : H&M Opportunity Trader
==========================================================
"""

from core.telegram_feed import TelegramFeed


# The real pair, from his 10 September store.
TAGGED_UTC = "2026-09-10T05:11:03+00:00"
NAIVE_IST = "2026-09-10 10:41:30"


def test_a_tagged_utc_stamp_is_shown_in_ist():
    """THE CASE. 05:11 was never when it arrived."""
    assert TelegramFeed._ist_stamp(TAGGED_UTC) == "2026-09-10 10:41:03"


def test_a_naive_stamp_is_already_ist_and_is_left_alone():
    """seen_at is written by the collector in local time. Converting it
    again would push it forward another 5h30m."""
    assert TelegramFeed._ist_stamp(NAIVE_IST) == "2026-09-10 10:41:30"


def test_the_two_stamps_land_on_the_same_clock():
    """The whole point: posted and stored become comparable, and the
    gap is the 0.2 minutes it really was."""
    posted = TelegramFeed._ist_stamp(TAGGED_UTC)
    stored = TelegramFeed._ist_stamp(NAIVE_IST)
    assert posted[:16] == stored[:16]
    assert TelegramFeed._late_by(TAGGED_UTC, NAIVE_IST) == 0


def test_converting_twice_changes_nothing():
    """to_ist() reads a naive stamp as IST already, so the raw values
    can still go to _late_by() and _channel_state() without being
    shifted a second time."""
    once = TelegramFeed._ist_stamp(TAGGED_UTC)
    assert TelegramFeed._ist_stamp(once) == once


def test_it_never_raises_on_the_panel_path():
    """This runs while the board is being built. An unparseable stamp
    is shown as it is -- better than an empty cell, and never an
    exception."""
    assert TelegramFeed._ist_stamp("not a time") == "not a time"
    assert TelegramFeed._ist_stamp(None) is None
    assert TelegramFeed._ist_stamp("") == ""


def test_the_panel_sends_the_converted_stamp():
    """The display fields must go through it -- that is the bug. The
    raw row values still feed the lateness maths below them."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "telegram_feed.py").read_text(encoding="utf-8")
    assert '"last_post": self._ist_stamp(row.get("last_post")),' in src
    assert '"last_read": self._ist_stamp(row.get("last_read")),' in src
    assert '"last_try": self._ist_stamp(row.get("last_try")),' in src
