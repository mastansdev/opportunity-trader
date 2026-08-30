"""
==========================================================
Why is this stock moving? Ask BOTH stores, best answer wins
==========================================================

    "i brought the required sources to bot , & u couldn't do the
     proper work?"                  -- operator, 5 August 2026

WHAT WENT WRONG
---------------
The bot keeps two separate memories of why a stock moves:

    news_memory.db   `impact.reason`  -- written from newswire stories
    stock_events.db  `events`         -- written from the PRO channels

core/ranker.py only ever read the FIRST one. Everything the PRO
channels publish -- the grades he pays for and the only source he says
he trusts -- sat in the second store, unread, all day.

SHILPAMED, 5 August. The best-performing name of the session, +12.63%.
The only thing the ranker could see about it was this:

    reason:    "matched on: SHILPAMED"
    direction: UNKNOWN

That is the keyword matcher reporting its own work. Meanwhile, in the
OTHER store, timestamped 13:51 IST -- three minutes before the stock
began to run:

    Earnings Pulse    #SHILPAMED - Good Results        grade=GOOD
    Earnings Pro      PAT +51% vs est                  grade=GOOD
    Earnings 360      CLEAN | Rising, Expanding        grade=GOOD

The stock was refused "reason is a lookup, not a mechanism" and never
reached his screen. A clean entry at 14:03 would have hit its target
at 14:38 for +Rs 2,972 on Rs 27,603 of stock.

41% of every reason row in news_memory is a "matched on:" lookup. This
is not one unlucky stock.

WHAT THIS DOES
--------------
One function, why(), asked once per symbol. It reads both stores and
returns the STRONGEST real answer, in this order:

    1. a graded PRO channel event from today
    2. a written newswire reason that actually explains something
    3. nothing -- and nothing is a valid answer

WHY THE PRO CHANNELS RANK FIRST
-------------------------------
    "those 9 are our sources & pro channels"
    "we cannot deviate from NSE & PRO CHANNELS"

They are also earlier. On SHILPAMED the PRO grade existed at 13:51 and
the newswire reason never did.

WHAT THIS DOES NOT DO
---------------------
It does not decide whether to trade. core/ranker.py still applies
every gate it applied before -- move, volume, liquidity, sector,
circuit, MTF, liveness. This only stops a real reason from being
thrown away for being in the wrong drawer.

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"

So nothing here infers, widens or borrows across symbols. An answer
for a symbol comes from rows carrying that symbol and no other.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta, timezone
import re

# Indian market time. Stored stamps are UTC; the session is not.
IST = timezone(timedelta(hours=5, minutes=30))

POSITIVE = "POSITIVE"
NEGATIVE = "NEGATIVE"
UNKNOWN = "UNKNOWN"

# What the PRO channels publish as a verdict, and which way each points.
# Read off real messages -- see data/stock_events.db `grade`.
_POSITIVE_GRADES = {"EXCELLENT", "GREAT", "GOOD"}
_NEGATIVE_GRADES = {"WEAK", "POOR"}
# MIXED and OK are deliberately absent. They are not a direction, and
# core/ranker.py refuses anything whose reason contradicts the move --
# a grade that points nowhere must not be dressed up as one that does.

# The kinds worth quoting as "why it is moving". MACRO and
# MARKET_ANSWER are about the market, not the stock, and attaching one
# to a single symbol is exactly the mis-match he warned about.
_STOCK_KINDS = {"RESULT", "ORDER", "CONCALL", "NEWS", "AI_VERDICT"}

# The matcher reporting its own work, not a reason.
_LOOKUP = re.compile(r"^\s*matched on\s*:", re.I)
MIN_REASON_CHARS = 15


# ---- THE CARD SAYS HOW OLD ITS OWN NEWS IS. 29 August 2026. ----
#
#     "i want the bot to see the stocks only gaining + reason behind
#      that"                                          -- operator
#
# The Breakouts and Earnings channels stamp a clock marker on every
# card saying when the thing it describes actually happened:
#
#     "#LAURUSLABS  (clock) Recent activity - 29d ago"
#     "#ESAFSFB     (clock) News published 10d ago"
#     "#MARINE      (clock) Recent activity - 21d ago"
#
# The card is POSTED today, so `at` is today and the previous-close
# window below lets it straight through. The news inside it is weeks
# old. That is not why the stock is moving now.
#
# 61 such cards since 1 August; 14 were being accepted as today's
# reason. Every one of those 14 carried a RESULT grade -- the "a
# scanner is not a news source" guard further down only covers the
# UNGRADED branch, so a graded recap bypassed it entirely. In the
# 28 August reconstruction MARINE was the best trade of the day and
# its stated reason was 21 days old.
#
# Anchored on the clock marker, NOT on loose "N<unit> ago" text.
# "NSE - Live + 8m ago" is a quote widget saying eight MINUTES, and
# reading a bare "m" as months made that card look eight months
# stale. Inside the marker "m" is minutes, matching its own "h".
_STAMPED_AGE = re.compile(
    "\U0001f552" + r"[^|]{0,48}?(\d+)\s*(mo|[mhdw])\s*ago", re.I)
_AGE_HOURS = {"m": 1.0 / 60.0, "h": 1.0, "d": 24.0, "w": 168.0, "mo": 720.0}

# A day. Overnight news IS why a stock gaps -- "Order received 20h
# ago" is a real reason this morning -- so hours stay. Days do not.
STALE_REASON_HOURS = 24.0


def stated_age_hours(headline):
    """How old the card says its OWN news is, in hours, or None.

    None means the card did not say. That is not the same as fresh:
    it is left to the `at` window to judge, exactly as before.
    """
    found = _STAMPED_AGE.search(str(headline or ""))
    if not found:
        return None
    try:
        count = int(found.group(1))
    except (TypeError, ValueError):
        return None
    return count * _AGE_HOURS.get(found.group(2).lower(), 0.0)


def age_text(at, now=None):
    """How old this reason is, in day-to-day words, or None.

        "22 minutes ago"    "3 hours ago"    "4 days old"

    ---- THE GATE WAS SILENT. 30 August 2026. ----

    is_stale_reason() below drops a reason the card says is a day or
    more old, which is right -- a four-day-old order is not why a
    stock is moving this morning. But it dropped it WITHOUT SAYING
    SO, and the returned dict carried text, weight, direction and
    source with no timestamp on it at all. The stock simply appeared
    with no reason, indistinguishable from a stock nothing had ever
    been published about.

        "without visually seeing , how can i ask u or guide whats
         wrong or correct?"              -- the operator, same day

    "days old" rather than "days ago" past a day: the wording is the
    warning.
    """
    if not at:
        return None
    try:
        from core.feed_clock import to_ist
        from datetime import datetime

        when = to_ist(at)
        if when is None:
            return None
        now = now or datetime.now()
        if getattr(when, "tzinfo", None) is not None:
            when = when.replace(tzinfo=None)
        minutes = int((now - when).total_seconds() // 60)
    except Exception:                                      # noqa: BLE001
        return None

    if minutes < 0:
        return None                     # two clocks disagreeing
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} old"


def is_stale_reason(headline, limit_hours=None):
    """True when the card itself says its news is a day or more old.

    Never guesses. A card that states no age is not stale here.
    """
    age = stated_age_hours(headline)
    limit = STALE_REASON_HOURS if limit_hours is None else limit_hours
    return age is not None and age >= limit



# ---- A FAILURE MUST LEAVE A MARK. 8 August 2026. ----
#
#     "why these many bugs were un noticied till now?"
#
# 251 handlers on the live path swallow an exception and return
# nothing. Six real bugs hid in that pattern in a single day: the
# calendar refusing a date object, why() never fetching the PRO
# events, news events dropped for having no grade. Each one returned
# None, nothing was logged, and the bot ran on less information than
# it had while every test passed.
#
# None is a legitimate answer here -- most stocks have no reason. But
# an EXCEPTION is not the same as "no reason", and until now they
# looked identical from the outside.
#
# Rate-limited to once per source per session: this runs inside the
# ranking loop over 1,100 symbols and a warning per symbol would be
# its own kind of blindness.
_complained = set()


def _broke(where, exc):
    """Say it once, then stay quiet. Returns None for the caller."""
    if where not in _complained:
        _complained.add(where)
        try:
            from core.logger import warn
            warn(f"[WHY] {where} raised and was swallowed: "
                 f"{type(exc).__name__}: {exc}. Reasons from this "
                 f"source are MISSING until it is fixed.")
        except Exception:                                  # noqa: BLE001
            pass
    return None


def is_a_real_reason(text):
    """Does this text explain anything, or is it bookkeeping?

    "matched on: SHILPAMED" is the keyword matcher naming itself. So is
    a fragment too short to contain a claim.
    """
    text = str(text or "").strip()
    if not text or _LOOKUP.match(text):
        return False
    return len(text) >= MIN_REASON_CHARS


def direction_of_grade(grade):
    """A PRO channel grade as a direction, or UNKNOWN."""
    grade = str(grade or "").strip().upper()
    if grade in _POSITIVE_GRADES:
        return POSITIVE
    if grade in _NEGATIVE_GRADES:
        return NEGATIVE
    return UNKNOWN



# ---- NAMING A STOCK IS NOT NEWS. 8 August 2026. ----
#
# The first version of the NEWS fallback above accepted any headline
# over 15 characters. That immediately regressed NAVINFLUOR and
# GMMPFAUDLR, whose result cards were replaced by this, from the
# Breakouts scanner:
#
#     "#NAVINFLUOR.NS NAVINFLUOR.NS Navin Fluorine International"
#
# Long enough to pass, and it says nothing at all -- it is the ticker
# three times. A reason has to make a CLAIM about the company, not
# announce that the company exists.
_NOISE_WORDS = {"NS", "BSE", "NSE", "LTD", "LIMITED", "INDIA", "THE",
                "AND", "CAP", "SMALL", "MID", "LARGE"}


_name_words_cache = {}


def _own_name_words(symbol):
    """The words that are just this company's own name."""
    symbol = str(symbol or "").upper()
    if symbol in _name_words_cache:
        return _name_words_cache[symbol]
    words = set(re.findall(r"[A-Za-z]{2,}", symbol))
    try:
        from core.master_loader import MasterLoader
        if "__loader__" not in _name_words_cache:
            _name_words_cache["__loader__"] = MasterLoader()
        row = _name_words_cache["__loader__"].get_by_symbol(symbol) or {}
        words |= set(re.findall(r"[A-Za-z]{2,}",
                                str(row.get("COMPANY NAME") or "").upper()))
    except Exception:                                      # noqa: BLE001
        pass
    if len(_name_words_cache) > 3000:
        _name_words_cache.clear()
    _name_words_cache[symbol] = words
    return words


def _says_something(headline, symbol=None):
    """Does this headline claim anything, or just name the stock?

    ---- STRIP THE COMPANY'S OWN NAME. 8 August 2026. ----
    Counting "meaningful words" was not enough. The Breakouts scanner
    posts "#NAVINFLUOR.NS NAVINFLUOR.NS Navin Fluorine International"
    -- four distinct words, all of them the company's own name, and it
    replaced NAVINFLUOR's real result card.

    A reason says something the company NAME does not. So remove the
    ticker and the registered name, and require what is left to be a
    sentence.
    """
    if not is_a_real_reason(headline):
        return False
    words = re.findall(r"[A-Za-z]{2,}", str(headline).upper())
    own = _own_name_words(symbol) if symbol else set()
    seen, meat = set(), 0
    for word in words:
        if word in _NOISE_WORDS or word in own or word in seen:
            continue
        seen.add(word)
        meat += 1
    return meat >= 3


def _local_naive(text):
    """A stored stamp as IST wall-clock, or None.

    ---- THERE IS ONE CLOCK AND IT ALREADY EXISTED. 23 Aug 2026 ----
    #
    #     "why simple timing is still not resolved. we are in IST &
    #      its +05:30 asian timing"     -- operator, 23 August 2026
    #
    # Because +05:30 was written out TEN separate times in this repo,
    # and core/feed_clock.to_ist() -- built on 10 August from his own
    # instruction, "create a mechanism if bot doesn't know" -- was
    # used by almost none of them. Each fresh copy is a fresh chance
    # to strip the offset instead of applying it, and stripping is
    # what core/morning_ready.py, core/reaction.py, core/telegram_feed.py
    # and the first draft of this function all did.
    #
    # 16,247 of 16,407 stored events carry "+00:00". Deleting that
    # moves a stamp 5h30m earlier, so a post at 20:00 IST reads 14:30
    # and falls BEFORE a 15:30 close -- throwing away the whole
    # evening window this module exists to preserve.
    #
    # Naive comparisons here, so the offset is applied and then shed.
    """
    from core.feed_clock import to_ist
    moment = to_ist(text)
    return None if moment is None else moment.replace(tzinfo=None)


def previous_trading_close(clock):
    """15:30 on the last session before `clock`. Never raises.

    One rule for every evidence source. Anything published after this
    moment belongs to the session `clock` is in; anything before it
    belonged to a session that has already been traded.
    """
    fallback = clock.replace(hour=15, minute=30, second=0,
                             microsecond=0) - timedelta(days=1)
    try:
        from core.market_calendar import default_calendar
        previous = default_calendar().previous_trading_day(clock.date())
    except Exception:                                       # noqa: BLE001
        return fallback
    if previous is None:
        return fallback
    return datetime(previous.year, previous.month, previous.day, 15, 30)


def from_events(events, on_date=None):
    """The best PRO channel answer for ONE symbol, or None.

    `events` is core/stock_events.py's for_symbol() output -- newest
    first. `on_date` limits it to a single session ("2026-08-05");
    without it, the newest graded event wins whenever it happened.

    Yesterday's result is not why a stock is moving today, so callers
    on the live path should always pass on_date.
    """
    # ---- LAST NIGHT'S NEWS IS WHY IT GAPS THIS MORNING. 23 Aug ----
    #
    #     "after market hours news/telegram channels updates will
    #      recevie , store & use them when the opportunity occurs"
    #                                    -- operator, 23 August 2026
    #
    # `on_date` was an exact date-string match, so an event carried
    # the session it was POSTED in rather than the session it acts on.
    # Everything the channels published after 15:30 was collected,
    # stored, and then discarded the next morning:
    #
    #     Monday 21:00 order win, read on Tuesday   ->  LOST
    #     Monday 16:10 result,    read on Tuesday   ->  LOST
    #     Friday 18:30 news,      read on Monday    ->  LOST
    #
    # That is the whole after-hours channel feed -- which is when the
    # exchange publishes, when the desks post, and when the stock that
    # gaps tomorrow is decided. The bot then had no reason for the gap
    # and REQUIRE_A_REASON_ALWAYS refused the stock.
    #
    # The window is now the same one filings use: the previous trading
    # close to the end of the session being asked about. The docstring
    # rule is unchanged and still enforced -- yesterday's IN-SESSION
    # result is not why a stock moves today, because 14:00 Monday is
    # before Monday's close.
    window_from = window_to = None
    if on_date:
        try:
            end = datetime.fromisoformat(str(on_date) + "T23:59:59")
            window_from = previous_trading_close(end)
            window_to = end
        except (TypeError, ValueError):
            window_from = window_to = None

    for event in (events or []):
        if not isinstance(event, dict):
            continue
        at = str(event.get("at") or "")
        if window_from is not None:
            when = _local_naive(at)
            if when is None:
                # No usable stamp. Fall back to the old exact-date
                # match rather than letting an undated event through.
                if not at.startswith(str(on_date)):
                    continue
            elif not (window_from < when <= window_to):
                continue
        elif on_date and not at.startswith(str(on_date)):
            continue
        if str(event.get("kind") or "").upper() not in _STOCK_KINDS:
            continue

        # The card stamped its own age. Weeks-old news is not why the
        # stock is moving now, whatever grade the card carries -- and
        # this sits ABOVE all three return paths below on purpose, so
        # a graded recap cannot slip past the way it did until today.
        if is_stale_reason(event.get("headline")):
            continue

        # An explicit AI verdict outranks a grade: it was written about
        # this event specifically.
        reason = event.get("ai_reason")
        direction = str(event.get("ai_direction") or "").upper()
        if is_a_real_reason(reason) and direction in (POSITIVE, NEGATIVE):
            return {"text": str(reason).strip(),
                    "weight": float(event.get("ai_confidence") or 0.8),
                    "direction": direction,
                    "at": event.get("at"),
                    "source": "PRO channel verdict"}

        grade_direction = direction_of_grade(event.get("grade"))
        if grade_direction == UNKNOWN:
            # ---- A NEWS ITEM HAS NO GRADE. 8 August 2026. ----
            #
            #     "decngold has news"          -- operator
            #
            # DECNGOLD moved +8.87% on 6 August. The bot HAD the
            # reason, stored and correctly tagged:
            #
            #   kind=NEWS  "DECCAN GOLD: CO. PRODUCES FIRST GOLD DORE
            #               AT ALTYN TOR PROJECT IN KYRGYZSTAN"
            #
            # and threw it away here. This grade check was written for
            # result cards, where a grade always exists. Company news
            # has no grade and never will, so EVERY news catalyst was
            # discarded however good -- and his rules name news as an
            # entry reason in its own right:
            #
            #     "NEWS = ONLY POSITIVE NEWS WHICH WILL GIVE SOME
            #      POINTS TO GRAB & EXIT"
            #
            # So a NEWS or ORDER event qualifies on its own headline.
            # Direction is left UNKNOWN rather than guessed: the
            # ranker already refuses a reason that contradicts the
            # move, and inventing a direction from a headline is how
            # the "matched on:" rubbish got into news_memory.
            kind = str(event.get("kind") or "").upper()
            headline = str(event.get("headline") or "").strip()
            # ---- A SCANNER IS NOT A NEWS SOURCE. 8 August 2026. ----
            # Breakouts posts a listing, not a story:
            #   "#NAVINFLUOR.NS NAVINFLUOR.NS Navin Fluorine Inte,
            #    NSE, Large-cap 39037 cr, Basic Materials- Chemicals"
            # Ticker, exchange, market cap, sector. It states that the
            # stock exists. Allowing it as a NEWS reason replaced
            # NAVINFLUOR's real result card with its own directory
            # entry, which is worse than having no reason at all.
            source = str(event.get("source") or "").upper()
            if kind in ("NEWS", "ORDER") \
                    and "BREAKOUT" not in source \
                    and _says_something(headline, event.get("symbol")):
                return {"text": headline,
                        "weight": 0.6,
                        "direction": UNKNOWN,
                        "at": event.get("at"),
                        "source": "PRO channel " + str(
                            event.get("source") or "").strip()}
            continue
        headline = str(event.get("headline") or "").strip()
        if not is_a_real_reason(headline):
            continue
        # The grade IS the claim; the headline carries the detail.
        return {"text": headline,
                "weight": 0.9,
                "direction": grade_direction,
                "at": event.get("at"),
                "source": "PRO channel " + str(event.get("source")
                                               or "").strip()}
    return None


# What an NSE filing is WORTH, by the kind core/feed_store.py stamps.
# A binding corporate action is not the same evidence as an AGM notice,
# and flattening them would put "Corrigendum to EGM notice" beside an
# open offer on his phone.
# ---- THE KINDS ARE THE STORE'S, NOT MINE. 21 Aug 2026 ----
# The first version of this table guessed "ORDER" and "RESULT".
# core/feed_store.py actually stamps ORDER_WIN and RESULTS, so the two
# most valuable kinds fell through to a permissive default -- and so
# did every kind nobody had thought about. "Press Release" reached his
# board as a reason to buy. Read off the live store:
#
#     GOVERNANCE 57   Resignation of Director/KMP/SMP
#     DEAL       24   Disclosure under SEBI Takeover Regulations
#     PAYOUT     23   Record Date
#     ORDER_WIN  23   Bagging/Receiving of orders/contracts
#     RATING     20   Credit Rating- New
#     RESULTS    16   Analysts/Institutional Investor Meet/Con. Call
#     APPROVAL   10   Press Release
#     FUND_RAISE  9   Allotment of Securities
FILING_WEIGHT = {
    "DEAL": 0.85, "ORDER_WIN": 0.85, "FUND_RAISE": 0.80,
    "RESULTS": 0.80, "CONCALL": 0.60, "RATING": 0.65,
    # OTHER is every filing core/announcement_watcher.classify() does
    # not recognise. From 21 August those are KEPT rather than thrown
    # away -- 468 of 602 a day were being discarded -- but kept below
    # the bar, so the bot can SEE them without being allowed to BUY on
    # them until a subject has earned it.
    "OTHER": 0.30,
    "APPROVAL": 0.40, "PAYOUT": 0.45, "GOVERNANCE": 0.35,
}

# An UNRECOGNISED kind is not a reason. The default used to be 0.55 --
# above the bar -- so a kind nobody had classified counted as evidence
# by accident. His rule is "an event or real opportunity", and a
# subject line we cannot categorise is neither.
FILING_DEFAULT_WEIGHT = 0.40

# Below this a filing is recorded but is not, on its own, a reason to
# buy. AGM notices and board-meeting intimations sit here.
FILING_MIN_WEIGHT = 0.50


def from_filing(filing, on_date=None, now=None):
    """The NSE filing behind today's move, or None.

    ==========================================================
    IT READ TWO STORES OUT OF THREE. 21 August 2026.
    ==========================================================

        "the top gainers/ movers itself proves something is happening
         inside the stock right?"                    -- operator

    He was right, and the bot's own feed proved it. 21 August, seven
    of the day's gainers were refused "no event behind it":

        KRONOX     +9.3%   Public Announcement-Open Offer
        NETWEB     +4.2%   Rs 1,200 crore QIP
        RHETAN     +9.1%   1 MW solar project operational
        IIFL       +6.2%   credit rating reaffirmed
        THOMASCOOK +12.7%  AGM, Rs 0.50 dividend

    Every one of those is a PUBLISHED NSE FILING, and data/feeds.db
    was holding them -- 31 stored that day, newest at 13:05. The
    trading path never opened it.

    dashboard/state.py's _mechanism_for() asks core/stock_events.py
    (the PRO channels) and core/news_impact.py (the newswire). It has
    never asked the filing store. That is the SAME fault as 5 August,
    when it read one store out of two and refused SHILPAMED all day
    while three channels had graded it GOOD -- one store further on.

    THE EVENING FILING IS THE POINT

    KRONOX's open offer was filed at 18:43 on the 20th -- after the
    close, which is exactly when the ones that move a stock get filed.
    A same-day filter would miss precisely the filings that matter, so
    the window runs from the PREVIOUS CLOSE, the same rule
    Engine._channel_event_kind() already uses.
    """
    if not isinstance(filing, dict):
        return None
    subject = str(filing.get("subject") or "").strip()
    if not subject:
        return None

    kind = str(filing.get("kind") or "").upper()
    weight = FILING_WEIGHT.get(kind, FILING_DEFAULT_WEIGHT)
    if weight < FILING_MIN_WEIGHT:
        return None

    # WINDOW: from the previous close to now. Anything older belongs
    # to an earlier session's move, however important it was.
    stamp = filing.get("_filed_dt") or filing.get("filed_at")
    when = None
    for text in (stamp, filing.get("at")):
        if not text:
            continue
        when = _local_naive(text)
        if when is not None:
            break
    if when is not None:
        clock = now or datetime.now()
        if on_date:
            try:
                clock = datetime.fromisoformat(str(on_date) + "T23:59:59")
            except (TypeError, ValueError):
                pass
        # ---- THE PREVIOUS TRADING CLOSE, NOT YESTERDAY. 23 Aug ----
        #
        #     "after market hours news/telegram channels updates will
        #      recevie , store & use them when the opportunity occurs"
        #                                    -- operator, 23 August 2026
        #
        # This was `clock - 1 day`, and both arms of the branch that
        # chose it did the same thing -- which is what a session-aware
        # rule looks like after it has been flattened. Across a weekend
        # it threw away exactly the news he means: measured on Monday
        # 11:00, a Friday 18:30 order win and a Saturday filing were
        # both LOST, while Sunday 20:00 survived. Friday evening is
        # when the exchange publishes and when the channels post, and
        # Monday morning is when the stock gaps on it. The bot had no
        # reason for the move and REQUIRE_A_REASON_ALWAYS then refused
        # the stock.
        #
        # Holidays behave the same way and are worse -- a Thursday
        # holiday puts three nights between two sessions.
        #
        # Falls back to the old answer if the calendar cannot be read.
        # This runs on the trading loop and must not raise.
        cutoff = previous_trading_close(clock)
        if when < cutoff:
            return None
        if when > clock:
            return None

    return {"text": subject,
            "weight": weight,
            "direction": UNKNOWN,
            "source": f"NSE filing ({kind})" if kind else "NSE filing"}


def from_news(hits):
    """The best newswire answer for ONE symbol, or None.

    `hits` is core/news_impact.py's for_symbol() output. Anything that
    is only a keyword match is skipped rather than returned -- that is
    the whole SHILPAMED failure.
    """
    for hit in (hits or []):
        if not isinstance(hit, dict):
            continue
        text = hit.get("reason") or hit.get("headline")
        if not is_a_real_reason(text):
            continue
        return {"text": str(text).strip(),
                "weight": float(hit.get("confidence") or 0.5),
                "direction": str(hit.get("direction") or UNKNOWN).upper(),
                "source": "news"}
    return None


def from_gappers(symbol):
    """The pre-open gapper card's answer for ONE symbol, or None.

    ---- A TABLE IS A REASON TOO. 6 August 2026. ----

        "have we / bot recvd & read about today pre-opened stocks?"

    On 6 August the ranker refused 494 of 605 moving stocks for "no
    reason found", and NAVINFLUOR -- up 8.58% on Rs 119 crore, closing
    near its high -- was one of them.

    The bot was holding this at 09:08 IST, from Earnings Pulse, with
    all twelve symbols correctly linked:

        NAVINFLUOR   Quality: Great   MCap 39,079 Cr   Gap +4.5%

    A named stock, a graded result, a measured gap. from_events() and
    from_news() both returned None because they look for a SENTENCE
    and the card is a TABLE. The source was never missing. The reader
    was.
    """
    try:
        from core import gappers
        row = gappers.row_for(symbol)
    except Exception as exc:                               # noqa: BLE001
        return _broke("gapper card", exc)
    if not row:
        return None
    line = gappers.reason_line(row)
    if not line:
        return None

    # ---- THE GRADE MUST DRIVE THE SCORE. 6 August 2026. ----
    #
    # The first version returned weight=2 for every stock. ranker.py
    # multiplies the weight into the score, so SOTL (Excellent result,
    # +13.4% gap) and PACEDIGITK (Weak result, -4.6% gap) both came out
    # at exactly 8.00 and the ranker could not tell them apart. It had
    # found five candidates and could not rank them, which is the one
    # job it exists to do.
    #
    # ranker.py expects 0..1. The channel already graded the result --
    # use its grade.
    weight = {"EXCELLENT": 0.95, "GREAT": 0.85, "GOOD": 0.65,
              "OK": 0.45, "WEAK": 0.20}.get(
        str(row.get("quality") or "").upper(), 0.45)

    # ---- A DOWN GAP IS NOT A REASON TO BUY. ----
    #
    #     "i only trade in long positions"
    #
    # CUMMINSIND (-4.9%) and PACEDIGITK (-4.6%) gapped DOWN on their
    # results and then recovered intraday. The ranker offered both as
    # long candidates, because direction came back None and its
    # "reason contradicts the move" gate had nothing to test.
    #
    # ranker.py reads POSITIVE / NEGATIVE, so say which it is.
    direction = "POSITIVE" if row.get("direction") == "UP" else "NEGATIVE"

    return {"text": line, "weight": weight, "direction": direction,
            "source": "Earnings Pulse -- pre-open gappers",
            "quality": row.get("quality"), "gap_pct": row.get("gap_pct")}


def from_calendar(symbol, on_date=None):
    """"It reported yesterday" is itself the reason, or None.

    ---- THE BOT WAS BOUND TO NOW. 6 August 2026. ----

        "what alphabetical order? none are the hard coded rules here
         GMMPFAUDLR result last day. so bot doesnt know which stock got
         result last day , today & next day? it is binded to now"

    He is right and the data was already in the building. GMMPFAUDLR
    closed up 13.8% on 6 August, and data/results_calendar.db has held
    this the whole time:

        GMMPFAUDLR  results_date 2026-08-05  NSE_ANN  17:03
        "quarterly financial results for the quarter ended Jun 30 2026"

    5,669 rows, refreshed the same morning. The ranker never asked.

    A result filed after yesterday's close is the single most common
    reason a stock moves at today's open -- and unlike a channel card
    it exists for EVERY listed company, from the exchange itself, on
    the day it happens. So it is a first-class reason source.
    """
    if not symbol:
        return None
    try:
        import sqlite3
        from datetime import date, datetime, timedelta
        # ---- IT ONLY ACCEPTED A STRING. 8 August 2026. ----
        #
        # strptime() takes str. Handed a date or a datetime it raises
        # TypeError, the bare except below swallows it, and the whole
        # function returns None -- silently, with no log line.
        #
        # Measured that evening: why(symbol="SBCL") returned "reported
        # results yesterday", and why(symbol="SBCL", on_date=<datetime>)
        # returned nothing. Every tools/replay_day.py decision passes a
        # datetime, so the results calendar -- the one reason source
        # that exists for EVERY listed company -- was absent from every
        # replayed decision, and from the centre.
        #
        # Accept all three shapes rather than trusting callers to guess.
        if on_date is None:
            today = datetime.now().date()
        elif isinstance(on_date, str):
            today = datetime.strptime(on_date[:10], "%Y-%m-%d").date()
        elif isinstance(on_date, datetime):
            # datetime FIRST -- datetime subclasses date, so testing
            # isinstance(x, date) matches both and the datetime branch
            # never runs. That is precisely how the first fix still
            # returned None for every replay call.
            today = on_date.date()
        else:
            today = on_date                 # date
        con = sqlite3.connect("data/results_calendar.db")
        rows = con.execute(
            "select results_date, purpose from results_events "
            "where upper(symbol) = ? and results_date >= ? "
            "and results_date <= ? order by results_date desc limit 1",
            (str(symbol).upper(),
             (today - timedelta(days=4)).isoformat(),
             (today + timedelta(days=4)).isoformat())).fetchall()
        con.close()
    except Exception as exc:                               # noqa: BLE001
        return _broke("results calendar", exc)
    if not rows:
        return None
    when, purpose = rows[0]
    try:
        from datetime import datetime as _dt
        gap = (_dt.strptime(when, "%Y-%m-%d").date() - today).days
    except Exception as exc:                               # noqa: BLE001
        return _broke("results calendar date", exc)

    # ---- A RESULT DUE TOMORROW IS NOT A REASON TO BUY TODAY ----
    # It is a reason to be careful: the operator holds overnight on
    # MTF, and buying into an unknown print is a coin toss he did not
    # ask for. Reported = a reason. Upcoming = a warning, no weight.
    if gap > 0:
        return {"text": (f"results due in {gap} day(s) -- "
                         f"{str(purpose)[:60]}"),
                "weight": 0.0, "direction": None,
                "source": "NSE results calendar", "upcoming": True}
    when_words = {0: "reported results today",
                  -1: "reported results yesterday"}.get(
        gap, f"reported results {abs(gap)} sessions ago")
    return {"text": f"{when_words} -- {str(purpose)[:70]}",
            # Below a graded channel card, above an unexplained move:
            # the exchange confirms THAT it reported, the card grades
            # HOW it went.
            "weight": 0.55, "direction": None,
            "source": "NSE results calendar"}


# ---- ONE READER, ONE QUERY PER SYMBOL PER MINUTE. 8 Aug 2026 ----
#
# The first version built a StockEvents() and hit the database on
# EVERY why() call. Measured: 7.6 seconds for a single ranking cycle
# of 60 symbols. The live loop ranks every few seconds, so this would
# have spent the whole session opening sqlite connections while the
# market moved.
#
# Same trap core/catalysts.py hit this morning. Opening a store per
# symbol per cycle is never right on the trading loop.
#
# The events for a stock do not change second to second, so a short
# TTL is honest: fresh enough that a card landing at 11:51 is seen on
# the next cycle, cheap enough that ranking is not the bottleneck.
_EVENT_TTL_SECONDS = 45.0
_events_cache = {}
_events_reader = [None]


def _events_for(symbol):
    """This stock's PRO channel events, cached briefly."""
    import time
    symbol = str(symbol or "").upper()
    if not symbol:
        return None
    now = time.time()
    hit = _events_cache.get(symbol)
    if hit is not None and (now - hit[0]) < _EVENT_TTL_SECONDS:
        return hit[1]
    try:
        if _events_reader[0] is None:
            from core.stock_events import StockEvents
            _events_reader[0] = StockEvents()
        rows = _events_reader[0].for_symbol(symbol, limit=25)
    except Exception as exc:                               # noqa: BLE001
        rows = _broke("PRO channel events", exc)
    # Bounded. A session touches ~1,100 symbols; this keeps the last
    # few cycles rather than growing all day.
    if len(_events_cache) > 2500:
        _events_cache.clear()
    _events_cache[symbol] = (now, rows)
    return rows


def _why_before_payoff(events=None, news_hits=None, on_date=None,
                       symbol=None, filing=None):
    """The single answer, or None.

    PRO channels first -- they are the source he trusts and, on
    SHILPAMED, they were also two hours earlier than anything else.
    The gapper card is checked last: it is a real mechanism, but a
    written explanation of the move beats a table of gaps.

    `symbol` is optional so every existing caller keeps working; pass
    it and the gapper card is consulted too.

    Returns {"text", "weight", "direction", "source"} in exactly the
    shape core/ranker.py's mechanism_of() already expects, so the
    ranker needs no new field to read.
    """
    # ---- THE FILING STORE IS THE THIRD SOURCE. 21 August 2026 ----
    # data/feeds.db holds the NSE announcements and no part of the
    # trading path had ever opened it. See from_filing().
    filed = from_filing(filing, on_date=on_date) if filing else None

    if not symbol:
        return (from_events(events, on_date=on_date)
                or filed or from_news(news_hits))

    # A result due TOMORROW is a warning, never a reason -- and it
    # outranks everything, because he holds overnight on MTF and
    # buying into an unknown print is a coin toss he did not ask for.
    ahead = from_calendar(symbol, on_date=on_date)
    if ahead and ahead.get("upcoming"):
        return ahead

    # ---- FETCH THE PRO EVENTS IF NOBODY HANDED THEM IN. 8 Aug 2026 ----
    #
    #     "on 06/08/2026 i stopped the bot early & terminal -2 news
    #      collector left running."           -- operator
    #
    # He offered that as the explanation for why no PRO channel card
    # appeared on 6 August. It was not the cause. data/stock_events.db
    # holds 166 graded RESULT events for that day; the collector did
    # its job.
    #
    # The cause is this function. from_events() reads the `events`
    # argument, and every caller that does not fetch and pass them
    # gets None -- silently, with the calendar answering instead. The
    # live dashboard passes them via _mechanism_for(); the replay,
    # core/centre.py and every test call why(symbol=X) and never have.
    #
    # So the nine PRO channels he pays for -- the grades, the AI
    # verdicts, the only source he says he trusts -- have been absent
    # from every replayed decision and every number I have shown him.
    #
    # A function that needs to be fed to work will eventually be
    # called by someone who does not know that. It fetches for itself.
    if events is None:
        events = _events_for(symbol)

    # The FILING sits between the PRO channels and the newswire: it is
    # a primary document, so it beats a keyword match, but the channels
    # carry a graded direction that a bare subject line does not.
    return (from_events(events, on_date=on_date)
            or filed
            or from_news(news_hits)
            # ---- ORDER WINS AND BUSINESS UPDATES. 8 August 2026. ----
            #
            #     "concall , business updates are already with telegram
            #      pro channels & also check for the data we were
            #      ignoring"                        -- operator
            #
            # Business Pulse and OrderBook Pulse had been arriving for
            # a month, correctly symbol-tagged, and nothing read them.
            # Eleven of twelve stocks they named came back with no
            # reason at all.
            #
            # Placed AFTER the filings and the news -- a published
            # result outranks a contract -- and BEFORE the gapper card,
            # because a Rs 990 crore order is a written explanation of
            # a move and the gapper table is only a table of gaps.
            or from_catalysts(symbol, on_date=on_date)
            or from_gappers(symbol)
            or ahead)


def from_catalysts(symbol, on_date=None):
    """An order win or a business update, if one landed recently.

    These are the ANTICIPATION reasons -- the ones that move a stock
    with no result anywhere near it. Weighted by the size printed on
    the card: Rs 1,918 crore and Rs 1.05 crore are not the same news.
    """
    try:
        from core import catalysts
    except Exception as exc:                               # noqa: BLE001
        return _broke("catalysts import", exc)
    when = None
    if on_date is not None:
        try:
            when = (on_date if hasattr(on_date, "hour")
                    else datetime.combine(on_date, datetime.min.time()))
        except Exception:                                  # noqa: BLE001
            when = None
    try:
        return catalysts.for_symbol(symbol, now=when)
    except Exception as exc:                               # noqa: BLE001
        return _broke("catalysts", exc)


# ==========================================================
#  THE WEIGHT WAS A NUMBER SOMEBODY TYPED
# ==========================================================
#
#     "bot is not fully equipped to find the opportunity ... u need to
#      educate & make sure bot must understand about markets"
#                                 -- operator, 19 August 2026
#
# Every weight above is hand-assigned: 0.95, 0.9, 0.85, 0.8, 0.65,
# 0.6, 0.55, 0.5. core/ranker.py multiplies one of them into every
# score it produces, and not one had ever been checked against what
# the stock then did.
#
# core/opportunity.py had measured exactly that, on stored events and
# real price history, and the answers do not agree with the typing:
#
#     ORDER_WIN          +0.64%   n=80     hand weight ~0.8
#     BUSINESS_UPDATE    -0.32%   n=123    hand weight ~0.9
#
# A business update was outranking an order win on the board while
# being worth LESS THAN NOTHING across 123 cases. That is the machine
# by which "the top-ranked three were the worst of the eleven" in the
# 8 August replay -- the bot was ranking by how important an event
# SOUNDS.
#
# The tilt is bounded, switchable and shown. See
# core/opportunity.payoff_weight() for why it stops well short of
# letting a measurement decide anything on its own.

def why(events=None, news_hits=None, on_date=None, symbol=None,
        filing=None):
    """The reason this stock is moving, weighted by what that KIND of
    reason has actually been worth.

    Same shape in and out -- {"text", "weight", "direction", "source"}
    -- so core/ranker.py needs no new field and every existing caller
    is untouched. Two fields are ADDED for the board: `payoff_mult`
    and `payoff_note`, so a ranking he disagrees with can be taken
    apart rather than trusted.

    Never raises and never blocks: any failure leaves the hand weight
    exactly as it was.
    """
    got = _why_before_payoff(events=events, news_hits=news_hits,
                             on_date=on_date, symbol=symbol,
                             filing=filing)
    if not isinstance(got, dict):
        return got
    try:
        from core.rules import RANK_BY_MEASURED_PAYOFF
        if not RANK_BY_MEASURED_PAYOFF:
            return got
        raw = got.get("weight")
        if raw is None:
            return got
        from core import opportunity
        text = str(got.get("text") or "")
        mult = opportunity.payoff_weight(text)
        if mult == 1.0:
            return got
        got["payoff_mult"] = round(mult, 3)
        got["payoff_note"] = opportunity.payoff_note(text)
        got["weight_before_payoff"] = raw
        got["weight"] = round(float(raw) * mult, 4)
    except Exception as exc:                                # noqa: BLE001
        try:
            from core.logger import diagnostic
            diagnostic(f"[WHY] payoff weighting skipped "
                       f"({type(exc).__name__}). The hand weight stands.")
        except Exception:                                   # noqa: BLE001
            pass
    return got
