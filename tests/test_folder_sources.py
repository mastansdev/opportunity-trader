"""
==========================================================
What the bot may read out of a Telegram folder
==========================================================

    "no personal data at all. its completley used for bot. we can see
     all the channels in PRO Folder. no personal / sensitive info"
                                    -- operator, 1 August 2026

He is right about his own folder, and the guard stays anyway.

WHY BOTS ARE ALLOWED
--------------------
The richest thing in his subscription arrives as a direct message.
@WLPulseBot pushes results, concall summaries, investor presentations,
OrderBook filings, broker ratings and price alerts for up to 100
chosen stocks -- "Only your stocks. No firehose."

That is a publisher that happens to use a DM. Refusing it on the
grounds that a DM is private would cost the single best source in the
account for no benefit to anyone.

WHY HUMAN CHATS ARE STILL REFUSED
---------------------------------
Because a rule that holds only while everybody remembers is not a
rule. The folder is curated by dragging things into it, which means
the day someone drags a friend's chat in by accident is a day this
guard is the only thing standing between a tidy-up and a bot reading
private conversations.

It costs nothing on every other day.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.telegram_client import _is_readable_source


class Entity:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------
# 1. PUBLISHERS ARE READ
# ---------------------------------------------------------------
@pytest.mark.parametrize("label,entity", [
    ("a public channel", Entity(broadcast=True, username="earnings_pulse")),
    ("a private channel", Entity(broadcast=True, title="Earnings Pro")),
    ("a supergroup", Entity(megagroup=True, title="Some Group")),
    ("@WLPulseBot", Entity(bot=True, username="WLPulseBot")),
])
def test_publishers_are_read(label, entity):
    assert _is_readable_source(entity) is True, label


def test_the_watchlist_bot_specifically():
    """The one that made this change necessary. Up to 100 symbols, with
    results, concalls, presentations, filings, broker ratings and price
    moves -- all by DM."""
    assert _is_readable_source(Entity(bot=True, username="WLPulseBot"))


# ---------------------------------------------------------------
# 2. PEOPLE ARE NOT
# ---------------------------------------------------------------
@pytest.mark.parametrize("label,entity", [
    ("a person", Entity(bot=False, first_name="Someone")),
    ("a user with no flags", Entity(first_name="Someone")),
    ("an empty entity", Entity()),
])
def test_human_chats_are_refused(label, entity):
    assert _is_readable_source(entity) is False, label


def test_a_person_dragged_into_the_folder_is_still_skipped():
    """The whole reason the guard survives the operator saying his
    folder is clean. Folders are curated by dragging; one day
    something will be dragged in by mistake."""
    folder = [
        Entity(broadcast=True, title="Earnings Pro"),
        Entity(bot=True, username="WLPulseBot"),
        Entity(bot=False, first_name="A Friend"),
    ]
    readable = [e for e in folder if _is_readable_source(e)]
    assert len(readable) == 2
    assert not any(getattr(e, "first_name", None) == "A Friend"
                   for e in readable)


# ---------------------------------------------------------------
# 3. THE GUARD IS WHERE THE FOLDER IS READ
# ---------------------------------------------------------------
def test_the_folder_reader_uses_the_guard():
    """Not a comment, not a convention -- the one function that turns a
    folder into a list of sources must call it."""
    src = open("core/telegram_client.py", encoding="utf-8").read()
    body = src[src.index("def channels_in_folder"):]
    body = body[:body.index("\ndef ", 10)]
    assert "_is_readable_source(entity)" in body


def test_a_missing_folder_yields_nothing_rather_than_everything():
    """Failing open here would mean reading the whole account."""
    from core.telegram_client import channels_in_folder
    assert channels_in_folder("") == []
    assert channels_in_folder("NoSuchFolderAnywhere") == []
