"""
==========================================================
The Telegram channels, on the dashboard instead of a screen
==========================================================

    "separate screens for NSE; Trading; Telegram for continous
     updates. Now we will replace everything by our Dashboard."
    "Telegram channels - Day Trader Telugu , MoneyPurse,
     EARNINGS PULSE , ORDERBOOK PULSE"
                                    -- operator, 29 July 2026

WHAT THIS DOES
--------------
Reads recent messages from the four channels, finds the stock symbols
named in them, and hands the dashboard a list. That is all.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not trade on them, score them, or grade them. Not one field
here reaches core/engine.py, and that is a deliberate line rather than
an unfinished feature:

  - These are anonymous third-party channels. A tip is not a filing.
  - The operator's own rule for the whole bot is that entries need a
    real reason -- results, a filing, a measured breakout. "A Telegram
    channel mentioned it" is not one.
  - The bot cannot tell a paid promotion from a genuine call, and a
    pump is exactly the sort of message that names a small illiquid
    stock in an excited tone.

So this is a READING panel: it replaces the screen he watches, and
leaves the judgement where it already is -- with him.

SYMBOL MATCHING is deliberately strict. A message is matched against
the master file's real symbols on word boundaries only. Loose matching
would tag every message containing "ALL", "ON" or "IT" -- and a
mentions panel that is wrong is worse than no panel, because he would
stop trusting the ones that are right.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn
from core.stock_events import events_from_message

# How often the background poller re-reads the channels. 90s because
# Earnings Pulse posts a filing within 1-2 minutes of it landing, and the
# whole value of the feed is that freshness -- but t.me/s/ is a courtesy
# HTML view and hammering it would be rude and would get us blocked.
POLL_SECONDS = 90

# How often the FULL pass runs -- every channel, including the ones he
# has told me are episodic or results-season only. The daily three run
# on POLL_SECONDS above; see start() for the measurement that split
# them. Nothing is read less often than it was: a full pass still
# happens, just not in front of the channels that carry order wins.
SLOW_POLL_SECONDS = 300

# A message later than this has probably already cost the move it was
# about. Measured over 18-29 August the median was 5.7 minutes and the
# p90 was 21.5 -- and 30 of 459 in-hours events had already run 1% or
# more before the bot saw them. See TelegramFeed._report_lag().
SLOW_FEED_WARN_MINUTES = 10.0

# Past this, it is the bot catching up after being off, not the feed
# running late. See _report_lag() -- the 28 August restart stored 227
# messages from the previous day, which reads as a 1,440-minute lag.
CATCH_UP_MINUTES = 120.0

# What each pass asks a channel for. The FIRST pass of a process asks
# for more, because nothing was collecting while the bot was down --
# see TelegramFeed._next_limit().
DEFAULT_LIMIT = 30
FIRST_PASS_LIMIT = 120


def _as_ist(stamp):
    """A stored stamp as naive IST, or None.

    One clock for the whole repo -- core/feed_clock.to_ist() is what
    every other reader of these two columns uses. `at` carries a UTC
    offset and `seen_at` does not, so comparing them raw is how a
    five-and-a-half hour "lag" gets reported.
    """
    try:
        from core.feed_clock import to_ist
        got = to_ist(stamp)
    except Exception:                                      # noqa: BLE001
        return None
    if got is None:
        return None
    return got.replace(tzinfo=None) if got.tzinfo else got


# A ticker straight after a number and a slash is a unit of measure --
# "$84.94/BBL", "Rs 2,053/kg", "5,773.63/Sh". See symbols_in().
_UNIT_AFTER_NUMBER = re.compile(r"(?<=[0-9])\s*/\s*(#?[A-Za-z]{2,})")

# OIL after a commodity word, DOLLAR after a currency one. Both are
# real NSE tickers and ordinary English in the same breath.
_COMMODITY_OR_CURRENCY = re.compile(
    r"\b(?:CRUDE|BRENT|PALM|WTI|COOKING|EDIBLE|HEATING|FUEL|SOY)\s+(OIL)\b"
    r"|\b(?:US|U\.S\.|THE|PER|BILLION|MILLION|TRILLION)\s+(DOLLAR)S?\b",
    re.I)


def _blank_the_word(match):
    """Blank only the ticker-shaped word, leaving the rest in place.

    The surrounding words still have to be readable -- another rule,
    or a human, may be looking at the same line.
    """
    word = match.group(1) or match.group(2)
    return match.group(0)[:-len(word)] + "x" * len(word)

# ---------------------------------------------------------------
# HOW LONG THE RAW MESSAGES ARE KEPT
# ---------------------------------------------------------------
# Was 36 hours, and _prune() measures from seen_at -- when WE stored
# it, not when it was posted. So everything collected on Friday
# afternoon was deleted around 03:00 on Sunday, before Monday's
# session ever started.
#
# The extracted EVENTS survive that (stock_events.db is never pruned),
# so the score was not losing anything. What was being lost is the
# ability to RE-DERIVE: tools/build_stock_events.py rebuilds the whole
# events table from these messages, and it is the only way a rule
# change reaches old data. With a 36-hour window, any improvement made
# over a weekend could never be applied to the Friday that prompted it.
#
# 96 hours keeps a full weekend. These rows are small -- 660 messages
# is well under a megabyte -- so the cost is nothing and the thing it
# buys is the ability to fix a mistake retrospectively.
KEEP_HOURS = 96

# How many pages back the startup catch-up will walk before giving up.
# A page is ~20 posts, so 40 pages is ~800 -- comfortably more than the
# 400-700 the busiest channel produces over a Friday-to-Monday gap.
# It almost never runs to the end: the walk stops the moment a page
# overlaps what is already stored, which on a normal overnight gap is
# the second or third page.
CATCH_UP_PAGES = 40

# Messages per page during the walk. The public web view serves about
# twenty whatever you ask for; the Telegram API serves exactly what you
# ask for, and serves EVERYTHING if you ask for nothing -- which is how
# three channels stopped dead at 30 messages on 1 August. Stated here
# so neither reader has to guess.
CATCH_UP_PAGE_SIZE = 100


def _boxes_json(boxes):
    """Word positions -> a compact JSON string, or None.

    Compact on purpose: a busy card is several hundred words and this
    row is written on every poll. Only the four numbers rows_from_grid()
    actually reads are kept, and the text itself.
    """
    if not boxes:
        return None
    try:
        import json
        small = [{"t": b.get("text"), "l": b.get("left"),
                  "y": b.get("top"), "w": b.get("width"),
                  "h": b.get("height")}
                 for b in boxes if b.get("text")]
        return json.dumps(small, separators=(",", ":")) if small else None
    except Exception:                                      # noqa: BLE001
        # A picture whose positions cannot be serialised is still a
        # picture whose TEXT is worth storing. Never let this be the
        # thing that loses a message.
        return None


def boxes_from_json(blob):
    """The stored positions, back in the shape rows_from_grid() wants."""
    if not blob:
        return []
    try:
        import json
        return [{"text": b.get("t"), "left": b.get("l"), "top": b.get("y"),
                 "width": b.get("w"), "height": b.get("h")}
                for b in json.loads(blob)]
    except Exception:                                      # noqa: BLE001
        return []


def _all_older_than(messages, hours):
    """Is every message on this page past the retention window?

    Used to stop the history walk. Returns False when nothing can be
    dated -- an unreadable timestamp must not end the walk early and
    leave a real gap unfilled.
    """
    if not messages:
        return False
    cutoff = datetime.now() - timedelta(hours=hours)
    dated = 0
    for message in messages:
        when = message.get("at")
        # ---- A UTC STAMP READ AS IST IS 5h30m STALE. 23 Aug 2026 ----
        # Both arms discarded the offset rather than applying it, so
        # data/telegram.db's "+00:00" stamps made a live feed look
        # five and a half hours behind. core/feed_clock.to_ist() is
        # the one converter; naive after, as the caller compares
        # against a naive clock.
        try:
            from core.feed_clock import to_ist
            moment = to_ist(when)
            when = None if moment is None else moment.replace(tzinfo=None)
        except Exception:                                   # noqa: BLE001
            when = None
        if when is None:
            continue
        dated += 1
        if when >= cutoff:
            return False
    return dated > 0

# How many events one poll may send to the model. A normal 90-second
# poll files a handful; a cap this low means a runaway cycle costs
# pennies rather than the month's budget, and tools/ai_backfill.py
# sweeps up anything a busy minute left behind.
LIVE_GRADE_LIMIT = 25

DB_PATH = os.path.join("data", "telegram.db")

# The operator's own channels, by their REAL @handles -- verified by
# fetching each one on 29 July 2026, because guessing was worse than
# useless: a guessed "@earningspulse" resolved to a 3-subscriber
# Spanish-language Mr Beast channel that would have filled the panel
# with a stranger's messages.
#
# `kind` decides how the panel renders it, and it was measured:
#
#   text    #UPL - Great Results - 1 minute ago  + link to the PDF
#   image   173,000 photos, and twenty consecutive market-hours posts
#           with no text at all -- screenshots from X and news sites.
#           The operator reads these himself; the dashboard shows the
#           picture rather than pretending to understand it.
# `trust_hashtags` is NOT cosmetic. Measured on the live pages,
# 30 July 2026:
#
#   earnings_pulse   "#MOLDTKPAC - Great Results"  the hashtag IS the
#   orders_pulse     "Ameenji wins Rs 47.46cr order. #AMEENJI"
#                    subject of the post. Reliable.
#
#   news_pulse_ai    hashtags are AI-generated and demonstrably wrong:
#                    a CBIZ / Grant Thornton story tagged #MODRNSH, a
#                    Hexaware results line tagged #GSTL_RE, an India-US
#                    trade story tagged #WINROC. None of those
#                    companies were in the story.
#
# Tagging a position with the wrong stock is worse than not tagging
# it, so that channel's symbols come from the strict text matcher
# only -- which finds COFORGE in "Coforge anticipates a strong Q2"
# and correctly finds nothing in the CBIZ line.
#
# KEPT, 30 July 2026: "we have enough daytradertelugu, earnigpluse,
# newspulse". Dropping it had been recommended on the strength of those
# three wrong hashtags. That recommendation is withdrawn -- it was
# measured before core/news_impact.py's matcher was rewritten, and all
# three failures now resolve correctly:
#
#   CBIZ / Grant Thornton  #MODRNSH  -> nothing        (correct)
#   India-US trade         #WINROC   -> nothing        (correct)
#   Hexaware results       #GSTL_RE  -> HEXT           (correct, and the
#                                       right symbol, found from the
#                                       text while the AI's own tag was
#                                       ignored)
#
# The channel is still Tier 3 -- an AI relaying other people's news,
# with no primary source at the end of it. It reads and it remembers.
# It must never carry conviction weight.
# MONEYPURSE IS NOT WATCHED, AND THAT IS SETTLED.
#
#     "@moneypurse isnot required. we have enough daytradertelugu,
#      earnigpluse, newspulse"        -- operator, 30 July 2026
#
# It was one of the four channels originally named, so this is recorded
# rather than silently dropped. Nobody should reopen it, and nobody
# should guess a handle for it -- two were checked against the live
# pages on 30 July 2026 and both were wrong:
#
#   @moneypurse         resolves, but /s/ redirects to a contact page
#                       with an empty description -- a private channel
#                       or a user account. No public web view exists,
#                       so the web reader cannot read it at all.
#
#   @moneypursetelugu   "Money purse { మనీ పర్స్ } Official", and it is
#                       NOT his channel. 3 subscribers. Dormant since
#                       2022 ("cash back if u join before 06/04/2022").
#                       Posts read:
#                           "Stop Loss : Only for paid members"
#                           "JOIN OUR OPTIONS PREMIUM PLAN STARTS @7499"
#                           "For more details DM me @Kingpinadvisory"
#                       An options tip service trading on the real
#                       channel's name. This is the exact paid-promotion
#                       content the module docstring says the bot cannot
#                       tell from a genuine call.
#
# That is TWO guessed handles that resolved to the wrong channel, on top
# of an earlier one that resolved to a 3-subscriber Spanish-language Mr
# Beast channel. If this is ever wanted, the handle must come from the
# operator's own Telegram app -- open the channel, tap its name, copy
# the @handle. It must never be inferred from the channel's title.
# ---- CHANNELS WE DO NOT RE-READ BACKWARDS. 10 August 2026. ----
#
#     "out of 9 channels . brealout, news pulse , WLPULSE bot we can
#      skip from getting back data. remaining 6 we will start"
#
# These three are still POLLED FORWARD every cycle. What is skipped is
# the weekend catch-up walk, which for nine channels is 400-700 posts
# each at 3.5 minutes a page -- the exact thing that on 3 August was on
# channel 2 of 9 when the market opened.
#
# Matched loosely on the stored channel NAME, because the names carry
# emoji and spacing that vary ("Breakouts 🇮🇳").
CATCH_UP_SKIP = ("BREAKOUT", "NEWS PULSE", "WLPULSE")


def _skip_catch_up(name):
    upper = str(name or "").upper()
    return any(mark in upper for mark in CATCH_UP_SKIP)


CHANNELS = [
    {"handle": "earnings_pulse", "name": "Earnings Pulse", "kind": "text",
     "trust_hashtags": True},
    {"handle": "orders_pulse", "name": "OrderBook Pulse", "kind": "text",
     "trust_hashtags": True},
    {"handle": "news_pulse_ai", "name": "News Pulse", "kind": "text",
     "trust_hashtags": False},
    {"handle": "daytradertelugu", "name": "Day Trader Telugu",
     "kind": "image", "trust_hashtags": False},

    # ---- ADDED 20 AUGUST 2026, ON HIS INSTRUCTION. ----
    #
    #     "redbox global added to pro channel in telegram , bot need
    #      to get data from that channel too"
    #
    # Handle verified with tools/telegram_channels.py rather than read
    # off the screenshot he sent -- that showed @REDBOXINDIA, which is
    # the X account. The Telegram channel is @Indiaredboxglobal, and a
    # wrong handle here reads NOTHING, silently, for as long as nobody
    # checks.
    #
    # trust_hashtags is FALSE. Its copy is macro and sector-level --
    # "COPPER COMPANIES WOULD BE IN FOCUS", "LME COPPER ONE-DAY SPREAD
    # HITS $110" -- so its tags describe a THEME, not the one company
    # a card is about. News Pulse taught this exact lesson on 8 August
    # when four Siemens Energy stories arrived tagged #SIEMENS and the
    # bot believed the tag.
    {"handle": "Indiaredboxglobal", "name": "RedboxGlobal India",
     "kind": "text", "trust_hashtags": False},
]

# English words that are also NSE tickers. Matching these would tag
# almost every message ever sent and make the panel useless.
NOT_A_MENTION = {
    "ALL", "AND", "ANY", "ARE", "BUY", "CAN", "FOR", "GET", "HAS", "IT",
    "ITC", "NOW", "ONE", "OUR", "OUT", "SELL", "THE", "TOP", "WAS", "WIN",
    "BEST", "GOOD", "HIGH", "LOW", "MAX", "MID", "NEW", "OLD", "SET",
    "TIME", "WELL", "GO", "ON", "IN", "AT", "UP", "BY", "OK", "PSU",
}


# The NAME-side twin of NOT_A_MENTION above. That set stops an English
# word being read as a TICKER; this one stops an English word being read
# as a one-word COMPANY NAME.
#
# EVERY ENTRY MUST BE COUNTED BEFORE IT IS ADDED. There are 392 one-word
# name entries and only six are English words at all. Five of those
# measured clean over all 2,967 stored messages and must NOT be added:
#
#     DOLLAR   -> DOLLAR      37 fired, 37 genuine, 0 false
#     TITAN, TRENT, SUVEN, GOLDIAM, WELSPUN   all genuine
#
# Only URBAN failed, and it failed badly.
NOT_A_NAME = {
    # URBAN COMPANY LIMITED. _NAME_SUFFIX strips COMPANY, leaving the
    # adjective. 4 genuine mentions against 13 false ones -- "urban
    # transit technology", "India's urban infrastructure sector",
    # "ahead of urban demand in Q1". The middle one filed Afcons's
    # Rs 900 crore order against URBANCO.
    "URBAN",
}


class TelegramFeed:
    """Recent messages from the operator's channels, and the stocks
    they name. Read-only, fail-quiet, never an input to a trade."""

    _NOT_A_NAME = NOT_A_NAME

    def __init__(self, client=None, channels=None, master_loader=None,
                 db_path=DB_PATH, keep_hours=KEEP_HOURS, news_impact=None,
                 read_images=True, stock_events=None, ai_news=None):
        self.client = client
        # Every text message is also handed to the impact memory, so
        # "which stocks does this news touch" is answerable later --
        # see core/news_impact.py. Optional; None simply skips it.
        self.news_impact = news_impact
        # ---- THE TYPED EVENT MEMORY, WIRED LIVE 31 July 2026 ----
        #
        # Collecting a message and turning it into something the SCORE
        # can read were two separate steps, and only the first ran
        # during the session. The second was tools/build_stock_events.py
        # -- a command the operator typed after the close.
        #
        # Measured on 31 July: all 119 of the day's events were written
        # in one batch at 14:35:54. Typical delay 91 minutes, worst 429.
        # On a normal day the tool runs after 15:30, so a result posted
        # at 12:19 would first affect the ranking the NEXT MORNING.
        #
        #     "if today result came excellent & if the stock moved high
        #      even though we get them in top gainers but without why
        #      cards. i cannot trust the price movement right? genuine
        #      gap between trusted & vague buying"
        #
        # Exactly right, and it is the reason the panel exists. A stock
        # up 13% with a reason and a stock up 13% without one are
        # different objects, and the reason was already in our own
        # database -- an hour and a half before anything could read it.
        #
        # Now every poll files what it just collected. Optional: None
        # means the nightly tool is still the only path, which is what
        # every test that does not care about events wants.
        self.stock_events = stock_events
        # core/ai_news.py. Optional, and None is a fully supported
        # state -- it is exactly how the bot ran before 31 July: events
        # keep their kind and carry no direction.
        self.ai_news = ai_news
        # A channel may be given as a plain handle or as a dict with
        # its kind. Normalised once, here, so nothing downstream has
        # to handle both shapes.
        # config.EXTRA_TELEGRAM_CHANNELS is appended so the operator can
        # add a PRIVATE channel by its title without anyone editing this
        # file. Read here rather than at import so a config change takes
        # effect on the next run, not the next release.
        #
        # trust_hashtags is TRUE for these. The three channels whose
        # hashtags were measured wrong are all AI-generated relays; a
        # paid channel a human curates is a different thing. If one of
        # them ever tags a story with the wrong ticker, that assumption
        # is where to look.
        extra = []
        if channels is None:
            try:
                from config import EXTRA_TELEGRAM_CHANNELS
                extra = list(EXTRA_TELEGRAM_CHANNELS or [])
            except Exception:                              # noqa: BLE001
                extra = []
            # A Telegram FOLDER, if one is named. Curated in the app
            # rather than in a file -- drag a channel in and it is
            # watched. Wrapped whole: a folder that cannot be read must
            # cost the extra channels, never the session.
            #
            # ---- A READER DOES NOT PHONE TELEGRAM. 12 Aug 2026. ----
            #
            #     "[TELEGRAM] Folder 'PRO' is empty or unreadable"
            #                                -- main.py, 22:53
            #
            # It was neither. The folder holds all nine channels and
            # reads fine on demand. What failed was WHO was asking.
            #
            # main.py builds TelegramFeed(client=None) and says so in
            # its own log line -- "Read-only view of data/telegram.db.
            # This process does NOT collect." But the constructor ran
            # the folder lookup anyway, and channels_in_folder() opens
            # its own live Telethon client. So a process that will
            # never poll a channel was opening a Telegram API session
            # at startup, on the same session FILE the collector holds
            # open in the other terminal. Two clients, one SQLite
            # session, a race -- and the loser prints a warning telling
            # the operator to go and check his folder name.
            #
            # A read-only view takes its channel list from the store it
            # reads. feed_watermark already holds every channel that
            # has ever posted, with a message count, written by the
            # collector as it goes. No API call, no session contention,
            # no false alarm -- and the names are the ones that have
            # actually delivered rather than the ones subscribed to.
            if self.client is None:
                # db_path, not self.db_path -- self.db_path is not
                # assigned until AFTER this block. Calling the method
                # bare returned [] every time, silently, because the
                # AttributeError landed in its own except. The channel
                # list looked right (4 base + 1 config extra) which is
                # exactly why it took a count to notice.
                found = self._channels_from_store(db_path)
                if found:
                    diagnostic(f"[TELEGRAM] Read-only view: {len(found)} "
                               f"channel(s) from the store.")
                extra += found
            else:
                try:
                    from config import TELEGRAM_FOLDER
                    if TELEGRAM_FOLDER:
                        from core.telegram_client import channels_in_folder
                        found = channels_in_folder(TELEGRAM_FOLDER)
                        if found:
                            decision(f"[TELEGRAM] Folder "
                                     f"{TELEGRAM_FOLDER!r}: {len(found)} "
                                     f"channel(s) -- {', '.join(found[:6])}")
                        else:
                            warn(f"[TELEGRAM] Folder {TELEGRAM_FOLDER!r} is "
                                 f"empty or unreadable. Check the name "
                                 f"matches the app exactly, and that "
                                 f"py tools/telegram_setup.py has been run.")
                        extra += found
                except Exception as exc:                   # noqa: BLE001
                    diagnostic(f"[TELEGRAM] Folder lookup skipped: {exc}")
        # DEDUPLICATED, because the same channel arrives twice the
        # moment the operator does the sensible thing:
        #
        #     "yes all moved to pro folder."
        #
        # The four public channels are in CHANNELS by handle AND now in
        # the PRO folder by title, so without this every poll would
        # fetch each of them twice and the catch-up would walk their
        # history twice -- at a stranger's expense, for nothing.
        #
        # Matched on BOTH handle and name, lowercased, because the
        # folder returns a @username for a public channel and a title
        # for a private one, and CHANNELS carries both.
        seen = set()
        self.channels = []
        for raw in ((channels or CHANNELS) + extra):
            entry = raw if isinstance(raw, dict) else {
                "handle": raw, "name": raw, "kind": "text",
                "trust_hashtags": True}
            keys = {str(entry.get("handle") or "").strip().lower(),
                    str(entry.get("name") or "").strip().lower()}
            keys.discard("")
            if keys & seen:
                continue
            seen |= keys
            self.channels.append(entry)

        # ---- THE THREE THAT MATTER GO FIRST. 24 August 2026. ----
        #
        #     "daily focused channels: OrderBook Pulse, Day Trader
        #      Telugu , RedboxGlobal India = these channels will get
        #      posted on daily & event occuring times. so delay in
        #      getting their data into bot will cost us money."
        #                                    -- operator, 24 Aug 2026
        #
        # POLL_SECONDS is 90, but the MEASURED median lag on 24 August
        # was 4.8 minutes, because one pass walks ten channels and
        # OCRs every image before it comes back round. The three that
        # carry the order wins were queued behind seven that he has
        # told me are episodic or results-only -- WLPulseBot posts
        # when its 100 tracked stocks move, Business Pulse when a
        # company publishes, the Earnings channels in season.
        #
        # A stable sort, so nothing else changes order: the daily
        # three are read first every pass, and a slow OCR on a
        # promotional card can no longer delay an order win.
        #
        # Same list as core/feed_clock.DAILY_CHANNELS -- imported, not
        # retyped, so the two cannot drift.
        try:
            from core.feed_clock import channel_kind

            def _priority(entry):
                # The folder hands over USERNAMES ("orders_pulse"),
                # the store keeps TITLES ("OrderBook Pulse").
                # channel_kind() resolves either through
                # feed_clock.CHANNEL_ALIASES; matching raw strings
                # would have prioritised nothing at all.
                for key in ("handle", "name"):
                    if channel_kind(entry.get(key)) == "daily":
                        return 0
                return 1

            self.channels.sort(key=_priority)
        except Exception:                                  # noqa: BLE001
            pass        # order is an optimisation, never a requirement

        self.master_loader = master_loader
        # Posts Telegram PUSHED, as opposed to ones we asked for.
        # pushed_count() reads it, so a listener that has gone quiet
        # and a quiet news day do not look the same.
        self._pushed = 0
        self.db_path = db_path
        self.keep_hours = keep_hours
        self._lock = threading.Lock()
        # Reading pictures is opt-out. It is local, free and off the
        # trading path, but a session must always be able to run without
        # it -- see core/image_text.py.
        self.read_images = read_images
        self._ocr_cache = {}
        # Word boxes beside the text, so a GRID card can be read by
        # position rather than by whatever order Tesseract walked it
        # in. See _read_photo() and core/recap_card.rows_from_grid().
        self._ocr_boxes = {}
        self._ocr_misses = 0
        self._symbols = None
        # The same set without the 3-character floor -- see
        # _known_symbols(). Only ever used for explicit hashtags.
        self._symbols_tagged = None
        self._names = None
        self._last_poll_at = None
        self._last_error = None
        # A store failure is the same failure on every channel on every
        # poll -- four identical warnings a minute buried the one line
        # that mattered. Warned once per process, then counted.
        self._store_warned = False
        self._store_failures = 0
        # Background poller -- see start(). None until started.
        self._thread = None
        self._slow_thread = None
        # Posted-to-stored lag, this session. See _report_lag().
        self._lags = []
        # The first pass reaches further back. See _next_limit().
        self._first_pass_done = False
        self._stop = threading.Event()
        self._ensure_db()

    # ------------------------------------------------------------

    # Every column beyond the original six, with its type. Named here
    # ONCE so _ensure_db and _migrate can never drift apart -- which is
    # exactly how the bug below happened.
    _EXTRA_COLUMNS = (
        ("grade", "TEXT"),
        ("filing_url", "TEXT"),
        ("photos", "TEXT"),
        ("url", "TEXT"),
        ("kind", "TEXT"),
        ("is_calendar", "INTEGER DEFAULT 0"),
        # What the picture said, 30 July 2026. Its OWN column, never
        # merged into `text`: the original message stays exactly as the
        # channel sent it, so it is always possible to tell what a human
        # typed from what a machine read off a screenshot. See
        # core/image_text.py.
        ("ocr_text", "TEXT"),
        # ---- WHERE EACH WORD WAS. 5 September 2026. ----
        #
        # Tesseract walks a picture COLUMN BY COLUMN, so the flat
        # transcript of a grid comes out in an order that has nothing to
        # do with what belongs to what. Earnings Pulse's week-ahead card
        # is exactly that shape:
        #
        #     EARNINGS PULSE - THE WEEK AHEAD
        #     SAT ... MOLBIO  13,355 Cr  MID CAP
        #     MON ... SHIPROCKET  9,894 Cr  MID CAP
        #            BLEL  1,925 Cr  SMALL CAP
        #
        # Every company right, every figure right -- and WHICH DAY each
        # one reports is lost, because the day headers and the cards are
        # separate columns. On 2 August that put NINE companies
        # reporting during market hours into the after-the-close bucket.
        #
        # core/recap_card.rows_from_grid() fixes it from the word
        # coordinates, and image_text.words_with_positions() produces
        # them for free -- image_to_data runs the same recognition pass
        # image_to_string already did. They were then held in memory for
        # ninety seconds and thrown away, so nothing could re-group a
        # card after the fact and nothing could check a bad read.
        #
        # Stored as JSON beside the transcript. The bot records
        # days_since_results on every trade and the results grade gates
        # entry, so a company put on the wrong day is a stock watched on
        # the wrong day.
        ("ocr_boxes", "TEXT"),
    )

    def _ensure_db(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                " channel TEXT, message_id TEXT, at TEXT, text TEXT,"
                " symbols TEXT, seen_at TEXT, grade TEXT,"
                " filing_url TEXT, photos TEXT, url TEXT, kind TEXT,"
                " is_calendar INTEGER DEFAULT 0,"
                " PRIMARY KEY (channel, message_id))")
            # ---- WHAT WAS ASKED FOR AND NEVER CAME. 5 Sep 2026. ----
            #
            # Telegram numbers SERVICE posts in the same sequence as
            # real ones -- somebody joins, a message is pinned, the
            # channel photo changes -- and the reader skips anything
            # with no text and no picture. Those ids can never be
            # stored, so a gap filler with no memory would ask for the
            # same dead numbers on every run, for ever, at somebody
            # else's server.
            #
            # Three tries and the id is left alone. That is enough for
            # a genuine post that was rate-limited on the first two
            # attempts, and it stops the pointless traffic that would
            # otherwise look exactly like a bot hammering an API --
            # which is the one thing he has said must never happen.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS gap_attempts ("
                " channel TEXT, message_id INTEGER, tries INTEGER,"
                " first_try TEXT, last_try TEXT, outcome TEXT,"
                " PRIMARY KEY (channel, message_id))")
            conn.commit()
            self._migrate(conn)
            conn.close()
        except sqlite3.Error as exc:
            warn(f"[TELEGRAM] Could not open {self.db_path}: {exc}")

    def _migrate(self, conn):
        """Add any column this file writes that the table on disk does
        not have.

        WHY THIS EXISTS -- the single worst bug in this module's life.
        _ensure_db uses CREATE TABLE IF NOT EXISTS. When `grade`,
        `filing_url`, `photos`, `url`, `kind` and `is_calendar` were
        added to the INSERT, the table already existed with the
        original six columns, so IF NOT EXISTS did nothing and no
        migration was ever written. Every single insert then failed:

            [TELEGRAM] Could not store {...}: table messages has no
            column named grade

        The fetch worked perfectly the whole time -- 20 messages from
        each of four channels, every poll -- and all 80 were thrown
        away at the last step. `messages` held 0 rows, so recent(),
        for_symbol() and most_mentioned() returned nothing and the
        panel was blank in every session after the schema changed.

        Nothing in the logs said "schema" and the startup warnings
        pointed at telethon / api_id / my.telegram.org instead, so the
        API was blamed for months for a local ALTER TABLE.

        Note what was NOT lost: _store hands every message to
        core/news_impact.py BEFORE this insert, so news_memory.db kept
        filling up (63 stories, 166 links). The stock->news memory was
        working; only the display store was broken.
        """
        try:
            have = {row[1] for row in
                    conn.execute("PRAGMA table_info(messages)")}
        except sqlite3.Error as exc:
            warn(f"[TELEGRAM] Could not read the messages schema: {exc}")
            return
        if not have:                       # table genuinely absent
            return
        added = []
        for column, coltype in self._EXTRA_COLUMNS:
            if column in have:
                continue
            try:
                conn.execute(f"ALTER TABLE messages ADD COLUMN "
                             f"{column} {coltype}")
                added.append(column)
            except sqlite3.Error as exc:
                warn(f"[TELEGRAM] Could not add column {column}: {exc}")
        if added:
            conn.commit()
            decision(f"[TELEGRAM] Schema migrated -- added {len(added)} "
                     f"missing column(s): {', '.join(added)}. Messages "
                     f"were being fetched and then discarded before this.")

    # ------------------------------------------------------------

    def _known_symbols(self, hashtag=False):
        """Every symbol the bot KNOWS, minus the ones that are also words.

        TWO BUGS FIXED HERE, 30 July 2026. Measured on the live store:
        79 messages displayed a #TICKER and stored no symbol at all,
        including "#ACMESOLAR - Excellent Results".

        (1) include_blocked. all_symbols() defaults to the SUBSCRIBED
            list -- 668 of 973 -- so the 305 blocked stocks were
            invisible to the matcher and 21 tickers were silently lost.
            That conflated two different questions: "may the bot trade
            this" and "does the bot know what this is". Being barred from
            trading ACMESOLAR is no reason to fail to notice that it
            just reported excellent results. The dashboard already
            labels such rows NOT TRADEABLE, so nothing here can imply a
            permission that does not exist.

        (2) short tickers. The >= 3 character floor exists so a bare
            "LT" in prose does not tag Larsen & Toubro, and it should
            stay for TEXT. But a HASHTAG is explicit -- somebody typed
            "#LT" to mean exactly that company -- and the floor was
            being applied to both paths, so "L&T secures mega order for
            1,600 MW thermal power plant. #LT" stored nothing.

        `hashtag=True` therefore returns the unfiltered set: use it only
        where the symbol arrived as a deliberate tag.
        """
        if self._symbols is None:
            symbols = set()
            if self.master_loader is not None:
                try:
                    symbols = {s.strip().upper() for s in
                               self.master_loader.all_symbols(
                                   include_blocked=True)}
                except TypeError:
                    # An older MasterLoader without the keyword. Better
                    # the subscribed list than no symbols at all.
                    symbols = {s.strip().upper()
                               for s in self.master_loader.all_symbols()}
                except Exception:                          # noqa: BLE001
                    symbols = set()
            self._symbols_tagged = {s for s in symbols
                                    if s not in NOT_A_MENTION}
            self._symbols = {s for s in self._symbols_tagged if len(s) >= 3}
        return self._symbols_tagged if hashtag else self._symbols

    # Words that end a company name and identify nothing: the legal
    # suffix. NOT the descriptive words -- stripping "INDUSTRIES" left
    # "AARTI INDUSTRIES" as a single word and lost it, which was the
    # first attempt at this.
    _NAME_SUFFIX = {"LIMITED", "LTD", "PVT", "PRIVATE", "CORP",
                    "CORPORATION", "COMPANY", "CO", "AND", "THE", "OF"}

    # ==============================================================
    # A STATE IS NOT A COMPANY.  5 September 2026.
    # ==============================================================
    #
    #     "for me all info must be tagged properly & never mis ,
    #      duplicate , thats it"                    -- the operator
    #
    # names_in() recognises a company by the FIRST TWO WORDS of its
    # name, and two words is normally a good safeguard -- "Aarti" alone
    # would tag half the exchange. It fails completely when those two
    # words are a place:
    #
    #     TAMIL NADU NEWSPRINT & PAPERS   ->  pair (TAMIL, NADU)
    #
    # so ANY message mentioning the state named the paper mill. Counted
    # on the store: 18 events filed against TNPL, and EIGHT of them are
    # the state --
    #
    #     "Ops at arm Del Monte Food, Tamil Nadu plant halted"  SUNDROP
    #     "Network partner stores in Rajasthan, Tamil Nadu"     OLAELEC
    #     "US FDA conducted inspection at arm in Tamil Nadu"    CAPLIN
    #     "CO SECURES 119.85 CRORE ORDER FROM NHAI FOR ..."     BRGIL
    #
    # Every one of those is a reason on a stock that had no news. A
    # false reason is worse than a missing one: it opens the door -- a
    # published reason is MANDATORY before the bot will even evaluate a
    # stock -- so a paper mill was being put in front of the ranker on
    # days when somebody else built a road.
    #
    # Where the first two words are a place, the THIRD word is required.
    # TAMIL NADU NEWSPRINT still matches on all three; "Tamil Nadu
    # plant" no longer matches anything. A company whose name is ONLY a
    # place keeps its pair -- there is no third word to ask for, and
    # nothing else it could be.
    _PLACE_PAIRS = frozenset({
        ("TAMIL", "NADU"), ("ANDHRA", "PRADESH"), ("MADHYA", "PRADESH"),
        ("UTTAR", "PRADESH"), ("HIMACHAL", "PRADESH"),
        ("ARUNACHAL", "PRADESH"), ("WEST", "BENGAL"),
        ("JAMMU", "KASHMIR"), ("NEW", "DELHI"), ("NAVI", "MUMBAI"),
    })

    def _name_index(self):
        """Two ways to recognise a company by the name on a card.

        BUILT FOR PICTURES, 30 July 2026. The first real OCR run read
        nine result cards cleanly and matched almost nothing, because
        symbols_in() looks for TICKERS and a card prints the NAME:

            Aarti Industries   Data Pattern   Indegene   Mallcom

        `pairs`  the first two words of the name. Two words is the
                 safeguard -- "Aarti" alone or "Data" alone would tag
                 half the exchange.
        `solo`   a company whose ENTIRE name is one word. INDEGENE
                 LIMITED is just INDEGENE, and there is no pair to match.

        The second one nearly repeated the morning's POINT/SOUTH bug.
        The first attempt indexed any word belonging to exactly one
        company, and the result cards print a SECTOR line as well as a
        name:

            "Healthcare Research, Analytics & Technology" -> LATENTVIEW
            "Capital Markets | Stockbroking & Allied"     -> ABDL

        ANALYTICS and ALLIED are each unique in the master -- as
        FRAGMENTS of "LATENT VIEW ANALYTICS" and "ALLIED BLENDERS". Rare
        is not the same as being a name. So a one-word match now
        requires the company's whole name to be that one word.
        """
        if self._names is not None:
            return self._names
        pairs, solo, triples = {}, {}, {}
        if self.master_loader is not None:
            try:
                symbols = self.master_loader.all_symbols(include_blocked=True)
            except TypeError:
                symbols = self.master_loader.all_symbols()
            except Exception:                              # noqa: BLE001
                symbols = []
            for symbol in symbols:
                try:
                    record = self.master_loader.get_by_symbol(symbol) or {}
                except Exception:                          # noqa: BLE001
                    continue
                name = str(record.get("COMPANY NAME") or "").upper()
                # ---- A PLACEHOLDER IS NOT A NAME. 2 August 2026. ----
                #
                #     "what ever the stocks we are not maintained in
                #      our master data base pls add them in our
                #      universe"
                #
                # tools/discover_stocks.py adds a discovered stock with
                # SECURITY ID and SYMBOL from Dhan and COMPANY NAME set
                # to the ticker, because Dhan's compact master does not
                # carry a company name and inventing one is worse.
                #
                # That placeholder must not enter the NAME index. The
                # widened search reaches 751 candidates, and a one-word
                # "name" of five characters or more becomes a solo
                # entry -- so HEIDELBERG would match any sentence about
                # the German city, which is the URBANCO bug arriving in
                # bulk.
                #
                # The TICKER index is untouched: symbols_in() still
                # finds #HEIDELBERG, which is how these stocks are
                # meant to be recognised.
                #
                # ---- AND "NAME EQUALS SYMBOL" IS NOT ENOUGH ----
                #
                # That was the first version of this guard, and
                # tests/test_name_is_not_an_adjective.py failed it in
                # one run. DOLLAR is a real, curated, tradeable stock
                # whose COMPANY NAME genuinely IS "DOLLAR", measured 37
                # fired and 37 genuine. Dropping it would have been
                # exactly the collateral damage that test exists to
                # catch.
                #
                # What actually marks a placeholder is that NOTHING was
                # curated: no SECTOR. That is the same condition
                # MasterLoader.load() uses to decide a row may be left
                # unclassified, and it is only ever true for rows that
                # discover_stocks.py or morning_universe.py queued for
                # a human to look at.
                if (name == str(symbol).upper()
                        and not str(record.get("SECTOR") or "").strip()):
                    continue
                # EVERY token, including the short ones. "3M INDIA" and
                # "PI INDUSTRIES" are two-word names whose distinctive
                # half is two characters long -- filter those out first
                # and both collapse to a generic word, which is how
                # "Mallcom (India)" matched 3MINDIA and "Aarti
                # Industries" also matched PIIND.
                tokens_raw = [w for w in re.findall(r"[A-Z0-9]{1,}", name)
                              if len(w) >= 3]
                tokens = [w for w in re.findall(r"[A-Z0-9]{1,}", name)
                          if w not in self._NAME_SUFFIX]
                words = [w for w in tokens if len(w) >= 3]
                if not words:
                    continue
                if len(words) >= 2:
                    head = (words[0], words[1])
                    if head in self._PLACE_PAIRS and len(words) >= 3:
                        # See _PLACE_PAIRS. The pair is a state, so it
                        # names nothing on its own.
                        triples.setdefault(head + (words[2],), symbol)
                    else:
                        pairs.setdefault(head, symbol)
                elif len(tokens) == 1 and len(words[0]) >= 5:
                    # The whole name, not a rare fragment of a longer
                    # one. Five characters because shorter than that is
                    # an abbreviation somebody else also uses.
                    #
                    # ---- URBAN COMPANY, 1 August 2026 ----
                    #
                    # "len(tokens) == 1" was read as "this company's
                    # name IS one word". It is not. It is one word
                    # AFTER _NAME_SUFFIX has been removed, and COMPANY
                    # is in _NAME_SUFFIX:
                    #
                    #     INDEGENE LIMITED        -> INDEGENE   a real
                    #                                one-word name
                    #     URBAN COMPANY LIMITED   -> URBAN      an
                    #                                ADJECTIVE
                    #
                    # So URBAN entered the index as a company name, and
                    # matched ordinary English prose. Measured over all
                    # 2,967 stored messages:
                    #
                    #     genuine mentions of Urban Company    4
                    #     FALSE matches                       13
                    #
                    #     "...its position in URBAN transit technology"
                    #     "...India's URBAN infrastructure sector"
                    #     "...ahead of URBAN demand in Q1"
                    #
                    # The second one is how a Rs 900 crore Afcons order
                    # was filed against URBANCO -- a wrong-company tag
                    # on the panel he clicks BUY from, which is the one
                    # thing this project has said must never happen.
                    #
                    # THE NAME IS NOT LOST. Where suffix-stripping is
                    # what collapsed the name, the ORIGINAL first two
                    # words are indexed as a pair instead, so "Urban
                    # Company" still matches -- it just now needs both
                    # words, which is exactly what distinguishes the
                    # firm from the adjective.
                    #
                    # Why a denylist and not a rule: there is no offline
                    # dictionary here, and of the 392 solo entries only
                    # SIX are English words at all. Five of them
                    # (GOLDIAM, SUVEN, TITAN, TRENT, WELSPUN) measured
                    # 100% genuine -- DOLLAR fired 37 times, every one a
                    # real mention of Dollar Industries. Removing them
                    # would cost true matches to fix nothing. Nothing
                    # goes in this set that has not been counted first.
                    if words[0] in self._NOT_A_NAME:
                        if len(tokens_raw) >= 2:
                            pairs.setdefault(
                                (tokens_raw[0], tokens_raw[1]), symbol)
                        continue
                    solo.setdefault(words[0], symbol)
        self._names = {"pairs": pairs, "solo": solo, "triples": triples}
        return self._names

    @staticmethod
    def _like(a, b):
        """Same word, allowing for a plural either side.

        OCR drops a trailing S about as often as the master carries one
        the card does not -- "Data Pattern" against DATA PATTERNS.
        """
        return (a == b
                or (len(a) >= 4 and len(b) >= 4
                    and (a.startswith(b) or b.startswith(a))
                    and abs(len(a) - len(b)) <= 2))

    def names_in(self, text):
        """Companies named in full, whatever the capitalisation."""
        if not text:
            return []
        index = self._name_index()
        pairs, solo = index.get("pairs") or {}, index.get("solo") or {}
        triples = index.get("triples") or {}
        if not pairs and not solo and not triples:
            return []
        every = re.findall(r"[A-Za-z]{3,}", str(text).upper())
        words = [w for w in every if w not in self._NAME_SUFFIX]
        found = []
        # Pairs are matched against BOTH lists. The stripped one is the
        # original behaviour -- "Aarti Industries Ltd" reads as
        # (AARTI, INDUSTRIES) whatever punctuation sits between.
        #
        # The unstripped one exists for the names whose SECOND word is
        # itself a suffix word: URBAN COMPANY, indexed as a pair
        # precisely so the adjective alone cannot match, is invisible to
        # the stripped list because COMPANY is removed from the text as
        # well as from the name. Indexing a pair the matcher could never
        # see would have been a fix that silently did nothing -- which
        # is the failure mode this project keeps finding.
        for source in (words, every):
            for first, second in zip(source, source[1:]):
                for (a, b), symbol in pairs.items():
                    if symbol not in found and self._like(first, a) \
                            and self._like(second, b):
                        found.append(symbol)
        # THREE words, for the names whose first two are a state. See
        # _PLACE_PAIRS -- "Tamil Nadu plant" must match nothing, and
        # "Tamil Nadu Newsprint" must still match TNPL.
        if triples:
            for source in (words, every):
                for a, b, c in zip(source, source[1:], source[2:]):
                    for key, symbol in triples.items():
                        if symbol in found:
                            continue
                        if self._like(a, key[0]) and self._like(b, key[1]) \
                                and self._like(c, key[2]):
                            found.append(symbol)
        for word in words:
            symbol = solo.get(word)
            if symbol and symbol not in found:
                found.append(symbol)
        return found

    def symbols_in(self, text):
        """Which stocks a message actually names.

        Word boundaries only. "KAYNES up 5%" matches; "KAYNESX" does
        not, and neither does the "IT" in "IT sector". A mentions
        panel that is wrong is worse than no panel -- he would stop
        believing the ones that are right.
        """
        if not text:
            return []
        known = self._known_symbols()
        if not known:
            return []
        # ---- A CARD'S OWN LABELS ARE NOT COMPANY NAMES ----
        # 1 August 2026. Stored against D-Link's Q1 card:
        #
        #     symbols = DLINKINDIA, DLINKINDIA, CLEAN
        #
        # because the card prints its earnings-quality verdict as
        #
        #     EARNINGS QUALITY | CLEAN
        #
        # and CLEAN is Clean Science's real ticker, in capitals, so
        # every guard below passed it. D-Link's earnings were being
        # filed against a chemicals company.
        #
        # core/stock_events.py already stripped this before matching,
        # but it did so in ITS OWN copy of the text -- so the events
        # were right and the `symbols` column written here was wrong,
        # and the news panel reads the column. Doing it inside
        # symbols_in() means every caller gets it, which is what
        # should have happened the first time.
        try:
            from core.stock_events import _for_matching
            text = _for_matching(str(text))
        except Exception:                                  # noqa: BLE001
            pass
        # ---- AN ALL-CAPS LINE GUARD WAS TRIED HERE AND REVERTED ----
        # 1 August 2026.
        #
        # Measured on the store, a shouted line does produce false
        # links:
        #
        #     "CRUDE OIL & COMMODITIES"      -> OIL    x14
        #     "FOR CLEAN MOBILITY: CENTRE"   -> CLEAN
        #
        # so a rule was written to ignore bare words on any line with
        # no lowercase in it, keeping only hashtags. Measured BEFORE it
        # shipped: it removed 83 links across 62 messages, and most of
        # them were TRUE.
        #
        #     HFCL: SECURES AN INTERNATIONAL EXPORT
        #     DABUR: CO AIMS DOUBLE-DIGIT VOLUME
        #     WESTLIFE FOODWORLD: Q1 CONS NET PROFIT
        #     ICRA: Q1 CONS NET PROFIT 562M RUPEES VS
        #     HYUNDAI MOTOR INDIA: Q1 EBITDA 15.11B
        #
        # Day Trader Telugu writes EVERY post in capitals. The guard
        # would have silenced most of that channel to fix about fifteen
        # rows -- exactly the trade tools/telegram_resymbol.py warns
        # about: "losing a true link to fix a missing one is a bad
        # trade."
        #
        # A ticker-density test was tried to separate a shouted
        # SENTENCE from a shouted LIST. It sorted the four hand-picked
        # examples correctly and still failed on the store, because
        # "HFCL: SECURES AN INTERNATIONAL EXPORT" is one ticker in five
        # words and reads as prose by any measure. The ticker is the
        # SUBJECT of that line, and nothing about its shape says so.
        #
        # Left here as the record, so this is not tried a third time
        # without the measurement.
        # ---- A SCRIP CODE IS NOT A TICKER. 1 August 2026. ----
        #
        # Earnings 360 tags some cards with the BSE scrip code:
        #
        #     🟢 #BSE_543980 — Q1 FY27 Solid quarter...
        #     🟢 #BSE_526935 — Q1 FY27 Strong...
        #
        # The token class had no underscore, so this split into "#BSE"
        # and "543980" -- and BSE is BSE Ltd. Two other companies'
        # GREAT quarters were filed against the exchange itself, on the
        # one chip the operator had decided to trade:
        #
        #     "pls make sure these chips & related stocks are never
        #      mis matched as they are the one we trust"
        #
        # With the underscore inside the token, "#BSE_543980" is one
        # word, matches nothing, and the card is simply left unlinked
        # -- which is the honest outcome for a code we cannot resolve.
        #
        # It costs nothing real. "#M_M" stops matching too, and M&M
        # keeps its link because the card also writes "M&M" in prose,
        # which this same loop reads.
        # ---- A TICKER MAY START WITH A DIGIT. 2 August 2026. ----
        #
        #   "Earnings Pulse & Pro both uses same format #Company name.
        #    recheck & i'm 100% sure"        -- operator
        #
        # He was, and this was one of the two reasons the measurement
        # disagreed with him. The class was [A-Za-z] first, so three
        # real NSE tickers could never be tokenised at all:
        #
        #     360ONE     3MINDIA     63MOONS
        #
        # "#63MOONS.NS" and "#360ONE.NS" arrive from Breakouts with the
        # company named outright in the caption, and matched NOTHING.
        # The card was filed by guessing from the prose instead, which
        # is the failure the caption rule exists to prevent.
        #
        # A digit may now LEAD, but the token must still contain a
        # letter -- otherwise "5,33,416" off a Business Pulse table and
        # "2026" out of every date on every card become candidate
        # tickers. Three symbols is the entire population this opens,
        # and every one of them is checked against `known` below.
        # ---- A UNIT IS NOT A TICKER. 29 August 2026. ----
        #
        #     "day trader telugu posts data images after 08 am daily
        #      bulk images"                          -- operator
        #
        # Those bulk images carry macro and commodity lines, and three
        # NSE tickers are ordinary words inside them:
        #
        #     "CRUDE OIL FUTURES SETTLE AT $84.94/BBL"
        #        -> OIL     Oil India
        #        -> BBL     Bharat Bijlee, from the BARREL
        #     "NET PURCHASE OF US DOLLARS"
        #        -> DOLLAR  Dollar Industries
        #
        # The capitals guard below cannot see these -- the whole line
        # is shouted, so they read exactly like a real ticker mention.
        # And they are not harmless: since REQUIRE_A_REASON_ALWAYS, an
        # event is what makes a stock tradeable at all, so a crude
        # price quoted per barrel was giving Bharat Bijlee a reason.
        #
        # TWO NARROW RULES, both measured on the 1,525 stored messages
        # before shipping:
        #
        #     a token straight after a number and a slash is a UNIT
        #       -- /kg /Sh /BBL /share /kWh /MT /oz /ton /Litre. Only
        #          BBL is also a ticker; the rest match nothing.
        #     OIL after CRUDE, BRENT, PALM ... is a commodity, and
        #     DOLLAR after US, THE, PER ... is a currency.
        #
        # Result: 20 links removed across 16 messages -- OIL x10,
        # BBL x9, DOLLAR x1 -- and every one of them false.
        #
        # WHY IT IS THIS NARROW. The blunt version of this was tried on
        # 1 August (see the all-caps note above) and reverted: it took
        # out 83 links and most were TRUE. Masking the OCCURRENCE and
        # not the symbol keeps that from happening again -- a message
        # that says "#OIL" or "OIL INDIA: Q1 PROFIT" still links,
        # because only the unit and phrase positions are blanked.
        text = _UNIT_AFTER_NUMBER.sub(
            lambda m: " " + "x" * len(m.group(1)), str(text))
        text = _COMMODITY_OR_CURRENCY.sub(_blank_the_word, text)

        found = []
        for token in re.findall(r"#?[A-Za-z0-9][A-Za-z0-9&_\-]{2,}", str(text)):
            tagged = token.startswith("#")
            bare = token.lstrip("#")
            if not any(c.isalpha() for c in bare):
                continue
            # CAPITALS, unless it arrived as a hashtag. Third time this
            # lesson has been learned in one day:
            #
            #     "dollar"  -> DOLLAR      a textiles company, on a story
            #                              about an AI security breach
            #     "oil"     -> OIL         Oil India, on a US GDP story
            #     "Agi"     -> AGI         from garbled OCR of "& Agri"
            #
            # A ticker is written in capitals. A lowercase word that
            # happens to spell one is a word. This costs nothing real --
            # every channel here writes tickers as #TAGS or in caps --
            # and it removes a whole class of false link without a
            # blocklist that would have to grow forever.
            if not tagged and bare != bare.upper():
                continue
            upper = bare.upper()
            # ---- A NUMERIC SUFFIX IS A SCRIP CODE. AN ALPHABETIC ONE
            #      IS STILL THE COMPANY. 1 August 2026. ----
            #
            # With the underscore inside the token both of these stop
            # matching, and only one of them should:
            #
            #   #BSE_543980   a BSE SCRIP CODE. Another company's card
            #                 entirely, and it was being filed against
            #                 BSE Ltd -- twice, on a chip the operator
            #                 had decided to trade.
            #
            #   #VHLTD_RE     Viceroy Hotels' RIGHTS ENTITLEMENT, on
            #   #CGCL_RE      Viceroy's own Q1 story. Same company.
            #                 Dropping it loses a true link.
            #
            # So the suffix decides: digits are an instrument
            # identifier we cannot resolve, letters are a variant of
            # the same name.
            if upper not in known and "_" in upper:
                head, _sep, tail = upper.partition("_")
                # An EMPTY tail is a trailing underscore the OCR left
                # behind -- "-«UEL_—«=SPAUSHAKLTD" off a garbled
                # calendar image. Requiring a suffix to exist dropped
                # UEL for no reason at all.
                if head in known and not tail.isdigit():
                    upper = head
            if upper in known and upper not in found:
                found.append(upper)
        return found

    def _read_photo(self, url, data=None):
        """The words inside one forwarded screenshot.

        Two sources, one cache. The WEB reader gives a CDN URL and the
        bytes are fetched; the TELEGRAM API gives the bytes directly,
        because a photo behind the API has no public URL at all.
        core/image_text.read() has always taken bytes -- read_url() is
        just read(fetch(url)) -- so the difference is one branch, not a
        second OCR path.

        Cached by URL for the life of the process: the poller re-reads
        the same recent messages every 90 seconds, and OCR is the one
        genuinely expensive thing in this loop.

        Failures are counted, not raised, and the count is what
        status() reports -- "the reader is not installed" and "the
        reader is installed and reading nothing" must not look the same.
        """
        if not url and data is None:
            return ""
        if url and url in self._ocr_cache:
            return self._ocr_cache[url]
        try:
            from core import image_text
            if not image_text.available():
                if url:
                    self._ocr_cache[url] = ""
                return ""
            if data is None and url:
                data = image_text.fetch(url)
            text = image_text.read(data)
            # ---- KEEP THE WORD POSITIONS TOO. 2 August 2026. ----
            #
            #     "make sure the ocr is working properly what if i
            #      didn't asked you to tell me what our bot will do
            #      this image? we never know right"
            #
            # TOMORROW'S CALENDAR is a grid of logos and Tesseract
            # walks it column by column, so the flat transcript put
            # NINE stocks that report while the market is open into the
            # after-the-close bucket. The y-coordinate does not care
            # what order anything was read in -- see
            # core/recap_card.rows_from_grid().
            #
            # Cached beside the text and bounded the same way. Costs
            # nothing extra: image_to_data runs the same recognition
            # pass image_to_string already did.
            try:
                self._ocr_boxes[url or id(data)] = \
                    image_text.words_with_positions(data)
            except Exception:                              # noqa: BLE001
                pass
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[TELEGRAM] Image read failed: {exc}")
            text = ""
        if not text:
            self._ocr_misses += 1
        # Cache is bounded -- this process can run for a week.
        if len(self._ocr_cache) > 500:
            self._ocr_cache.clear()
            self._ocr_boxes.clear()
        self._ocr_cache[url] = text
        return text

    # ------------------------------------------------------------

    def poll(self, limit=DEFAULT_LIMIT, stop_check=None, fast=None):
        """Fetch recent messages from every channel.

        One channel failing costs that channel only. Never raises --
        a chat feed must not be able to stop a trading session.

        ---- CTRL+C HAD NOTHING TO INTERRUPT. 3 August 2026. ----

            "py tools/collector.py is not closing in from 1st run. i
             tried to close ctrl+c"

        The collector sets a flag on Ctrl+C and checks it BETWEEN
        passes. One pass is nine channels with OCR on every image, so
        the flag sat unread for minutes while the terminal ignored him.
        Nothing was hung; nothing was listening either.

        `stop_check` is asked before each channel. A pass abandoned
        halfway costs nothing -- every message is committed as it is
        stored, and the next run picks up from the last id.

        `fast` limits the pass to the channels that post through
        the session -- everything except SLOW_KINDS. None reads all of
        them. See start() for why that exists.
        """
        if self.client is None:
            self._last_error = ("no Telegram client -- run "
                                "py tools/telegram_setup.py")
            return 0

        started = datetime.now()
        stored = 0
        for channel in self._channels_for(fast):
            if stop_check is not None and stop_check():
                decision(f"[TELEGRAM] Stopping mid-pass. {stored} message(s) "
                         f"already saved.")
                break
            handle = channel["handle"]

            # ---- ASK ONLY FOR WHAT CAME AFTER. 30 August 2026. ----
            #
            #     "the only issue i observed is bot looking back on
            #      already stored info & re processing them, thats the
            #      reason i asked to maintain the time stamps on all
            #      channels ... collector must check from that channel
            #      after 30/08/2026 07:20:06 not before that time"
            #                                        -- the operator
            #
            # Each channel carries its own mark, so a quiet channel
            # and a busy one are each resumed from their own last
            # post rather than from a shared clock.
            #
            # The id, not the timestamp, is what is sent. They mean
            # the same thing here -- Telegram ids rise with time
            # within a channel -- but the id is exact, while a
            # timestamp has to be compared across two clocks and ties
            # inside the same second are ambiguous. His 07:20:05
            # picture and its id are the same boundary; the id cannot
            # be off by a second.
            #
            # The skip in _store() still stands behind this. This
            # stops the post ARRIVING; that stops it being written.
            # The web-view fallback has no server-side filter, so on
            # that path the skip is the only guard -- which is why
            # both exist.
            since_id = self._newest_stored_id(
                channel.get("name") or handle)
            # The retry is NESTED, not a sibling clause. Raised from
            # inside an `except TypeError:` handler, a dead channel's
            # error would escape the `except Exception` below and end
            # the whole pass -- which is exactly what
            # test_one_dead_channel_does_not_cost_the_others caught.
            try:
                try:
                    messages = self.client.fetch(handle, limit=limit,
                                                 since_id=since_id) or []
                except TypeError:
                    # An older or stubbed reader without the argument.
                    # Losing the channel because we asked it something
                    # new is a far worse trade than reading a page
                    # twice.
                    messages = self.client.fetch(handle, limit=limit) or []
            except Exception as exc:                       # noqa: BLE001
                warn(f"[TELEGRAM] {handle}: {exc}")
                self._last_error = f"{handle}: {exc}"
                self._note_attempt(channel, ok=False, error=exc)
                continue
            # A read that WORKED, even if it brought nothing back. This
            # is what lets the board tell a quiet channel from an
            # unreadable one -- see core/feed_clock.note_attempt().
            self._note_attempt(channel, ok=True)
            stored += self._store(channel, messages)

        self._last_poll_at = datetime.now()
        if stored:
            decision(f"[TELEGRAM] {stored} new message(s) across "
                     f"{len(self.channels)} channels.")
            self._report_lag(started)
        self._prune()
        return stored

    def _report_lag(self, since):
        """Say how late this pass's messages were. Never raises.

        ---- IT KNEW AND NEVER SAID. 29 August 2026. ----
        Every row carries `at` (posted on the channel) and `seen_at`
        (stored by us), and core/feed_clock.py's own note says the
        difference is pure collection lag. Nothing ever read it. The
        5.7-minute median and the 21.5-minute p90 that split the
        poller into two loops were measured by hand, off the store,
        weeks after the fact.

        A number nobody looks at is a number nobody acts on. So the
        bot now says it after every pass that stored something, and
        says it LOUDLY when a message was late enough to have cost a
        move -- SLOW_FEED_WARN_MINUTES.

        This is also the only way to know whether the two-loop split
        worked. It could not be measured offline; the client only
        exists in a live session.
        """
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                rows = conn.execute(
                    "SELECT channel, at, seen_at FROM messages "
                    "WHERE seen_at >= ?",
                    (since.isoformat(timespec="seconds"),)).fetchall()
                conn.close()
            lags = []
            worst = None
            for channel, at, seen_at in rows:
                posted = _as_ist(at)
                seen = _as_ist(seen_at)
                if not posted or not seen:
                    continue
                minutes = (seen - posted).total_seconds() / 60.0
                # ---- A BACKFILL IS NOT A LAG. ----
                # The bot was off on 28 August; when it came back it
                # stored 227 messages posted the day before. Measured
                # naively that reads as a 1,440-minute delay and fires
                # a warning about a feed that is working perfectly.
                #
                # A poll delay cannot cross a date and cannot outlast
                # a couple of hours -- the loop runs every 90 seconds.
                # Anything else is catching up, and counting it would
                # make the median meaningless on exactly the mornings
                # it matters.
                if minutes < 0 or minutes > CATCH_UP_MINUTES:
                    continue
                if posted.date() != seen.date():
                    continue
                lags.append(minutes)
                if worst is None or minutes > worst[0]:
                    worst = (minutes, channel)
            if not lags:
                return
            lags.sort()
            middle = lags[len(lags) // 2]
            self._lags.extend(lags)
            if worst and worst[0] >= SLOW_FEED_WARN_MINUTES:
                warn(f"[TELEGRAM] {worst[1]} was {worst[0]:.0f} minutes "
                     f"behind -- posted before the bot could see it. "
                     f"This pass: {middle:.1f} min median over "
                     f"{len(lags)} message(s).")
            else:
                diagnostic(f"[TELEGRAM] lag {middle:.1f} min median over "
                           f"{len(lags)} new message(s).")
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[TELEGRAM] could not measure lag ({exc}).")

    @staticmethod
    def _note_attempt(channel, ok=True, error=None):
        """Bookkeeping only. Never allowed to break a pass."""
        try:
            from core.feed_clock import note_attempt
            note_attempt(channel, ok=ok, error=error)
        except Exception:                                  # noqa: BLE001
            pass

    def channel_report(self):
        """One row per channel, for the Telegram tab. Never raises.

            "yes even i felt that . show me in another tab named
             Telegram, under this tab create a data structure for all
             channels (currently -10 channels) & display"
                                        -- operator, 30 August 2026

        Everything here was already on disk and reached no screen. He
        has asked twice what the bot last heard and from where, and
        both times the answer had to be dug out of SQLite by hand.

        ONE query for all ten channels, not one each -- this is built
        on a dashboard cycle and there is a websocket feed waiting on
        it.

        "late by" is measured on the LATEST message, not across the
        day. A median would be an average of unlike things -- a
        backfilled weekend and a live morning tick in one number --
        and it would hide the only reading that matters, which is how
        late the last thing to arrive was.
        """
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT channel, COUNT(*) AS held, MAX(at) AS last_post, "
                    "SUM(CASE WHEN photos IS NOT NULL AND photos != '' "
                    "         THEN 1 ELSE 0 END) AS pictures, "
                    "SUM(CASE WHEN ocr_text IS NOT NULL AND ocr_text != '' "
                    "         THEN 1 ELSE 0 END) AS read_back, "
                    "SUM(CASE WHEN symbols IS NOT NULL AND symbols != '' "
                    "         THEN 1 ELSE 0 END) AS named "
                    "FROM messages GROUP BY channel").fetchall()
                held = {r["channel"]: dict(r) for r in rows}
                # The newest message's own pair of stamps, which is
                # what "late by" is measured on.
                for name in list(held):
                    got = conn.execute(
                        "SELECT at, seen_at FROM messages WHERE channel = ? "
                        "ORDER BY at DESC LIMIT 1", (name,)).fetchone()
                    if got:
                        held[name]["last_post"] = got["at"]
                        held[name]["last_read"] = got["seen_at"]
                # How the LAST READ went, which the messages table
                # cannot say -- a channel with no new posts and a
                # channel we could not reach look identical in it.
                try:
                    for row in conn.execute(
                            "SELECT channel, last_try_ist, last_error, "
                            "last_error_ist FROM feed_watermark").fetchall():
                        entry = held.setdefault(row["channel"], {})
                        entry["last_try"] = row["last_try_ist"]
                        entry["last_error"] = row["last_error"]
                        entry["last_error_at"] = row["last_error_ist"]
                except sqlite3.Error:
                    pass                    # older store, no columns yet
                conn.close()
        except Exception:                                  # noqa: BLE001
            held = {}

        try:
            fast = {(c.get("name") or c.get("handle"))
                    for c in self._channels_for(fast=True)}
        except Exception:                                  # noqa: BLE001
            fast = set()
        try:
            in_season = self._results_matter_today()
        except Exception:                                  # noqa: BLE001
            in_season = False

        out = []
        for entry in self.channels:
            name = entry.get("name") or entry.get("handle")
            row = dict(held.get(name) or {})
            try:
                from core.feed_clock import channel_kind
                role = channel_kind(entry.get("handle")) or "other"
                if role == "other":
                    role = channel_kind(name) or "other"
            except Exception:                              # noqa: BLE001
                role = "other"

            quick = name in fast
            late = self._late_by(row.get("last_post"), row.get("last_read"))
            out.append({
                "name": name,
                "handle": entry.get("handle"),
                "role": role,
                "quick": quick,
                "loop_seconds": POLL_SECONDS if quick else SLOW_POLL_SECONDS,
                "last_post": row.get("last_post"),
                "last_read": row.get("last_read"),
                "late_minutes": late,
                "held": row.get("held") or 0,
                "pictures": row.get("pictures") or 0,
                "pictures_read": row.get("read_back") or 0,
                "named_a_stock": row.get("named") or 0,
                "last_try": row.get("last_try"),
                "last_error": row.get("last_error"),
                "state": self._channel_state(role, in_season, row, late,
                                             row.get("last_post")),
            })
        return out

    @staticmethod
    def _late_by(posted, stored):
        """Whole minutes between posting and storing, or None.

        Negative readings are dropped rather than shown. They mean the
        two stamps came off different clocks, and a screen that says
        "-3 minutes late" teaches him to distrust the column.
        """
        if not posted or not stored:
            return None
        try:
            from core.feed_clock import to_ist
            a, b = to_ist(posted), to_ist(stored)
            if a is None or b is None:
                return None
            gap = int((b - a).total_seconds() // 60)
        except Exception:                                  # noqa: BLE001
            return None
        return gap if gap >= 0 else None

    # A lag measured on a message that arrived days ago describes
    # that day, not this one. Past this the channel is simply quiet.
    STALE_STATE_HOURS = 6.0

    @staticmethod
    def _channel_state(role, in_season, row, late, last_post=None):
        """One word for the right-hand column.

        A results channel silent in September is not a fault, and
        saying so would train him to ignore the column on the morning
        it IS one. See core/feed_clock.expected_today(), which has
        made the same distinction since it was written.

        ---- A STALE LAG IS NOT A LATE CHANNEL. 30 August 2026. ----

        First run against the real store, on a Sunday evening:

            Breakouts         last post 28 Aug 10:03   late 1043   LATE
            OrderBook Pulse   last post 29 Aug 15:59   late  126   LATE

        Both readings were true and neither was a fault to act on.
        1,043 minutes is what a backfill looks like, and 126 minutes
        was Friday evening's collection lag. He would have opened the
        board on Monday to two red flags describing last week.

        So "late" now means the channel has posted RECENTLY and that
        post was slow to reach us -- which is the only version of late
        he can do anything about. The number itself stays in its own
        column either way, so nothing is hidden.
        """
        # ---- UNREADABLE IS NOT QUIET. 31 August 2026. ----
        #
        #     "if channel not posted then no error & if channel posted
        #      but bot struck at different time stamp then it must
        #      fetch after that time stamp data"   -- the operator
        #
        # This read the same for a channel that published nothing and
        # one the bot could not reach. Earnings 360 showed "quiet" while
        # it had not been successfully read for two days -- and it is a
        # RESULTS channel, so from 15 October it is on the fast loop and
        # carrying the most time-critical thing the bot reads.
        #
        # Checked FIRST, before role and before season: a results
        # channel that cannot be read in October must not be excused as
        # "off season".
        if row.get("last_error"):
            return "unreadable"
        if not row.get("held"):
            return "nothing yet"
        if role == "results" and not in_season:
            return "off season"
        if role == "episodic":
            return "quiet"

        stale = False
        if last_post:
            try:
                from core.feed_clock import to_ist
                when = to_ist(last_post)
                if when is not None:
                    if getattr(when, "tzinfo", None) is not None:
                        when = when.replace(tzinfo=None)
                    hours = (datetime.now() - when).total_seconds() / 3600.0
                    stale = hours > TelegramFeed.STALE_STATE_HOURS
            except Exception:                              # noqa: BLE001
                stale = False
        if stale:
            return "quiet"

        # `late` is passed IN. Reading it off the database row was
        # the first version, and the row does not carry it -- so the
        # column could never say "late" at all. OrderBook Pulse was
        # 126 minutes behind and reading "live".
        if late is not None and late > SLOW_FEED_WARN_MINUTES:
            return "late"
        return "live"

    def lag_summary(self):
        """Posted-to-stored lag for the session. {} until something
        has arrived. Read by the close-of-session score."""
        got = sorted(self._lags)
        if not got:
            return {}
        return {"messages": len(got),
                "median_min": round(got[len(got) // 2], 1),
                "p90_min": round(got[int(len(got) * 0.9)], 1),
                "worst_min": round(got[-1], 1)}

    # Only these are held back to the slow pass. Everything else --
    # including a channel nobody has classified yet -- is read on the
    # fast one.
    #
    # ---- THE DEFAULT WAS THE WRONG WAY ROUND. 29 August 2026. ----
    # This first selected FOR "daily", which is OrderBook Pulse, Day
    # Trader Telugu and RedboxGlobal India. News Pulse is none of those
    # -- channel_kind() calls it "other" -- so it landed on the five
    # minute loop while posting news all day, 109 messages in the
    # 18-29 August sample. He spotted it immediately: "telegram
    # channels are still getting news, orderbook, business updates."
    #
    # An unclassified channel is one nobody has looked at, not one
    # known to be quiet. Reading it too often costs a few seconds;
    # reading it too rarely costs a trade. So the slow list is the
    # SHORT, EXPLICIT one, and the fast loop takes everything else.
    SLOW_KINDS = ("results", "episodic")

    def _next_limit(self):
        """How many messages to ask each channel for on this pass.

        ---- NOTHING COLLECTS WHILE THE MARKET IS SHUT. 29 Aug 2026 ----

            "in telegram last i saw one info at 21:29"    -- operator

        The store's last row that evening was 18:09. main.py exits on a
        non-trading day -- "Nothing to do -- exiting" -- and the
        collector goes with it, so everything posted between Friday
        evening and Monday morning arrives only when the next session
        starts and the first pass reaches back for it.

        Thirty was not far enough to reach. Counted on the store,
        between a Friday 18:00 and the Monday 09:15 after it:

            14-17 August   Earnings Pulse   42 messages
            21-24 August   Earnings Pulse    1

        Forty-two against a limit of thirty means the twelve OLDEST --
        Friday evening's, the ones that decide Monday's gaps -- were
        the ones dropped.

        So the first pass of a process asks for FIRST_PASS_LIMIT and
        every pass after it goes back to the ordinary number, because
        nothing posted since the last pass can be more than ninety
        seconds old. Same shape as the announcement watcher's deep
        first pass, and for the same reason.

        t.me/s/ decides how much it will actually return; asking for
        more is not a promise of getting it.
        """
        if self._first_pass_done:
            return DEFAULT_LIMIT
        self._first_pass_done = True
        decision(f"[TELEGRAM] First pass of this run -- asking each channel "
                 f"for {FIRST_PASS_LIMIT} messages to cover the time the "
                 f"collector was not running.")
        return FIRST_PASS_LIMIT

    def _channels_for(self, fast=None):
        """Channels in poll order. All of them unless `fast` is True.

        fast=True  everything except SLOW_KINDS -- the channels that
                   post through the session, plus anything unclassified
        fast=None  every channel

        Falls back to every channel whenever the kind cannot be
        resolved. A pass that reads too much is a slow pass; a pass
        that reads nothing is a blind one.
        """
        # ==============================================================
        # A YOUTUBE CHANNEL AT THE WEEKEND.  5 September 2026.
        # ==============================================================
        #
        #     "daytrader telugu needs to be avoided on weekends & links
        #      they are posting"
        #     "they will be posting their youtube links all weekends"
        #                                          -- the operator
        #
        # On a Saturday that channel is not a market feed. From his own
        # store, the same evening:
        #
        #     post 208202  "మీకు SBI ACC ఉందా ?🤩 శుభవార్త
        #                   https://youtube.com/shorts/..."
        #     STOCKS FOUND: ACC
        #
        # "ACC" inside the Telugu word for ACCOUNT matched ACC Ltd, the
        # cement company, and a YouTube promotion became a published
        # reason. That is not a cosmetic fault: a published reason is
        # MANDATORY before the ranker will evaluate a stock at all, so
        # this does not sit harmlessly on a panel -- it opens the door.
        #
        # Skipped on Saturday and Sunday only. NOT a rule about
        # collecting at the weekend in general: the weekend is exactly
        # when the gaps form, and every other channel must keep being
        # read. This is about what THIS channel publishes on those two
        # days, which he watches and I do not.
        weekend = datetime.now().weekday() >= 5
        channels = self.channels
        if weekend:
            kept = [c for c in channels
                    if "daytrader" not in
                    f"{c.get('handle') or ''}{c.get('name') or ''}"
                    .lower().replace(" ", "")]
            if kept:                       # never empty the list
                channels = kept
        if not fast:
            return list(channels)
        try:
            from core.feed_clock import channel_kind

            in_season = self._results_matter_today()
            picked = []
            for entry in channels:
                kinds = {channel_kind(entry.get(key))
                         for key in ("handle", "name")}
                if kinds & set(self.SLOW_KINDS):
                    # ---- IN SEASON THE RESULTS CHANNELS LEAD. ----
                    #      30 August 2026.
                    #
                    #     "bot must follow the NSE calendar - follow
                    #      results period . (only that time bot
                    #      prioritizes the result channels from
                    #      telegram too)"          -- the operator
                    #
                    # "results" was in SLOW_KINDS unconditionally, so
                    # Earnings Pulse, Earnings 360 and Earnings Pro sat
                    # on the five minute loop on 14 August -- the Q1
                    # deadline, the single busiest filing day of the
                    # quarter -- for exactly the same reason they sit
                    # there on a quiet Tuesday in September.
                    #
                    # core/results_calendar.in_results_season() has
                    # known the answer since it was written. Only
                    # core/feed_clock.py ever asked it, and only to
                    # decide whether a quiet channel was a fault.
                    if "results" in kinds and in_season:
                        picked.append(entry)
                    continue
                picked.append(entry)
            # The fallback keeps the weekend rule: falling back to
            # `channels` rather than self.channels means an
            # unresolvable channel kind cannot quietly put Day Trader
            # Telugu's Saturday YouTube posts back on the list.
            return picked or list(channels)
        except Exception:                                  # noqa: BLE001
            return list(channels)

    def _results_matter_today(self, day=None):
        """Should the results channels be read on the fast loop?

        Two ways to say yes, because neither alone is enough:

            in_results_season()   the SEBI Regulation 33 windows --
                                  the four weeks running up to each
                                  deadline, which is when the bulk
                                  files. 14 August yes, 24 August no.
            symbols_on(day)       a straggler reporting OUTSIDE the
                                  window. One company is scheduled for
                                  31 August 2026; the window closed on
                                  the 14th.

        False on any failure. Being slow on the results channels out
        of season is the behaviour that has shipped for weeks; being
        wrong about the date must not make the pass blind.
        """
        try:
            from core.results_calendar import in_results_season
            if in_results_season(day):
                return True
        except Exception:                                  # noqa: BLE001
            return False
        try:
            from core.results_calendar import ResultsCalendar
            return bool(ResultsCalendar().symbols_on(day))
        except Exception:                                  # noqa: BLE001
            return False

    # ------------------------------------------------------------
    # keeping it CURRENT
    # ------------------------------------------------------------

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
    # It was asking, every 90 seconds, of every channel, whether or not
    # anything had been published. He is right that Telegram will tell
    # us instead: NewMessage rides on the connection that is already
    # open, and a post arrives the moment it is published rather than
    # up to 90 seconds later. For the three channels where "delay in
    # getting their data into bot will cost us money", that is the
    # whole of the lag -- measured 18-29 August, Day Trader Telugu's
    # median was 5.5 minutes and its p90 24.9.
    #
    # THE POLLING STAYS, and this is not belt-and-braces for its own
    # sake. Telegram pushes to a client that is CONNECTED and queues
    # nothing for one that is not. A dropped socket, a laptop lid, a
    # DNS blink -- and everything published in the gap is simply never
    # sent. poll(), catch_up() and fill_gaps() are what make a restart
    # whole, and none of them is touched. Push is the fast path; the
    # poll is the floor.

    def _store_pushed(self, handle, record):
        """One post, pushed by Telegram, into the store.

        Never raises. This runs inside telethon's event loop, and an
        exception escaping here would take the loop down -- and with it
        the polling that is supposed to be the safety net.
        """
        try:
            channel = None
            for c in self.channels:
                names = {str(c.get("handle") or "").lstrip("@").lower(),
                         str(c.get("name") or "").lower()}
                if str(handle or "").lower() in names:
                    channel = c
                    break
            if channel is None:
                # A channel that pushed but is not on the list. Storing
                # it under a name nothing else uses would make a row
                # that no panel and no matcher ever reads.
                diagnostic(f"[PUSH] {handle}: not a watched channel, "
                           f"ignored")
                return 0
            stored = self._store(channel, [record])
            if stored:
                self._pushed += stored
                decision(f"[PUSH] {channel.get('name') or handle}: "
                         f"a new post arrived")
            return stored
        except Exception as exc:                           # noqa: BLE001
            warn(f"[PUSH] Could not store a pushed post ({exc}). "
                 f"The poll will pick it up.")
            return 0

    def pushed_count(self):
        """How many posts Telegram has PUSHED this run.

        Zero after an hour of market open means the listener is not
        delivering and the polling is carrying the whole feed -- which
        works, and is slower, and should not be discovered by accident.
        A counter nothing reads is a counter that proves nothing, so
        this is the reader.
        """
        return int(getattr(self, "_pushed", 0) or 0)

    def listen(self):
        """Ask Telegram to push new posts. Returns how many channels.

        Zero is a normal answer, not a failure: the web-view reader
        cannot push, and neither can a stub. The caller falls back to
        an ordinary sleep and everything still works, more slowly.
        """
        watch = getattr(self.client, "watch", None)
        if watch is None:
            return 0
        handles = [c.get("handle") or c.get("name") for c in self.channels
                   if (c.get("handle") or c.get("name"))]
        try:
            n = watch(handles, self._store_pushed) or 0
        except Exception as exc:                           # noqa: BLE001
            warn(f"[PUSH] Could not start listening ({str(exc)[:70]}). "
                 f"Polling only.")
            return 0
        if n:
            decision(f"[PUSH] Telegram will push new posts from {n} "
                     f"channel(s) as they are published. Polling "
                     f"continues behind it.")
        return n

    def start(self, every_seconds=POLL_SECONDS):
        """Poll the channels on a background thread until stop().

        WHY THIS EXISTS -- found live on 30 July 2026, hours into a
        session. main.py called telegram.poll() exactly ONCE, during
        setup, and never again. data/telegram.db was last written at
        09:02:59 and the panel showed 08:59's messages for the rest of
        the day.

        That threw away the entire point of these channels. Earnings
        Pulse posts "#HEXT - OK Results - 13 seconds ago"; OrderBook
        Pulse posts an order win minutes after the filing. Reading them
        once, BEFORE the market opens, means every filing, results post
        and order that landed during the session was never fetched.

        The bug was invisible in the obvious place: the startup log said
        "14 new message(s) across 4 channels", which is a success line.
        Nothing ever said "and that was the only time I looked".

        Own daemon thread, never the tick path -- same posture as
        core/announcement_watcher.py. A failed poll costs one cycle and
        the previous messages stay on screen; it can never block a trade
        or stop the loop.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        # ---- THE DAILY THREE WERE WAITING FOR THE OTHER SEVEN ----
        #      29 August 2026.
        #
        #     "fix the telegram collector delay"      -- operator
        #
        # This loop was `wait(90s) -> poll() -> wait(90s)`, and poll()
        # walked EVERY channel with OCR on every image. So the cycle was
        # never 90 seconds -- it was 90 plus the length of a full pass.
        #
        # Ordering the daily three first (24 August) did not fix it, and
        # the measurement says so: over 18-29 August their median lag
        # from posted to stored was still 5.5 minutes, p90 24.9. Being
        # read first in a pass does not help when you still wait for the
        # PREVIOUS pass to finish walking seven channels you do not need.
        #
        #     Day Trader Telugu   958 messages   median 5.5m   p90 24.9m
        #     Breakouts           240            median 5.5m   p90  9.4m
        #     RedboxGlobal        171            median 5.6m   p90 12.9m
        #
        # His rule for those three, from 24 August: "delay in getting
        # their data into bot will cost us money."
        #
        # So they get their own loop at `every_seconds`, and the rest --
        # episodic and results-season channels he has told me are not
        # owed a post on a schedule -- get a slower one. The daily cycle
        # is now 90s plus THREE channels instead of 90s plus ten.
        #
        # Two threads, both daemon, both fail-quiet. A failed pass on
        # either costs one cycle; neither can block the other, because
        # sqlite3 serialises the writes and every message is committed
        # as it is stored.
        slow = max(int(every_seconds), int(SLOW_POLL_SECONDS))

        # ---- ONE THREAD, BECAUSE THE LOOP CAN ONLY HAVE ONE OWNER ----
        #                                       5 September 2026.
        #
        # This was two threads calling poll() on the same telethon
        # client. That works for ask-and-answer calls -- telethon's sync
        # wrapper serialises them onto its own event loop, and no error
        # about it has ever been recorded on any channel.
        #
        # It stops working the moment anything HOLDS that loop, which is
        # exactly what listening for pushed messages does. Two owners
        # and a held loop is "this event loop is already running", on
        # the path that feeds the ranker.
        #
        # So the two loops become one, and the wait between polls
        # becomes a wait that LISTENS -- pump(). The thread was going to
        # sleep for 90 seconds anyway; now Telegram delivers during
        # those 90 seconds and the client is free again when they are
        # up. Same cadence, same safety net, nothing new blocked.
        #
        # The slow channels keep their own cadence by counting cycles
        # rather than by having their own thread: every `slow` seconds
        # of elapsed time, one pass includes them. Their reason is
        # unchanged -- they are episodic and results-season channels he
        # has said are not owed a post on a schedule, and walking all
        # ten every 90 seconds is what made the daily three wait.
        def _loop():
            watching = self.listen()
            last_full = time.monotonic()
            while not self._stop.is_set():
                # The wait, and it listens if it can. pump() returns
                # False when push is unavailable or the connection is
                # down -- and False must never become a busy loop, so
                # the ordinary wait runs instead.
                waited = False
                if watching:
                    try:
                        waited = bool(self.client.pump(every_seconds))
                    except Exception as exc:               # noqa: BLE001
                        diagnostic(f"[PUSH] listening cycle ended "
                                   f"({str(exc)[:60]})")
                        waited = False
                if not waited and self._stop.wait(every_seconds):
                    break
                if self._stop.is_set():
                    break
                due_full = (time.monotonic() - last_full) >= slow
                try:
                    self.poll(fast=(None if due_full else True),
                              limit=self._next_limit())
                    if due_full:
                        last_full = time.monotonic()
                except Exception as exc:                   # noqa: BLE001
                    warn(f"[TELEGRAM] poll cycle failed ({exc}) -- keeping "
                         f"what is already held, retrying in "
                         f"{every_seconds}s.")

        self._thread = threading.Thread(target=_loop, name="telegram-feed",
                                        daemon=True)
        self._thread.start()
        decision(f"[TELEGRAM] Watching the daily channels every "
                 f"{every_seconds}s, all channels every {slow}s.")

    def stop(self):
        """Stop both pollers. Safe to call when they were never started."""
        self._stop.set()
        for attr in ("_thread", "_slow_thread"):
            thread = getattr(self, attr, None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=3)
            setattr(self, attr, None)

    def poller_alive(self):
        """True if the background poll loop is running -- so the
        dashboard can say so instead of showing stale rows as if they
        were current."""
        return bool(self._thread is not None and self._thread.is_alive())

    def _channels_from_store(self, db_path=None):
        """Every channel that has actually delivered, from the store.

        `db_path` is a parameter because __init__ calls this BEFORE it
        assigns self.db_path. Defaulting to the attribute keeps every
        later caller working.

        For a READ-ONLY view (client=None). core/feed_clock.py's
        feed_watermark table is written by the collector as it polls,
        one row per channel, so it is the honest answer to "which
        channels does this bot watch" without asking Telegram --
        these are the ones that have really posted, not the ones
        subscribed to.

        Never raises and never blocks on the collector: opened
        read-only with a short timeout, and an unreadable store simply
        means no extra channels. See the note in __init__ for why this
        exists at all.
        """
        path = db_path or getattr(self, "db_path", None)
        if not path:
            return []
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro",
                                   uri=True, timeout=2.0)
        except Exception:                                   # noqa: BLE001
            return []
        try:
            rows = conn.execute(
                "select channel from feed_watermark "
                "where channel is not null and channel != '' "
                "order by channel").fetchall()
            return [r[0] for r in rows]
        except Exception:                                   # noqa: BLE001
            # No watermark table yet -- a first run, or an old store.
            return []
        finally:
            try:
                conn.close()
            except Exception:                               # noqa: BLE001
                pass

    def _stored_ocr(self, channel_name):
        """{message_id: ocr_text} for what this channel already holds.

        The transcripts were always written; nothing ever read them
        back, so every restart paid OCR again on pictures it had
        already read. See _store(). Empty on any error -- re-reading a
        picture is slow, not wrong.
        """
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                rows = conn.execute(
                    "SELECT message_id, ocr_text FROM messages "
                    "WHERE channel = ? AND ocr_text IS NOT NULL "
                    "AND ocr_text != ''", (channel_name,)).fetchall()
                conn.close()
            return {str(mid): text for mid, text in rows}
        except Exception:                                  # noqa: BLE001
            # Same reasoning as _newest_stored_id below: this reaches
            # for self._lock and self.db_path, so it can fail for more
            # than sqlite3's reasons, and its own docstring already
            # says re-reading a picture is slow rather than wrong.
            return {}

    def _newest_stored_id(self, channel_name):
        """The highest post id we already hold for one channel, as an
        int, or None. The stop signal for the catch-up walk."""
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                row = conn.execute(
                    "SELECT MAX(CAST(message_id AS INTEGER)) FROM messages "
                    "WHERE channel = ?", (channel_name,)).fetchone()
                conn.close()
            return int(row[0]) if row and row[0] is not None else None
        except Exception:                                  # noqa: BLE001
            # ---- AN OPTIMISATION MUST NOT BE ABLE TO COST A ----
            #      CHANNEL. 30 August 2026.
            #
            # This listed the three errors it expected, which was fine
            # while only catch_up() called it. poll() now calls it for
            # every channel on every pass, so anything it raises would
            # take that channel down -- and tests/test_collector_
            # stops.py found the fourth error immediately: a feed built
            # without __init__ has no _lock, and AttributeError was not
            # on the list.
            #
            # Not knowing the mark means reading a page we may already
            # hold. That is slower. Losing the channel is wrong.
            return None

    # ==============================================================
    # NOTHING MISSED -- THE HOLES, BY NAME.  5 September 2026.
    # ==============================================================
    #
    #     "for me all info must be tagged properly & never mis ,
    #      duplicate , thats it"                      -- the operator
    #
    # Counted on the store that morning: 183 posts published and never
    # collected. Every long run of them was a weekend --
    #
    #     RedboxGlobal India   76 missing   29 Aug 11:04 -> 31 Aug 18:07
    #     Earnings 360         10 missing   26 Aug 07:56 -> 27 Aug 07:10
    #     Earnings Pro          9 missing   26 Aug 07:35 -> 27 Aug 07:10
    #     Earnings Pulse        7 missing   26 Aug 03:38 -> 27 Aug 10:08
    #
    # -- the laptop off from Saturday to Monday, and catch_up() unable
    # to close a hole that sits BELOW the newest id it holds. It walks
    # backwards and stops after two pages that add nothing, and the page
    # on either side of a weekend hole is ground already held, so it
    # stopped every time with the hole still open. Four weeks of that.
    #
    # A page walk cannot ask the question. This can: the store knows it
    # holds 3711 and 3788 and nothing between, so it asks for 3712..3787
    # by name. One request, up to a hundred posts, nothing walked past.

    def missing_ids(self, channel_name, within_hours=None, cap=200):
        """Post ids published on this channel that were never collected.

        A hole is a run of numbers between two posts we DO hold. Only
        holes inside the retention window are reported: `_prune()` keeps
        `keep_hours`, and fetching a post that the same run deletes
        would be work done to throw away.

        Ids already asked for three times are left out -- see the
        gap_attempts note in _ensure_db().
        """
        window = self.keep_hours if within_hours is None else within_hours
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                rows = conn.execute(
                    "SELECT CAST(message_id AS INTEGER), at FROM messages "
                    "WHERE channel = ? AND message_id IS NOT NULL "
                    "ORDER BY 1", (channel_name,)).fetchall()
                try:
                    spent = {int(r[0]) for r in conn.execute(
                        "SELECT message_id FROM gap_attempts "
                        "WHERE channel = ? AND tries >= 3",
                        (channel_name,))}
                except sqlite3.Error:
                    spent = set()
                conn.close()
        except Exception:                                  # noqa: BLE001
            # Not knowing the holes means not filling them this run.
            # It must never mean losing the channel.
            return []

        # core/feed_clock.to_ist() is the ONE converter in this codebase
        # and the reason is written out beside _all_older_than(): the
        # stored stamps carry "+00:00", and an arm that discards the
        # offset instead of applying it makes a live feed look five and
        # a half hours stale. Naive after, because the cutoff is naive.
        cutoff = datetime.now() - timedelta(hours=window)
        held = []
        for mid, at in rows:
            if mid is None:
                continue
            try:
                from core.feed_clock import to_ist
                moment = to_ist(at)
                when = None if moment is None else moment.replace(tzinfo=None)
            except Exception:                              # noqa: BLE001
                when = None
            held.append((int(mid), when))
        held.sort()

        # ---- A HOLE THIS CHANNEL COULD NOT HAVE PUBLISHED IS ----
        #      NOT A HOLE. 5 September 2026.
        #
        # Two holes, both real numbers, one of them meaningless:
        #
        #   RedboxGlobal India   76 ids over 55 hours   346 posts on file
        #   WLPulseBot           57 ids over 33 hours     3 posts on file
        #
        # The first is a weekend. RedboxGlobal publishes about 43 posts
        # a day, so 55 hours of silence should hold roughly a hundred --
        # 76 fits, and every one of them is a post the bot never read.
        #
        # The second is not a gap at all. @WLPulseBot is a BOT, and a
        # bot chat numbers every message in a shared conversation, most
        # of them nothing to do with this feed. It has published three
        # things in three days. Fifty-seven missing posts in a day and a
        # half is not a channel that went quiet, it is id numbers that
        # were never this channel's to begin with. Asking Telegram for
        # them is fifty-seven questions with no answer, on every run --
        # exactly the traffic pattern that gets a reader rate-limited,
        # and he has been clear that must never happen.
        #
        # So each channel is measured against ITSELF: its own posts, its
        # own days, its own rate. Nothing is pooled across channels --
        # Day Trader Telugu posts ninety a day and Earnings Pulse three,
        # and one number for both would be wrong for both.
        #
        # Three times the expected count is the bar, which is generous
        # on purpose: a results-day evening genuinely does run several
        # times the average, and the cost of asking is one request while
        # the cost of not asking is a post lost for good.
        # THREE posts, not five. WLPulseBot has published three things
        # in three days and it is the exact channel this guard is for --
        # a bar it cannot clear leaves it unguarded. Three points make a
        # shaky rate, which is why the bar above it is three TIMES the
        # expected count rather than the count itself.
        rate_per_hour = None
        dated = [w for _m, w in held if w is not None]
        if len(dated) >= 3:
            hours = (max(dated) - min(dated)).total_seconds() / 3600.0
            if hours >= 1.0:
                rate_per_hour = len(held) / hours

        gaps = []
        for (a, at_a), (b, at_b) in zip(held, held[1:]):
            if b - a <= 1:
                continue
            # The OLDER edge decides. A hole whose older side is already
            # past the retention edge is a hole in history, not a hole
            # in the news.
            if at_a is not None and at_a < cutoff:
                continue
            size = b - a - 1
            # ---- TOO LITTLE HISTORY MUST NOT MEAN NO GUARD. ----
            #                                   5 September 2026.
            #
            # The rate needs three dated posts. @WLPulseBot had three
            # when the guard was written and TWO by the evening -- one
            # aged past the 96h retention edge -- so rate_per_hour came
            # back None, the size test below was skipped entirely, and
            # all 57 of its ids were asked for again on his 16:56 run.
            # The guard failed open on the exact channel it exists for,
            # and it will do that to any quiet channel eventually,
            # because _prune() keeps taking posts away.
            #
            # With no measurable rate, what IS known is how much of this
            # channel we hold at all. A hole bigger than everything we
            # have ever seen from it is not its numbering: two posts on
            # file and fifty-seven "missing" between them is a shared
            # bot conversation, not a channel that went quiet.
            if size > 3 and not rate_per_hour and size > max(3, len(held)):
                diagnostic(
                    f"[GAPFILL] {channel_name}: ids {a + 1}-{b - 1} "
                    f"({size}) against {len(held)} post(s) ever held, "
                    f"and too little history to measure a rate. Not its "
                    f"post numbers -- not asking.")
                continue
            # Small holes are always asked about. One or two missing ids
            # is the ordinary shape of a service message -- somebody
            # joined, a post was pinned -- and one question settles it.
            if size > 3 and rate_per_hour and at_a and at_b:
                span = (at_b - at_a).total_seconds() / 3600.0
                could_have = max(1.0, rate_per_hour * span)
                if size > could_have * 3:
                    diagnostic(
                        f"[GAPFILL] {channel_name}: ids {a + 1}-{b - 1} "
                        f"({size}) span {span:.1f}h, and this channel "
                        f"publishes {rate_per_hour:.1f}/h. Not its post "
                        f"numbers -- not asking.")
                    continue
            for mid in range(a + 1, b):
                if mid not in spent:
                    gaps.append(mid)
            if len(gaps) >= cap:
                break
        return gaps[:cap]

    def _note_gap_attempt(self, channel_name, ids, arrived):
        """Remember what was asked for, so a dead id is asked for at
        most three times. `arrived` is the set of ids that came back."""
        if not ids:
            return
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                for mid in ids:
                    got = int(mid) in arrived
                    conn.execute(
                        "INSERT INTO gap_attempts "
                        "(channel, message_id, tries, first_try, last_try,"
                        " outcome) VALUES (?, ?, 1, ?, ?, ?) "
                        "ON CONFLICT(channel, message_id) DO UPDATE SET "
                        "tries = tries + 1, last_try = excluded.last_try, "
                        "outcome = excluded.outcome",
                        (channel_name, int(mid), now, now,
                         "arrived" if got else "nothing there"))
                conn.commit()
                conn.close()
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[GAPFILL] Could not record the attempt: {exc}")

    def fill_gaps(self, cap_per_channel=200):
        """Ask for every missing post by name. Returns how many arrived.

        Never raises. A gap fill that fails leaves the store exactly as
        it was, and the holes are still there to be asked for next run.
        """
        if self.client is None:
            return 0
        filled = 0
        for channel in self.channels:
            name = channel.get("name") or channel.get("handle")
            handle = channel.get("handle") or name
            if not handle:
                continue
            wanted = self.missing_ids(name, cap=cap_per_channel)
            if not wanted:
                continue
            decision(f"    {str(name)[:22]:22} {len(wanted):3} post(s) "
                     f"missing -- asking for them by id")
            # ==================================================
            # A CONTROL, SO SILENCE CAN BE READ.  5 Sep 2026.
            # ==================================================
            #
            # First live run, 16:49: every one of 71 ids came back
            # "nothing there". That is either exactly right -- Telegram
            # numbers service posts in the same sequence and those can
            # never be stored -- or the request does not work at all,
            # and NOTHING IN THE ANSWER TELLS THE TWO APART.
            #
            # It matters because the wrong reading is expensive: three
            # runs of a broken request would mark 71 real posts dead
            # and stop asking for them for good. Silence must not be
            # allowed to mean two things.
            #
            # So one id we KNOW we hold travels with the first batch.
            # If it comes back, the request works and the others really
            # are not posts. If it does not, the request is broken --
            # say so loudly, and record NOTHING, so no attempt is spent
            # on a mechanism that was not working.
            control = None
            try:
                with self._lock:
                    conn = sqlite3.connect(self.db_path)
                    row = conn.execute(
                        "SELECT CAST(message_id AS INTEGER) FROM messages "
                        "WHERE channel = ? AND message_id IS NOT NULL "
                        "ORDER BY 1 DESC LIMIT 1", (name,)).fetchone()
                    conn.close()
                control = int(row[0]) if row and row[0] is not None else None
            except Exception:                              # noqa: BLE001
                control = None

            got = []
            # A hundred at a time is Telegram's own batch size for this
            # request. Asking for more in one call is not faster and is
            # the shape of thing that draws a rate limit.
            for start in range(0, len(wanted), 100):
                batch = wanted[start:start + 100]
                if start == 0 and control is not None:
                    batch = batch + [control]
                try:
                    got.extend(self.client.fetch(handle, ids=batch) or [])
                except TypeError:
                    # A reader with no `ids` argument -- the public web
                    # view, or a stub. Nothing to do here; say it once.
                    diagnostic(f"[GAPFILL] {name}: this reader cannot ask "
                               f"for named posts. Holes left open.")
                    got = []
                    break
                except Exception as exc:                   # noqa: BLE001
                    warn(f"[GAPFILL] {name}: {str(exc)[:80]}. "
                         f"Keeping what arrived.")
                    break
            arrived = {int(m["id"]) for m in got
                       if str(m.get("id") or "").isdigit()}

            # The control decides how to read the silence -- see above.
            if control is not None and control not in arrived:
                warn(f"[GAPFILL] {name}: asked for {len(wanted)} missing "
                     f"post(s) AND for post {control}, which is already "
                     f"on file, and none of them came back. The request "
                     f"is not working -- recording nothing, so no attempt "
                     f"is spent. The holes stay open and will be asked "
                     f"for again.")
                continue
            arrived.discard(control)
            # The control is already on file. Keeping it here would send
            # its picture back through _store() for nothing.
            got = [m for m in got
                   if str(m.get("id") or "") != str(control)]

            self._note_gap_attempt(name, wanted, arrived)
            if got:
                # skip_known=False for the same reason catch_up() uses
                # it: these ids sit BELOW the newest id on file, and the
                # skip is keyed on that.
                added = self._store(channel, got, skip_known=False)
                filled += added
                decision(f"    {str(name)[:22]:22} {added:3} recovered, "
                         f"{len(wanted) - len(arrived):3} were never posts "
                         f"(service messages or deleted)")
        if filled:
            decision(f"[GAPFILL] Recovered {filled} post(s) that had been "
                     f"published and never collected.")
        return filled

    def catch_up(self, max_pages=CATCH_UP_PAGES):
        """Read backwards until we reach what we already have.

        WHY THIS EXISTS
        ---------------
            "real gap as far i concerned about after my terminal(laptop)
             close to next opening. & weekends data?"

        The laptop is off from about 15:30 to 09:00, and all weekend.
        One page of t.me/s/ is twenty posts. These channels publish
        6-10 an hour and 34% of everything they send arrives OUTSIDE
        market hours, so Friday close to Monday open is 400-700 posts
        against a twenty-post window. Everything else was lost, and it
        was lost silently -- Monday simply had no reason chips for
        anything that happened over the weekend.

        WHEN IT STOPS
        -------------
        The moment a page contains a post id we already hold. That is
        the correct signal rather than a page count or a timestamp: it
        means the two ranges now overlap and there is no hole between
        them. max_pages is only a safety rail for the very first run on
        an empty database, where there is nothing to overlap with and
        it would otherwise walk the entire channel history.

        DELIBERATELY NOT ON THE POLL LOOP. Runs once at startup. The
        90-second poll never has more than a page of new material, so
        paginating on every cycle would be hundreds of pointless
        requests a day at a stranger's expense.
        """
        recovered = 0
        for channel in self.channels:
            handle = channel["handle"]
            name = channel.get("name") or handle

            # ---- HIS CALL, 10 August 2026. ----
            #
            #     "out of 9 channels . brealout, news pulse , WLPULSE
            #      bot we can skip from getting back data. remaining 6
            #      we will start"
            #
            # Skips the BACKWARD WALK only. These channels keep being
            # polled forward exactly as before -- what is dropped is
            # re-reading their weekend history, which is 400-700 posts
            # a channel at 3.5 minutes a page with the market opening.
            #
            # Sound: Breakouts is a scanner listing, News Pulse is
            # world headlines, WLPulseBot is a digest. None of the
            # three carries a graded result card, and a stale headline
            # from Friday is worth nothing on Monday.
            if _skip_catch_up(name):
                decision(f"[CATCHUP] {name}: skipped by "
                        f"CATCH_UP_SKIP -- polled forward as normal, "
                        f"weekend history not re-read.")
                continue

            # ==========================================================
            # PAGES SIZED TO THE GAP, NOT A FLAT 40.  10 August 2026.
            # ==========================================================
            #
            #     "if bot knows upto which time on what day it recvd
            #      msgs from telegram then the remaining after that
            #      time to current can be tracked & get them ... it
            #      removes extra burden, duplication of data & more
            #      time to catchup with already existing data"
            #
            # core/feed_clock.py knows exactly how far behind each
            # channel is. A channel 0.4 hours behind does not need the
            # same 40-page allowance as one 63 hours behind, and on
            # 10 August every channel got the same allowance regardless.
            #
            # These channels publish roughly 6-10 posts an hour and a
            # page is about twenty, so half a page an hour is generous.
            # Two pages minimum: one to fetch, one to confirm it stops.
            #
            # The STOP rule is untouched. A page that adds nothing new
            # still ends the walk, which is what fills holes in the
            # MIDDLE of a range -- see the note further down. This only
            # decides how far it is ALLOWED to go, never when it stops.
            pages_for_this = max_pages
            try:
                from core import feed_clock
                behind = next((r["behind_hours"] for r in feed_clock.gaps()
                               if r["channel"] == name), None)
                if behind is not None:
                    pages_for_this = max(2, min(max_pages,
                                                int(behind * 0.6) + 2))
                    decision(f"[CATCHUP] {name}: {behind:.1f}h behind -- "
                            f"up to {pages_for_this} page(s), not "
                            f"{max_pages}.")
            except Exception:                              # noqa: BLE001
                pages_for_this = max_pages

            known = self._newest_stored_id(name)
            before = None
            barren = 0
            for page in range(pages_for_this):
                # SAY IT BEFORE THE SLOW PART, NOT AFTER.
                #
                # The progress line used to print after _store(), which
                # is where the photos are downloaded and OCR'd. On a
                # channel that is three-quarters pictures that is
                # minutes of work with nothing on screen -- so the run
                # looked hung and got Ctrl+C'd a second time.
                #
                # Announcing the fetch first costs one line and makes
                # the silence explainable.
                decision(f"    {name:22} page {page + 1:2} ...")
                try:
                    # AN EXPLICIT PAGE SIZE, NOT None. 1 August 2026.
                    #
                    # This said limit=None, which meant "everything on
                    # this page" -- about twenty -- to the web reader
                    # it was written against. When the Telegram API
                    # reader was made a drop-in, the same argument
                    # started meaning "the ENTIRE channel history":
                    # telethon iterates without a limit when given
                    # none.
                    #
                    # Measured: Breakouts, Earnings 360 and Earnings
                    # Pro all stopped at exactly 30 messages -- the
                    # first poll's worth -- because the walk that
                    # should have followed asked for ten thousand at
                    # once and never returned.
                    #
                    # One argument, two readers, two meanings. The page
                    # size is now stated rather than inferred.
                    messages = self.client.fetch(handle,
                                                 limit=CATCH_UP_PAGE_SIZE,
                                                 before=before)
                except Exception as exc:                   # noqa: BLE001
                    warn(f"[TELEGRAM] {name}: catch-up stopped at page "
                         f"{page + 1} ({exc}). Keeping what was read.")
                    break
                if not messages:
                    break
                # ---- STOP AT THE EDGE OF WHAT IS STILL TRUE ----
                #
                #     "from now we need to capture as they are
                #      contemporary things. not a memory one. a fresh
                #      breakout is not valid after 1 week so do not get
                #      these old items into bot"
                #                       -- operator, 1 August 2026
                #
                # He is right, and the code was worse than he thought:
                # _prune() deletes anything older than KEEP_HOURS, so
                # the walk was fetching months of history in order to
                # store messages that the same run then threw away.
                #
                # A breakout alert from June is not a signal, it is a
                # fact about June. Walking back to find it costs
                # requests at a stranger's server and puts stale
                # material in front of a live decision.
                #
                # So the walk stops at the retention edge -- the gap
                # since the bot was last running, and nothing older.
                if _all_older_than(messages, self.keep_hours):
                    decision(f"    {name:22} reached {self.keep_hours}h "
                             f"old -- stopping, nothing older is kept")
                    break

                # skip_known=False: this walk exists to fill holes,
                # and a hole sits BELOW the newest id we hold.
                added = self._store(channel, messages, skip_known=False)
                recovered += added
                # SAY SOMETHING WHILE IT WORKS, 1 August 2026.
                #
                # 40 pages across 5 channels is up to 200 network
                # fetches, plus OCR on every new picture, plus a paid
                # grading call per new event. That is minutes, and it
                # printed nothing for all of them -- so the operator
                # pressed Ctrl+C on a run that was working correctly.
                #
                # A long silence and a hang are indistinguishable. This
                # is one line per page, which is cheap and settles it.
                decision(f"    {name:22} page {page + 1:2}  "
                         f"{len(messages):3} read  {added:3} new")
                ids = [int(m["id"]) for m in messages
                       if str(m.get("id") or "").isdigit()]
                if not ids:
                    break

                # ---- STOP WHEN A PAGE ADDS NOTHING, NOT WHEN IT
                #      OVERLAPS. 1 August 2026. ----
                #
                # The first rule here was "stop as soon as a page holds
                # an id we already have". That handles a clean gap at
                # the END of what we hold, and cannot fill a hole in
                # the MIDDLE -- which is the shape the real gaps have:
                #
                #   31 July, Earnings Pulse posted ids 12587..12702
                #     116 posts published
                #      81 held
                #      35 missing, scattered through the range
                #
                # We held both the newest and the oldest of that range,
                # so the overlap rule stopped on page one and declared
                # itself finished with 35 posts still missing. The
                # laptop is off overnight and the page only carries
                # twenty at a time, so holes in the middle are the
                # normal case, not the exception.
                #
                # A page that stores NOTHING NEW is the honest signal
                # that we are into ground we already have. One such
                # page could be a coincidence on a quiet stretch, so it
                # takes two in a row.
                if added == 0:
                    barren += 1
                    if barren >= 2:
                        break
                else:
                    barren = 0
                before = min(ids)
            else:
                # Ran out of pages without overlapping. Say so -- a
                # silent partial recovery is how the original problem
                # went unnoticed for a week.
                if known is not None:
                    warn(f"[TELEGRAM] {name}: still had not reached "
                         f"stored history after {max_pages} pages. Some "
                         f"messages from the gap are missing.")
        if recovered:
            decision(f"[TELEGRAM] Catch-up recovered {recovered} message(s) "
                     f"posted while the bot was not running.")
        return recovered

    def _file_events(self, filed):
        """Turn what we just collected into scored events, now.

        Wrapped whole. This runs on the polling thread of a LIVE
        trading session, and a classifier that raises must never be
        able to stop messages being collected -- losing the event is
        recoverable by the nightly tool, losing the message is not.

        remember() is idempotent on (symbol, at, kind, headline), so
        re-filing a message the poller has seen before costs one
        ignored INSERT and nothing else. That is deliberate: it means
        this does not have to know which rows were new.
        """
        if self.stock_events is None or not filed:
            return 0
        written = 0
        fresh = []
        for item in filed:
            try:
                for event in events_from_message(self, **item):
                    if self.stock_events.remember(**event):
                        written += 1
                        if event.get("grade") or event["kind"] == "ORDER":
                            # Printed because the operator watches this
                            # log during the session. A graded result
                            # reaching the score is the single thing he
                            # asked to be able to see happening.
                            decision(
                                f"[EVENTS] {event.get('symbol') or 'MARKET'}"
                                f" -- {event['kind']}"
                                f"{' ' + event['grade'] if event.get('grade') else ''}"
                                f": {event['headline'][:80]}")
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[EVENTS] live filing skipped one message: {exc}")
        if written:
            self._request_directions()
        return written

    def _request_directions(self):
        """Ask the model about anything filed without a direction.

        Runs on the polling thread, straight after the events are
        written, so a result posted at 12:19 has a verdict beside it by
        12:20 -- the same 90-second promise as the collection itself.

        The LIMIT is small on purpose. A normal poll files a handful of
        events; anything larger means something unusual has happened,
        and a poll loop that could fire two hundred paid calls in one
        cycle is the retry-loop failure the budget meter exists to stop.
        The nightly tools/ai_backfill.py sweeps up whatever a busy
        minute left behind.

        Wrapped whole. This is a paid network call on the thread that
        collects messages, and losing a message is not recoverable
        while losing a verdict is -- the backfill re-derives it.
        """
        if self.ai_news is None:
            return 0
        try:
            result = self.ai_news.grade_pending(self.stock_events,
                                                limit=LIVE_GRADE_LIMIT)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[AI NEWS] live grading skipped: {exc}")
            return 0
        if result.get("graded"):
            decision(f"[AI NEWS] {result['graded']} new event(s) given a "
                     f"direction.")
        elif result.get("pending"):
            # Something was waiting and none of it got a verdict. That
            # is the budget cap, a missing key, or the API being down --
            # all three are things the operator must not have to guess
            # at, and all three used to look like silence.
            warn(f"[AI NEWS] {result['pending']} event(s) waiting and none "
                 f"were graded. Run  py tools/ai_check.py  to see why.")
        return result.get("graded", 0)

    def _store(self, channel, messages, skip_known=True):
        name = channel.get("name") or channel["handle"]

        # ---- RE-READING WHAT WE ALREADY HAVE. 29 August 2026. ----
        #
        #     "the bot is doing over than asked to do in this telegram
        #      data getting by re running multiple same info"
        #                                       -- operator
        #
        # He is right. Every 90 seconds each channel is asked for its
        # last DEFAULT_LIMIT messages, and typically none to two of
        # them are new. The rows were never duplicated -- the insert is
        # OR IGNORE and the primary key is (channel, message_id) -- but
        # everything BEFORE the insert ran on all thirty, every pass:
        # hashtag matching, symbols_in() over the text, and the event
        # extraction underneath it.
        #
        # The watermark already holds what is needed to stop that. A
        # post id at or below the newest one on file is a post we have
        # read, so it is skipped before any of that work happens.
        #
        # NOT FOR catch_up(), and the reason is a hole in the middle.
        # I first reasoned that a gap is always NEWER than what we
        # hold, so the floor was safe everywhere. It is not.
        # tests/test_telegram_catchup.py caught it in one run:
        #
        #     "49 posts inside the range were never recovered --
        #      a stop-on-first-overlap rule cannot fill a hole"
        #     "630 posts from the weekend were lost"
        #
        # Hold 1000-1050 from before a stop and 1100-1150 from after
        # the restart, and the newest id is 1150 -- so a floor of 1150
        # skips the entire 1051-1099 hole, which is precisely what
        # catch_up() exists to fill. skip_known=False there.
        #
        # The floor is taken once, at the top of this call, so a row
        # stored earlier in a page cannot raise the bar on the rest of
        # its own page. Non-numeric ids, or an empty store, mean no
        # floor and the old behaviour: skipping is an optimisation,
        # never a requirement.
        floor = self._newest_stored_id(name) if skip_known else None

        # One query, not one per message: the transcripts this channel
        # already holds, so a re-walk does not re-OCR what is on disk.
        known_ocr = self._stored_ocr(name)

        rows = []
        filed = []
        fresh = []
        skipped = 0
        reused = 0
        for message in messages:
            if floor is not None:
                try:
                    post_id = int(message.get("id")
                                  or message.get("message_id"))
                except (TypeError, ValueError):
                    post_id = None
                if post_id is not None and post_id <= floor:
                    skipped += 1
                    continue
            fresh.append(message)
            text = (message.get("text") or "").strip()
            photos = message.get("photos") or []
            # A post with NO text but a photo is the entire content of
            # the image channel. Dropping it would empty the one panel
            # the operator most wants.
            if not text and not photos and not message.get("photo_data"):
                continue
            at = message.get("at")
            # Hashtags first, but ONLY from channels whose hashtags
            # are the subject of the post. See CHANNELS above for the
            # measurements -- one of these channels tags a CBIZ story
            # with an unrelated Indian ticker.
            symbols = []
            if channel.get("trust_hashtags", True):
                symbols = [h for h in (message.get("hashtags") or [])
                           if h in self._known_symbols(hashtag=True)]
            for found in self.symbols_in(text):
                if found not in symbols:
                    symbols.append(found)

            # THE PICTURE, 30 July 2026.
            #
            #     "Day Trader Telugu posts all important news in live
            #      markets. NONE of them are being used by bot. WHY?"
            #     "all images are english only that too taken from X,
            #      or any other reliable sources only"
            #
            # 77 of that channel's 90 messages carry no text whatsoever
            # -- the news is inside the screenshot. Read it, keep the
            # transcript separate, and put it through the SAME matcher
            # with the same rules. A picture earns no extra trust for
            # having been harder to read.
            ocr = ""
            # ---- IT HAD ALREADY READ THIS PICTURE. 30 Aug 2026. ----
            #
            #     "timestamps for this purpose right? does bot knows
            #      about last arrival of msgs/news/events from
            #      telegram"                          -- operator
            #
            # It does, precisely: feed_watermark holds the last post id
            # and time per channel, and every stored message carries
            # its own ocr_text. And it re-read the images anyway --
            # _ocr_cache is in MEMORY, keyed by url, and dies with the
            # process. So catch_up(), which walks back over pages it
            # has mostly seen, paid full OCR on every screenshot again.
            #
            # Measured on a Sunday-morning restart: 3.5 minutes at 35%
            # CPU still on page 1 of 7, of the first of ten channels.
            # Day Trader Telugu posts its news AS screenshots, so most
            # posts on a page carry one.
            #
            # The transcript is already on disk. Read it back instead.
            stored_ocr = known_ocr.get(str(message.get("id") or ""))
            if stored_ocr:
                ocr = stored_ocr
                reused += 1
            # photo_data is set only by the Telegram API reader, whose
            # images have no public URL. Either way one photo per
            # message is read -- the first is the card; the rest are
            # usually the same thing at another size.
            blobs = message.get("photo_data") or []
            if not ocr and (photos or blobs) and self.read_images:
                ocr = self._read_photo(photos[0] if photos else None,
                                       data=blobs[0] if blobs else None)
                # Tickers AND full company names. A results card prints
                # "Aarti Industries", not "#AARTIIND".
                for found in (self.symbols_in(ocr) + self.names_in(ocr)):
                    if found not in symbols:
                        symbols.append(found)
            when = (at.isoformat() if hasattr(at, "isoformat")
                    else str(at or ""))
            rows.append((
                name, str(message.get("id") or ""),
                when,
                text[:2000], ",".join(symbols),
                datetime.now().isoformat(timespec="seconds"),
                message.get("grade"), message.get("filing_url"),
                "\n".join(photos[:4]), message.get("url"),
                channel.get("kind", "text"),
                1 if message.get("is_calendar") else 0,
                ocr or None,
                _boxes_json(self._ocr_boxes.get(message.get("url"))),
            ))
            # Filed in the same pass that read it. The OCR above is the
            # expensive part and it has just been done; deferring the
            # classification would mean reading the picture twice.
            filed.append({"text": text, "ocr_text": ocr, "at": when,
                          "channel": name, "url": message.get("url"),
                          "grade": message.get("grade"),
                          "from_image": bool(photos and not text),
                          # Carried so a GRID card (TOMORROW'S CALENDAR
                          # is a wall of logos) can be split by POSITION
                          # rather than by the order Tesseract happened
                          # to walk it in. None everywhere else.
                          "word_boxes": self._ocr_boxes.get(
                              message.get("url"))})
        if skipped or reused:
            diagnostic(f"[TELEGRAM] {name}: {skipped} already on file, "
                       f"{reused} picture(s) read back from disk instead "
                       f"of OCR'd again.")
        # ---- ONLY THE NEW ONES. 29 August 2026. ----
        # This took `messages`, so news_impact.record() ran for every
        # post on the page every 90 seconds -- a database round trip
        # each, for stories filed hours ago. The floor above already
        # decided which are new; this is the same decision, honoured.
        if self.news_impact is not None:
            self._remember_impact(name, fresh)
        self._file_events(filed)
        if not rows:
            return 0
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                before = conn.total_changes
                conn.executemany(
                    "INSERT OR IGNORE INTO messages "
                    "(channel, message_id, at, text, symbols, seen_at,"
                    " grade, filing_url, photos, url, kind, is_calendar,"
                    " ocr_text, ocr_boxes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                conn.commit()
                added = conn.total_changes - before
                conn.close()

            # ---- MARK HOW FAR THIS CHANNEL HAS BEEN READ. 10 Aug ----
            #
            #     "if bot knows upto which time on what day it recvd
            #      msgs from telegram then the remaining after that
            #      time to current can be tracked & get them"
            #
            # Until now nothing recorded this, so a channel that had
            # simply gone quiet looked exactly like one we had stopped
            # reading -- and a Monday catch-up could only sweep a
            # blanket 96 hours across nine channels. On 3 August that
            # sweep was on channel 2 of 9 at 3.5 minutes a page with
            # the market opening.
            #
            # The bookmark must never break the collection: record()
            # swallows everything and returns False.
            try:
                from core import feed_clock
                # ---- IT IS SOMETIMES A DICT. 10 August 2026. ----
                # `channel` arrives here as a plain name from the poll
                # path and as the whole {"handle","name",...} record
                # from the catch-up path. The first version passed it
                # straight through, so the watermark table grew rows
                # keyed on "{'handle': 'orders_pulse'..." beside the
                # real ones -- visible on his 07:41 screen, an hour
                # before the open. The messages themselves were stored
                # correctly; only the bookmark was polluted.
                key = channel
                if isinstance(channel, dict):
                    key = channel.get("name") or channel.get("handle")
                newest = max((r[2] for r in rows if r[2]), default=None)
                newest_id = max((r[1] for r in rows if r[1]), default=None)
                feed_clock.record(str(key), at=newest, message_id=newest_id,
                                  db_path=self.db_path)
            except Exception:                                  # noqa: BLE001
                pass
            return added
        except sqlite3.Error as exc:
            self._store_failures += 1
            self._last_error = f"store failed: {exc}"
            if not self._store_warned:
                self._store_warned = True
                warn(f"[TELEGRAM] Could not store messages from "
                     f"{channel.get('name') or channel.get('handle')}: "
                     f"{exc}. The messages WERE fetched successfully and "
                     f"are being dropped at {self.db_path} -- this is a "
                     f"LOCAL DATABASE fault, not Telegram and not an API "
                     f"or credentials problem. Warned once per run.")
            return 0

    def _remember_impact(self, channel_name, messages):
        """Hand each story to the impact memory.

        Deliberately NOT reasoned inline. Without ANTHROPIC_API_KEY
        the links are keyword-only with direction UNKNOWN, which is
        still worth storing: when the key arrives the same rows are
        re-reasoned in place by tools/news_impact_backfill.py. Storing
        now and reasoning later is the whole reason the news_id is a
        hash of the headline rather than a row number.
        """
        for message in messages:
            text = (message.get("text") or "").strip()
            if len(text) < 25:          # a bare link is not a story
                continue
            try:
                headline = text.split("\n")[0][:300]
                self.news_impact.record(
                    headline=headline, body=text, source=channel_name,
                    url=message.get("url"), at=message.get("at"))
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[TELEGRAM] impact record failed: {exc}")

    def _prune(self):
        """Chat is worth nothing once it is a day old."""
        cutoff = (datetime.now()
                  - timedelta(hours=self.keep_hours)).isoformat()
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                conn.execute("DELETE FROM messages WHERE seen_at < ?",
                             (cutoff,))
                conn.commit()
                conn.close()
        except sqlite3.Error as exc:
            # Lowest stakes of the silent writes -- a failed PRUNE keeps
            # too much rather than losing anything, so the panel is stale
            # at worst, never empty. Still reported: a database that
            # cannot be written to will fail the INSERT next, and that
            # one does lose data. Better to see it here first.
            diagnostic(f"[TELEGRAM] Could not prune old messages: {exc}")

    # ------------------------------------------------------------

    def recent(self, limit=25, symbol=None, hours=None):
        """Newest messages first. `symbol` narrows to one stock, which
        is what the stock card asks for."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM messages"
            params, where = [], []
            if hours:
                where.append("seen_at >= ?")
                params.append((datetime.now()
                               - timedelta(hours=hours)).isoformat())
            if symbol:
                # Comma-delimited on both sides so KAYNES cannot match
                # inside another symbol's name.
                where.append("(',' || symbols || ',') LIKE ?")
                params.append(f"%,{str(symbol).strip().upper()},%")
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY at DESC, seen_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except sqlite3.Error as exc:
            diagnostic(f"[TELEGRAM] read failed: {exc}")
            return []
        return [{
            "channel": r["channel"], "at": r["at"], "text": r["text"],
            "symbols": [s for s in (r["symbols"] or "").split(",") if s],
            "grade": r["grade"], "filing_url": r["filing_url"],
            "photos": [p for p in (r["photos"] or "").split("\n") if p],
            "url": r["url"], "kind": r["kind"],
            "is_calendar": bool(r["is_calendar"]),
            # What the picture said, if it was read. Handed out as its
            # OWN field, never folded into `text`, so the screen can
            # label it -- a machine reading a screenshot and a human
            # typing a sentence are not the same kind of evidence, and
            # the operator has to be able to tell which he is looking at.
            #
            # 30 July 2026: added when the transcripts existed but only
            # ever reached a terminal.
            #     "terminal is printing.... can we see them in our
            #      dashboard?"
            "ocr_text": (r["ocr_text"] if "ocr_text" in r.keys() else None),
        } for r in rows]

    def for_symbol(self, symbol, limit=5):
        """Everything the channels have said about one stock -- the
        stock card's own question."""
        return self.recent(limit=limit, symbol=symbol)

    def most_mentioned(self, hours=12, top=10):
        """Which stocks the channels are talking about most.

        A count, not a recommendation. Loud is not the same as right,
        and the loudest stock of the morning is as likely to be a pump
        as an opportunity.
        """
        counts = {}
        for row in self.recent(limit=500, hours=hours):
            for symbol in row["symbols"]:
                counts[symbol] = counts.get(symbol, 0) + 1
        rows = [{"symbol": s, "mentions": n} for s, n in counts.items()]
        rows.sort(key=lambda r: (-r["mentions"], r["symbol"]))
        return rows[:top]

    def snapshot(self, limit=20):
        """What the dashboard renders.

        `available` False is deliberately different from an empty
        list: "the channels are quiet" and "we cannot see Telegram"
        must never look the same.
        """
        rows = self.recent(limit=limit)
        return {
            "available": self.client is not None or bool(rows),
            "connected": self.client is not None,
            "channels": list(self.channels),
            "rows": rows,
            "count": len(rows),
            "most_mentioned": self.most_mentioned(),
            "last_poll_at": (self._last_poll_at.strftime("%H:%M:%S")
                             if self._last_poll_at else None),
            "error": self._last_error,
            # Said plainly on screen so nobody ever wonders.
            "note": "Reading only. Nothing here reaches the trading engine.",
        }
