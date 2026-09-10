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
        # Consecutive image timeouts, and the flag that stops asking
        # once Telegram has made its position clear. On the READER, not
        # in fetch()'s locals: "images are not being served right now"
        # is true of the connection, and a pushed message meets the
        # same wall a fetched one does. See _shape().
        self._photo_timeouts = 0
        self._photos_stalled = False
        # Set by watch(); read by pump(). Nothing else touches them.
        self._watching = False
        self._on_push = None

    def _photo_bytes(self, client, message, seconds):
        """The image, or None if Telegram did not send it in time.

        Telethon's sync wrapper hands back the coroutine untouched when
        a loop is already running, which is what lets asyncio.wait_for
        put a bound on it. Raises TimeoutError on expiry so the caller
        can count it.
        """
        import asyncio

        loop = getattr(client, "loop", None)

        # ---- A COROUTINE MUST NOT ESCAPE THIS FUNCTION. 10 Sep 2026 ----
        #
        #     "Telegram OCR Failed"                     -- the operator
        #
        # When Telegram PUSHES a photo it is dispatched INSIDE pump()'s
        # running loop (run_until_complete(sleep(90))), so telethon's
        # sync wrapper hands back an un-awaited COROUTINE rather than
        # bytes. Every caller from here is synchronous -- _shape() ->
        # _store() -> core.image_text.read() -- and read() dies on it
        # with "a bytes-like object is required, not 'coroutine'". On
        # 10 September that was 100% of pushed pictures, and push now
        # delivers nearly everything.
        #
        # We cannot drive the download here: the loop is already running
        # and nothing in this call chain can await. So give up CLEANLY --
        # close the coroutine so it does not leak an "was never awaited"
        # warning, and return None. None is "no image THIS time", which
        # _shape() already handles (it appends nothing and moves on). The
        # transcript is recovered afterwards by the re-read pass on the
        # poller thread, outside the loop, where the download CAN be
        # driven -- see core/telegram_feed.reread_missing_photos().
        if loop is not None and loop.is_running():
            coro = client.download_media(message, file=bytes)
            close = getattr(coro, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:                             # noqa: BLE001
                    pass
            return None

        if loop is None:
            # No loop object at all: telethon's sync wrapper drives its
            # own and returns bytes. Telethon 1.44 always sets
            # client.loop, so this is the defensive arm, not the hot one.
            return client.download_media(message, file=bytes)

        async def bounded():
            return await asyncio.wait_for(
                client.download_media(message, file=bytes), timeout=seconds)

        return loop.run_until_complete(bounded())

    def _connect(self):
        # ==========================================================
        # IT NEVER RECONNECTED.  31 August 2026.
        # ==========================================================
        #
        # 10:47:04, from his collector terminal:
        #
        #     [TELEGRAM] daytradertelugu: the API failed (Cannot send
        #     requests while disconnected)
        #     [TELEGRAM] orders_pulse: <urlopen error [Errno 11001]
        #     getaddrinfo failed>
        #
        # The machine lost DNS for a moment. Telethon dropped the
        # connection -- and this returned the DEAD client on every call
        # afterwards, because it only ever checked that the object
        # existed. Five hours of a trading session were served by a
        # socket that had been closed since mid-morning, and the only
        # cure was restarting the process.
        #
        # The channels with a public handle limped along on the web
        # fallback. The four private ones had nothing to fall back to
        # and simply went dark.
        #
        # A live object is reused, a dropped one is revived in place,
        # and only a client that cannot be revived is rebuilt from the
        # session file. Rebuilding first would be wrong: a fresh
        # TelegramClient on the same session is what triggers Telegram's
        # rate limits.
        if self._client is not None:
            try:
                if self._client.is_connected():
                    return self._client
                diagnostic("[TELEGRAM] The connection had dropped. "
                           "Reconnecting on the existing session.")
                self._client.connect()
                if self._client.is_connected():
                    return self._client
            except Exception as exc:                       # noqa: BLE001
                warn(f"[TELEGRAM] Could not revive the connection "
                     f"({str(exc)[:70]}). Building a new one.")
            try:
                self._client.disconnect()
            except Exception:                              # noqa: BLE001
                pass
            self._client = None
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

    def fetch(self, channel, limit=30, before=None, since_id=None,
              ids=None):
        """Recent messages from one channel, newest first.

        `ids` asks for NAMED POSTS and nothing else. See the
        note beside the kwargs below -- it is what fills a hole
        in the middle of a range, which no page walk can do
        reliably.

        `since_id` is the newest post id already on file. Telegram
        filters on it SERVER-SIDE, so a post we have read is never
        sent, never downloaded, never OCR'd. See the note by min_id
        below -- that one argument is the whole of it.

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
        # ==========================================================
        # ASK FOR THE POSTS THAT ARE MISSING, BY NAME.  5 Sep 2026.
        # ==========================================================
        #
        #     "for me all info must be tagged properly & never mis ,
        #      duplicate , thats it"                  -- the operator
        #
        # Measured on the store the day he said it, 183 posts had been
        # published and never collected. They were not scattered: they
        # sat in runs, and every run was a weekend.
        #
        #     RedboxGlobal India   76 missing, 29 Aug 11:04 -> 31 Aug 18:07
        #     Earnings 360         10 missing, 26 Aug 07:56 -> 27 Aug 07:10
        #     Earnings Pro          9 missing, 26 Aug 07:35 -> 27 Aug 07:10
        #     Business Pulse        9 missing, 27 Jul 12:30 -> 29 Jul 09:32
        #
        # catch_up() walks BACKWARDS a page at a time and stops after two
        # pages that add nothing. That closes a gap at the END of what we
        # hold. It cannot reliably close one in the MIDDLE, because the
        # page either side of the hole is ground we already have -- so
        # the walk declares itself finished while the hole is still open.
        # That is not a tuning problem. A page walk is the wrong shape of
        # question.
        #
        # The right question is the one the store can already answer
        # exactly: ids 3712 to 3787 are missing, fetch those. Telegram
        # answers it in ONE request for up to a hundred posts, sends
        # nothing we already hold, and walks past nothing.
        #
        # `ids` therefore overrides everything else. A request for named
        # posts is not a page and has no limit, no offset and no
        # watermark -- mixing them would silently return something other
        # than what was asked for.
        if ids:
            kwargs = {"ids": [int(i) for i in ids]}
        else:
            kwargs = {"limit": limit} if limit else {}
        if before and not ids:
            # Telethon counts BACKWARDS from an id, which is what the
            # web reader's ?before= does.
            kwargs["offset_id"] = int(before)
        if since_id and not ids:
            # ---- IT ASKED FOR WHAT IT ALREADY HAD. 30 Aug 2026. ----
            #
            #     "incase daytrader posted img at 30/08/2026 07:20:05 &
            #      bot read it then laptop off . next day laptop on &
            #      collector must check from that channel after
            #      30/08/2026 07:20:06 not before that time"
            #                                        -- the operator
            #
            # Without this the loop below received the whole page and
            # threw most of it away AFTER the expensive part: the photo
            # bytes are downloaded for every message it walks, and Day
            # Trader Telugu is 77% pictures. A restart paid for a
            # hundred image downloads to store nothing.
            #
            # min_id is a Telegram server-side filter -- only ids
            # ABOVE it are sent. The already-read post does not arrive
            # at all, so there is nothing to download and nothing to
            # skip. This is why the watermark was worth keeping.
            #
            # NOT used by catch_up(), which walks backwards on purpose
            # to fill a hole BELOW the newest id. See core/telegram_
            # feed.py's _store() for the run that proved that.
            kwargs["min_id"] = int(since_id)
            # ---- AND IT MUST WALK FORWARD. 1 September 2026. ----
            #
            #     "bot needs to check all channels last time stamp .
            #      after restart bot needs to fetch after that time
            #      stamp ... if bot received last data at 22:05 then
            #      this morning will start fetching from last night
            #      after 22:05:01"                    -- the operator
            #
            # min_id alone was only half of it. Telethon iterates
            # NEWEST FIRST, so a channel that posted 200 posts overnight
            # returned the newest 30 above the watermark -- and _store()
            # then advanced the watermark to the newest of those. The
            # 170 in between were skipped, permanently, and catch_up()
            # existed to walk backwards and patch the hole.
            #
            # reverse=True makes Telethon iterate ASCENDING from min_id,
            # so each pass takes the OLDEST 30 he has not seen and the
            # watermark advances by 30. Repeated passes close the gap in
            # order and no post is ever stepped over.
            #
            # Only with since_id, and never with `before`: `before` is
            # the backward walk and the two directions cannot both be
            # true in one call.
            if not before:
                kwargs["reverse"] = True
        for message in client.iter_messages(entity, **kwargs):
            # A named id that has been DELETED comes back as None. That
            # is a real answer -- the post is gone, not missing -- and
            # skipping it here is what stops the gap filler asking for
            # it again on every run.
            if message is None:
                continue
            record = self._shape(client, message, handle)
            if record is not None:
                out.append(record)
        return out

    def _shape(self, client, message, handle):
        """One telethon message -> the record the feed stores.

        ---- ONE SHAPE, TWO DOORS. 5 September 2026. ----

        This was the body of fetch()'s loop. It is a method because a
        message now reaches the bot two ways -- PULLED by fetch(), or
        PUSHED by watch() -- and a record built twice is a record that
        drifts. The photo bytes, the filing links, the inline-keyboard
        buttons and the hashtags are the whole reason a message is
        worth anything downstream, and none of it may depend on which
        door the message came through.

        Returns None for a message with neither text nor a picture: a
        poll, a sticker, a service post.

        The image-timeout counters live on the READER rather than in
        fetch()'s locals, because "Telegram is not serving images right
        now" is true of the connection, not of one call. A pushed
        message and a fetched one hit the same wall and should give up
        together.
        """
        text = getattr(message, "message", None) or ""
        photo = getattr(message, "photo", None)
        if not text and photo is None:
            return None

        data = []
        if photo is not None and self.download_photos \
                and not self._photos_stalled:
            try:
                blob = self._photo_bytes(client, message,
                                         self.photo_timeout)
                if blob:
                    data.append(blob)
                self._photo_timeouts = 0
            except (TimeoutError, asyncio.TimeoutError):
                self._photo_timeouts += 1
                diagnostic(f"[TELEGRAM] {handle}: image did not arrive "
                           f"in {self.photo_timeout:.0f}s "
                           f"({self._photo_timeouts}/"
                           f"{self.PHOTO_GIVE_UP_AFTER})")
                if self._photo_timeouts >= self.PHOTO_GIVE_UP_AFTER:
                    self._photos_stalled = True
                    # Said once, loudly, and then the run carries on
                    # with text. A silent degradation would look
                    # exactly like a quiet news day.
                    warn(f"[TELEGRAM] {handle}: Telegram is not serving "
                         f"images right now -- continuing with text "
                         f"only. Re-run catch-up later to pick up the "
                         f"cards.")
            except Exception as exc:                       # noqa: BLE001
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
        return record

    # ==============================================================
    # TELEGRAM TELLS THE BOT.  5 September 2026.
    # ==============================================================
    #
    #     "right now the bot is asking telegram channels for new post
    #      or reverse ? if telegram tells bot to check then it will be
    #      easy to bot i think. this will solves the issue of reading
    #      all empty to only channels posting information"
    #                                            -- the operator
    #
    # It was asking. POLL_SECONDS is 90 and every channel was asked on
    # every pass whether or not anything had been published -- about
    # 400 requests an hour, most of them answering "nothing".
    #
    # He is right that Telegram will tell us instead. It is the same
    # connection, already open and already authorised; NewMessage rides
    # on it and arrives the moment a post is published.
    #
    # WHAT PUSH DOES NOT DO, and why the polling stays: Telegram sends
    # updates to a client that is CONNECTED. Nothing is queued for a
    # laptop that is off. So push replaces the asking, never the
    # catching up -- poll(), catch_up() and fill_gaps() are what make a
    # restart whole, and they are untouched.
    #
    # WHY pump() RATHER THAN run_until_disconnected(): telethon's sync
    # wrapper owns one event loop, and run_until_disconnected() holds
    # it forever. This feed already drives that client from TWO threads
    # -- the fast loop for the daily three, the slow loop for the rest
    # -- and a held loop breaks both of them with "this event loop is
    # already running". So the loop is PUMPED in slices instead: the
    # caller says "run for 90 seconds", pushed messages are delivered
    # during those 90 seconds, and the client is free again the moment
    # it returns. A slice replaces a sleep the poller was doing anyway,
    # so it costs nothing and blocks nothing.

    def watch(self, channels, on_message):
        """Ask Telegram to push new posts from these channels.

        `on_message(handle, record)` is called for each one, with the
        same record shape fetch() returns -- see _shape().

        Registering is cheap and idempotent-ish: called again, it
        replaces the handler rather than stacking a second one.
        Returns the number of channels being watched, or 0 if push is
        not available, so the caller can say so rather than assume.
        """
        try:
            from telethon import events
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[TELEGRAM] No push support ({exc}). Polling only.")
            return 0
        try:
            client = self._connect()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[TELEGRAM] Could not open the connection to listen "
                 f"({str(exc)[:70]}). Polling only.")
            return 0

        entities, handles = [], {}
        for spec in channels or []:
            try:
                entity = self.resolve(spec)
            except Exception as exc:                       # noqa: BLE001
                # One unreadable channel costs that channel, never the
                # rest -- the same posture poll() has always had.
                diagnostic(f"[TELEGRAM] Cannot listen to {spec} "
                           f"({str(exc)[:50]})")
                continue
            entities.append(entity)
            handles[id(entity)] = str(spec).strip().lstrip("@")
        if not entities:
            return 0

        if self._on_push is not None:
            try:
                client.remove_event_handler(self._on_push)
            except Exception:                              # noqa: BLE001
                pass

        async def _handler(event):
            # Wrapped whole. This runs inside telethon's loop, and an
            # exception here would take the loop down and with it the
            # polling that is meant to be the safety net.
            try:
                message = getattr(event, "message", None)
                if message is None:
                    return
                chat = await event.get_chat()
                handle = (getattr(chat, "username", None)
                          or getattr(chat, "title", None) or "")
                record = self._shape(client, message,
                                     str(handle).lstrip("@"))
                if record is not None:
                    on_message(str(handle).lstrip("@"), record)
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[TELEGRAM] Pushed message not stored: "
                           f"{str(exc)[:70]}")

        client.add_event_handler(_handler, events.NewMessage(chats=entities))
        self._on_push = _handler
        self._watching = True
        return len(entities)

    def pump(self, seconds):
        """Run the update loop for a while, delivering pushed posts.

        This is a SLEEP that listens. The caller was going to wait
        anyway; during the wait Telegram delivers, and when it returns
        the client is free for the next poll.

        Returns True if it actually listened. False means the caller
        should fall back to an ordinary sleep -- push is off, the
        connection is down, or telethon refused -- and False must never
        become a busy loop, so the caller sleeps on it.
        """
        if not self._watching or seconds <= 0:
            return False
        try:
            import asyncio as _asyncio
            client = self._connect()
            client.loop.run_until_complete(_asyncio.sleep(float(seconds)))
            return True
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[TELEGRAM] Listening stopped ({str(exc)[:70]}). "
                       f"Falling back to polling for this cycle.")
            return False

    def close(self):
        if self._client is not None:
            try:
                if self._on_push is not None:
                    self._client.remove_event_handler(self._on_push)
            except Exception:                              # noqa: BLE001
                pass
            self._on_push = None
            self._watching = False
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


def _looks_like_a_username(handle):
    """Could t.me/s/<handle> exist at all?

    Telegram usernames are ASCII letters, digits and underscores. A
    title -- "Breakouts", "Earnings 360" -- has spaces or emoji and can
    never be a URL, which is what folder_sources() hands back for a
    private channel with no username.

    Deliberately loose on length: this is asking "is a web page even
    possible", not "is this a valid username".
    """
    text = str(handle or "").strip().lstrip("@")
    if not text:
        return False
    return all(c.isascii() and (c.isalnum() or c == "_") for c in text)


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
        # Channels told about once, not every ninety seconds.
        self._no_web_view = set()

    def fetch(self, channel, limit=30, before=None, since_id=None,
              ids=None):
        handle = channel if isinstance(channel, str) else str(channel)
        # ---- THE WEB VIEW CANNOT ANSWER THIS ONE. 5 Sep 2026. ----
        #
        # t.me/s/<channel> serves pages, not posts. There is no way to
        # ask it for id 3741 and nothing else. A gap fill that silently
        # fell back to it would return a PAGE and store whatever was on
        # it, which is the opposite of "ask for exactly what is
        # missing" -- so the request is refused rather than approximated.
        # The caller treats an empty answer as "not filled this run",
        # which is true and harmless: the hole is still in the store and
        # the next run with a working API asks again.
        if ids and self.primary is None:
            return []
        if self.primary is not None:
            # ---- "DOES NOT TAKE THAT ARGUMENT" IS NOT "FAILED". ----
            #      30 August 2026.
            #
            # Passing since_id unconditionally made any reader without
            # it look like a broken API, and the fallback then dropped
            # to the public web view -- which a PRIVATE channel does
            # not have. The channel would go quietly empty and the
            # warning would blame Telegram. Caught by
            # tests/test_telegram_api_reader.py in one run.
            #
            # So it is only sent when there is one, and a reader that
            # cannot take it is retried without it rather than
            # written off.
            extra = {"since_id": since_id} if since_id else {}
            if ids:
                # Named posts are not a page. Nothing else may travel
                # with the request -- see TelethonReader.fetch().
                extra = {"ids": list(ids)}
            try:
                try:
                    if ids:
                        return self.primary.fetch(handle, **extra)
                    return self.primary.fetch(handle, limit=limit,
                                              before=before, **extra)
                except TypeError:
                    if not extra:
                        raise
                    if ids:
                        # An older reader with no `ids` argument. Filling
                        # the hole is not possible; guessing at it with a
                        # page is worse than leaving it open.
                        return []
                    return self.primary.fetch(handle, limit=limit,
                                              before=before)
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
        # ==========================================================
        # A PRIVATE CHANNEL HAS NO WEB PAGE.  31 August 2026.
        # ==========================================================
        #
        # His terminal, four times every ninety seconds all afternoon:
        #
        #     [TELEGRAM] Breakouts: URL can't contain control
        #     characters. '/s/Breakouts ...' (found at least ' ')
        #
        # core/telegram_client.folder_sources() takes a channel's
        # USERNAME if it has one and falls back to its TITLE if it does
        # not. Four of the ten came through as titles -- Breakouts,
        # Business Pulse, Earnings 360, Earnings Pro -- which means
        # they are private channels with no public username. There is
        # no t.me/s/ page for them and never will be.
        #
        # So the fallback was being attempted on channels where it is
        # impossible, failing every pass, and printing roughly 160
        # warnings an hour over everything else in the terminal.
        #
        # It is skipped now, and said ONCE per channel per run. The
        # sentence matters more than the silence: two of the four are
        # RESULTS channels, and from 15 October they sit on the
        # 90-second loop carrying the most time-critical thing the bot
        # reads. When the API drops they go dark with nothing behind
        # them, and he needs to know that is the arrangement rather
        # than discover it in October.
        if not _looks_like_a_username(handle):
            if handle not in self._no_web_view:
                self._no_web_view.add(handle)
                warn(f"[TELEGRAM] {handle} is a private channel with no "
                     f"public username, so it has NO web fallback. It is "
                     f"readable through the API only -- if that drops, "
                     f"this channel goes dark until it returns.")
            return []
        # The public web view has no min_id -- it serves whole pages.
        # since_id is deliberately dropped rather than forwarded: the
        # id floor in telegram_feed._store() still skips what we hold,
        # so the fallback is slower, not wrong.
        return self.secondary.fetch(handle, limit=limit, before=before)

    # ---- THE FEED HOLDS THIS, NOT THE READER INSIDE IT. ----
    #                                        5 September 2026.
    #
    # watch() and pump() were added to TelethonReader, and the feed
    # holds a FallbackReader wrapping it. So TelegramFeed.listen() did
    #
    #     watch = getattr(self.client, "watch", None)
    #     if watch is None: return 0
    #
    # -- found nothing, returned 0, printed nothing, and the collector
    # ran a whole startup with the listener silently absent. His 16:48
    # run has no [PUSH] line anywhere in it.
    #
    # The fault this codebase keeps producing, and mine this time:
    # built on the inner object while the outer one is what the live
    # path actually holds. trading_gate, surge(), MOVE_DIED,
    # refused_symbols, _same_story(), the collector's own listener --
    # and now this.
    #
    # Both delegate, and both FAIL QUIET. The public web view cannot
    # push, and a channel that cannot push is polled, which is how this
    # worked for its entire life.

    def watch(self, channels, on_message):
        watcher = getattr(self.primary, "watch", None)
        if watcher is None:
            return 0
        try:
            return watcher(channels, on_message) or 0
        except Exception as exc:                           # noqa: BLE001
            warn(f"[TELEGRAM] Could not start listening "
                 f"({str(exc)[:70]}). Polling only.")
            return 0

    def pump(self, seconds):
        pumper = getattr(self.primary, "pump", None)
        if pumper is None:
            return False
        try:
            return bool(pumper(seconds))
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[TELEGRAM] Listening stopped ({str(exc)[:70]}). "
                       f"Polling covers this cycle.")
            return False

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
