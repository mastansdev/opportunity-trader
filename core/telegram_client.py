"""
==========================================================
The actual connection to Telegram
==========================================================

Kept separate from core/telegram_feed.py on purpose. The feed -- what
a message means, which stocks it names, what the dashboard shows -- is
fully testable with no network and no account. This file is the only
part that needs credentials, and it is optional: if telethon is not
installed or the login was never done, the feed simply reports itself
as not connected and every other panel is untouched.

WHY A USER LOGIN AND NOT A BOT
------------------------------
A Telegram BOT can only read a channel it has been made an admin of.
The operator's four channels are other people's:

    Day Trader Telugu, MoneyPurse, EARNINGS PULSE, ORDERBOOK PULSE

He can read them because he has joined them, so the client has to act
as him. That needs api_id / api_hash from my.telegram.org and a
one-time phone login -- `py tools/telegram_setup.py` does that once
and writes a session file.

THE SESSION FILE IS A CREDENTIAL. Anyone holding it can read this
Telegram account. It belongs in .gitignore with the .env, and it must
never be committed.

READ ONLY. This client fetches history and does nothing else -- it
never sends a message, joins, leaves, or reacts.

Author : H&M Opportunity Trader
==========================================================
"""

import asyncio
import os
import re

from core.logger import diagnostic, warn
from core.telegram_web import _pulse_fields

_HASHTAG = re.compile(r"#([A-Z0-9&_-]{2,})")

SESSION_PATH = os.path.join("data", "telegram_session")


def telethon_available():
    try:
        import telethon                                   # noqa: F401
        return True
    except ImportError:
        return False


class TelethonReader:
    """Fetches recent messages. The one method TelegramFeed calls."""

    # ---- A DOWNLOAD WITH NO TIMEOUT IS A HANG. 1 August 2026. ----
    #
    #     "Telegram is having internal issues
    #      TimeoutError: Timeout while fetching data (caused by
    #      GetFileRequest)"
    #
    # client.download_media() runs the event loop until the file
    # arrives, and Telegram's media servers can simply stop answering.
    # There is no timeout in that call, so the catch-up sat on one
    # image until the operator pressed Ctrl+C -- and the run that was
    # meant to bring in today's CDSL cards brought in nothing.
    #
    # The except-clause underneath it could not help: the code never
    # got that far. Waiting forever for a picture is the worst of the
    # options available, because the TEXT of that message was already
    # in hand and it is most of the value.
    PHOTO_TIMEOUT = 25.0

    # After this many timeouts in a row on one channel, stop asking it
    # for pictures. Telegram is either rate-limiting or its media DC is
    # down; either way the next 40 pages would each cost 25 seconds to
    # learn the same thing. Text keeps flowing throughout.
    PHOTO_GIVE_UP_AFTER = 3

    def __init__(self, api_id=None, api_hash=None, session=SESSION_PATH,
                 download_photos=True, photo_timeout=None):
        self.api_id = api_id or os.getenv("TELEGRAM_API_ID")
        self.api_hash = api_hash or os.getenv("TELEGRAM_API_HASH")
        self.session = session
        # Off during a bulk history walk, where thousands of images
        # would be downloaded to be OCR'd once and thrown away.
        self.download_photos = download_photos
        self.photo_timeout = (self.PHOTO_TIMEOUT if photo_timeout is None
                              else float(photo_timeout))
        self._client = None

    def _photo_bytes(self, client, message, seconds):
        """The image, or None if Telegram did not send it in time.

        Telethon's sync wrapper hands back the coroutine untouched when
        a loop is already running, which is what lets asyncio.wait_for
        put a bound on it. Raises TimeoutError on expiry so the caller
        can count it.
        """
        import asyncio

        loop = getattr(client, "loop", None)
        if loop is None or loop.is_running():
            # No loop to drive, or we are already inside one. Fall back
            # to the unbounded call rather than refusing to read at all
            # -- the bound is an improvement, not a precondition.
            return client.download_media(message, file=bytes)

        async def bounded():
            return await asyncio.wait_for(
                client.download_media(message, file=bytes), timeout=seconds)

        return loop.run_until_complete(bounded())

    def _connect(self):
        if self._client is not None:
            return self._client
        from telethon.sync import TelegramClient
        if not self.api_id or not self.api_hash:
            raise RuntimeError(
                "TELEGRAM_API_ID / TELEGRAM_API_HASH missing from .env -- "
                "get them free at my.telegram.org, then run "
                "py tools/telegram_setup.py")
        client = TelegramClient(self.session, int(self.api_id), self.api_hash)
        client.connect()
        if not client.is_user_authorized():
            raise RuntimeError(
                "Telegram session not authorised -- run "
                "py tools/telegram_setup.py once to log in.")
        self._client = client
        return client

    def resolve(self, spec):
        """A channel spec -> something telethon can fetch from.

        Three shapes, because a PRIVATE channel has no @handle:

            "earnings_pulse"    a public handle
            -1001234567890      a numeric id
            "Earnings Pro"      the channel's TITLE as it appears in the
                                app -- resolved against the accounts's
                                own dialog list

        The title form is the one that matters here. The operator's pro
        channels are private, show no share link, and the only name he
        can read off the screen is the title.
        """
        client = self._connect()
        text = str(spec).strip().lstrip("@")
        if text.lstrip("-").isdigit():
            return int(text)
        if "t.me/" in text:
            return text                 # an invite link telethon can use
        try:
            return client.get_entity(text)
        except Exception:                                  # noqa: BLE001
            pass
        # Not a public handle. Look through what this account has
        # actually joined and match on title.
        wanted = text.lower()
        for dialog in client.iter_dialogs():
            name = (getattr(dialog, "name", "") or "").strip().lower()
            if name == wanted:
                return dialog.entity
        for dialog in client.iter_dialogs():
            name = (getattr(dialog, "name", "") or "").strip().lower()
            if wanted and wanted in name:
                return dialog.entity
        raise RuntimeError(
            f"Telegram has no channel matching {spec!r}. For a PRIVATE "
            f"channel use its exact title as shown in the app, and make "
            f"sure this account has joined it.")

    def fetch(self, channel, limit=30, before=None):
        """Recent messages from one channel, newest first.

        ---- REBUILT 1 August 2026 ----
        This returned only `id`, `at` and `text`, and SKIPPED any
        message without text:

            if not text: continue

        Day Trader Telugu is 77% pictures, so that one line would have
        silently emptied the channel the operator most wanted. It also
        dropped the filing links -- the BSE URLs that turned out to be
        the only way to reach half of a day's results.

        It now returns what core/telegram_feed.py actually consumes, so
        it is a drop-in for the web reader rather than a lesser version
        of it:

            photos       a t.me permalink, for display and storage
            photo_data   the image BYTES, because an API photo has no
                         public URL and OCR needs the bytes anyway
            links        every URL in the message, filing links included
            hashtags     the #TICKERs
        """
        client = self._connect()
        entity = self.resolve(channel)
        handle = str(channel).strip().lstrip("@")
        out = []
        # Consecutive image timeouts on THIS channel, and the flag that
        # stops asking once Telegram has made its position clear.
        timeouts, stalled = 0, False
        kwargs = {"limit": limit} if limit else {}
        if before:
            # Telethon counts BACKWARDS from an id, which is what the
            # web reader's ?before= does.
            kwargs["offset_id"] = int(before)
        for message in client.iter_messages(entity, **kwargs):
            text = getattr(message, "message", None) or ""
            photo = getattr(message, "photo", None)
            if not text and photo is None:
                continue

            data = []
            if photo is not None and self.download_photos and not stalled:
                try:
                    blob = self._photo_bytes(client, message,
                                             self.photo_timeout)
                    if blob:
                        data.append(blob)
                    timeouts = 0
                except (TimeoutError, asyncio.TimeoutError):
                    timeouts += 1
                    diagnostic(f"[TELEGRAM] {handle}: image did not arrive "
                               f"in {self.photo_timeout:.0f}s "
                               f"({timeouts}/{self.PHOTO_GIVE_UP_AFTER})")
                    if timeouts >= self.PHOTO_GIVE_UP_AFTER:
                        stalled = True
                        # Said once, loudly, and then the run carries on
                        # with text. A silent degradation would look
                        # exactly like a quiet news day.
                        warn(f"[TELEGRAM] {handle}: Telegram is not serving "
                             f"images right now -- continuing with text "
                             f"only. Re-run catch-up later to pick up the "
                             f"cards.")
                except Exception as exc:                   # noqa: BLE001
                    diagnostic(f"[TELEGRAM] {handle}: photo download "
                               f"failed ({str(exc)[:60]})")

            links = []
            for entity_obj, value in (message.get_entities_text() or []):
                url = getattr(entity_obj, "url", None) or value
                if url and url.startswith("http"):
                    links.append(url)

            # ---- THE BUTTONS UNDER THE MESSAGE, 1 August 2026 ----
            #
            # @WLPulseBot puts its documents on an inline keyboard
            # rather than in the text:
            #
            #     Q4 results filed.  GREAT
            #     Revenue +8.4% YoY ...
            #     [ Brief PDF ]  [ Filing ]
            #
            # Those are reply_markup buttons, not text entities, so the
            # loop above cannot see them -- and the filing link is
            # exactly what turned out to be worth having: on 31 July it
            # was the only route to half a day's results, because the
            # announcement watcher polls NSE and those companies file
            # to BSE.
            #
            # A Mini App button carries no plain URL and is skipped: it
            # is a webview with its own login, and it is where the
            # watchlist is MANAGED rather than where the data arrives.
            markup = getattr(message, "reply_markup", None)
            for row in (getattr(markup, "rows", None) or []):
                for button in (getattr(row, "buttons", None) or []):
                    url = getattr(button, "url", None)
                    if url and url.startswith("http"):
                        links.append(url)

            permalink = f"https://t.me/{handle}/{message.id}"
            record = {
                "id": message.id,
                "at": message.date,
                "text": text,
                "photos": [permalink] if data or photo is not None else [],
                "photo_data": data,
                "links": [u for u in links
                          if "t.me" not in u and "telegram.org" not in u],
                "hashtags": _HASHTAG.findall(text.upper()),
                "url": permalink,
            }
            record.update(_pulse_fields(text, record["links"]))
            out.append(record)
        return out

    def close(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:                              # noqa: BLE001
                pass
            self._client = None


def _is_readable_source(entity):
    """Is this something the bot may read? Channels, groups and BOTS.

        "no personal data at all. its completley used for bot. we can
         see all the channels in PRO Folder. no personal / sensitive
         info"                        -- operator, 1 August 2026

    Bots are allowed because the most valuable thing in his
    subscription arrives as one: @WLPulseBot direct-messages results,
    concall summaries, investor presentations, OrderBook filings,
    broker ratings and price alerts for up to 100 chosen stocks. That
    is a publisher that happens to use a DM, not a conversation.

    A HUMAN chat is still refused, and deliberately so even though he
    has said there is nothing personal in that folder. The guard costs
    nothing, and the day someone drags a friend's chat in by accident
    is the day it earns its place. A rule that holds only while
    everybody remembers is not a rule.
    """
    if getattr(entity, "broadcast", False):
        return True                       # a channel
    if getattr(entity, "megagroup", False):
        return True                       # a group
    if getattr(entity, "bot", False):
        return True                       # a bot that publishes
    return False


def channels_in_folder(name, session=SESSION_PATH):
    """Every channel inside one Telegram FOLDER, by title.

        "in my telegram . two folder - ALL CHATS & PRO
         if we want & feasible i will move our required telegram
         channels to PRO folder"          -- operator, 1 August 2026

    Feasible, and better than a list in config.py. A folder is curated
    in the Telegram app: drag a channel in and the bot reads it, drag
    it out and it stops. No exact-title typing, no file to edit, and no
    way for the list in the code to drift from what he actually
    follows.

    Telegram calls folders "dialog filters". They are an account-level
    setting, so this only works through the API -- there is no folder
    on a public web page.

    ONLY CHANNELS AND GROUPS. If a personal chat is ever dragged into
    that folder it is skipped rather than read: the bot has no business
    in one, and silently hoovering up private messages because someone
    tidied their app would be indefensible.

    Returns [] for anything that goes wrong -- no folder, no session,
    an old telethon. A missing folder must degrade to "no extra
    channels", never to a crash on the way into a trading session.
    """
    wanted = str(name or "").strip().lower()
    if not wanted or not telethon_available():
        return []
    if not os.path.exists(session + ".session"):
        return []
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        return []

    client = None
    try:
        from telethon.sync import TelegramClient
        from telethon.tl.functions.messages import GetDialogFiltersRequest

        client = TelegramClient(session, int(api_id), api_hash)
        client.connect()
        if not client.is_user_authorized():
            return []

        result = client(GetDialogFiltersRequest())
        # Telethon changed this return shape between versions: older
        # gives a bare list, newer wraps it in an object with .filters.
        filters = getattr(result, "filters", result) or []

        out = []
        for folder in filters:
            title = getattr(folder, "title", None)
            # Newer telethon wraps the title in a TextWithEntities.
            title = getattr(title, "text", title)
            if str(title or "").strip().lower() != wanted:
                continue
            for peer in (getattr(folder, "include_peers", None) or []):
                try:
                    entity = client.get_entity(peer)
                except Exception:                          # noqa: BLE001
                    continue
                if not _is_readable_source(entity):
                    continue
                label = getattr(entity, "username", None) or \
                    getattr(entity, "title", None) or \
                    getattr(entity, "first_name", None)
                if label:
                    out.append(str(label))
        return out
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[TELEGRAM] Could not read folder {name!r}: {exc}")
        return []
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:                              # noqa: BLE001
                pass


# Distinguishes "primary not passed, use the default" from an
# explicitly passed primary=None -- see FallbackReader.__init__.
_UNSET = object()


def api_reader():
    """A logged-in API reader, or None with a clear reason.

    Never raises. Telegram being unavailable must never stop a trading
    session starting.
    """
    if not telethon_available():
        diagnostic("[TELEGRAM] telethon is not installed.")
        return None
    if not os.getenv("TELEGRAM_API_ID") or not os.getenv("TELEGRAM_API_HASH"):
        diagnostic("[TELEGRAM] TELEGRAM_API_ID / TELEGRAM_API_HASH not set.")
        return None
    if not os.path.exists(SESSION_PATH + ".session"):
        diagnostic("[TELEGRAM] No session file -- not logged in.")
        return None
    return TelethonReader()


class FallbackReader:
    """Try the API first, drop to the public web view if it fails.

    SINGLE SOURCE FOR CAPABILITY, NOT A SINGLE POINT OF FAILURE.

    The API is the better reader -- private channels, unlimited
    history, structured links, no scraping. But it depends on a session
    file that can expire, a phone number that can be re-verified, and a
    rate limit that can bite. When any of that happens, the four PUBLIC
    channels are still readable by anyone with a browser, and the bot
    should keep reading them rather than go dark on the day it matters.

    So a channel that fails on the API is retried on the web view, and
    only a channel that fails BOTH is reported as lost. A private
    channel has no web view, so for those the fallback correctly
    changes nothing.
    """

    def __init__(self, primary=_UNSET, secondary=None):
        from core.telegram_web import TelegramWebReader
        # ---- EXPLICIT None WAS INDISTINGUISHABLE FROM "OMITTED". ----
        #      12 August 2026.
        #
        # `primary if primary is not None else api_reader()` could not
        # tell "no primary reader, on purpose" (build_reader() passing
        # primary=None because api_reader() itself already returned
        # None -- no session yet) from "argument not given, use the
        # default". Both silently called api_reader() a second time --
        # harmless in practice (idempotent, but it re-runs the env/file
        # checks and can log "No session file" twice) except that it
        # made this class impossible to unit-test in the "no session"
        # state on a machine that DOES have one: passing primary=None
        # from a test just got the real, live reader back instead.
        # See tests/test_telegram_api_reader.py's
        # test_the_web_view_is_used_when_there_is_no_session.
        self.primary = api_reader() if primary is _UNSET else primary
        self.secondary = secondary if secondary is not None \
            else TelegramWebReader()
        self._fell_back = set()

    def fetch(self, channel, limit=30, before=None):
        handle = channel if isinstance(channel, str) else str(channel)
        if self.primary is not None:
            try:
                return self.primary.fetch(handle, limit=limit, before=before)
            except Exception as exc:                       # noqa: BLE001
                # Once per channel per run. A rate limit that fires on
                # every poll would otherwise fill the log with the same
                # line 400 times and hide everything else.
                if handle not in self._fell_back:
                    self._fell_back.add(handle)
                    warn(f"[TELEGRAM] {handle}: the API failed "
                         f"({str(exc)[:70]}). Falling back to the public "
                         f"web view -- a PRIVATE channel has none, so it "
                         f"will simply be empty until the API works.")
        return self.secondary.fetch(handle, limit=limit, before=before)

    def close(self):
        for reader in (self.primary, self.secondary):
            if hasattr(reader, "close"):
                try:
                    reader.close()
                except Exception:                          # noqa: BLE001
                    pass


def build_reader():
    """What main.py should use: the API when it is set up, the public
    web view otherwise, and the web view as a safety net either way."""
    primary = api_reader()
    if primary is None:
        warn("[TELEGRAM] Reading the PUBLIC web view only. Private "
             "channels need: TELEGRAM_API_ID / TELEGRAM_API_HASH in .env, "
             "pip install telethon, then py tools/telegram_setup.py")
    return FallbackReader(primary=primary)
