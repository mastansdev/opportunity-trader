"""
==========================================================
What has happened to each stock, and when
==========================================================

    "we will use only useful news, images and store them in memory
     linked to respective stocks."       -- operator, 30 July 2026

The bot was holding 368 Telegram messages, 224 news stories and 256
images. All of it was retrievable and none of it was USABLE: to answer
"has anything happened to KAYNES this week" you had to read messages.

This is the answer to that question in a shape a machine can use. One
row per EVENT, typed, with the number pulled out:

    KAYNES    RESULT  grade=EXCELLENT                  30 Jul 13:41
    ASTRAMICRO ORDER  Rs 2,205.23 cr from HAL          30 Jul 13:47
    HFCL      ORDER   Rs 441.53 cr, optical fibre      30 Jul 11:02

WHAT COUNTS AS USEFUL
---------------------
Measured over the real store, not guessed:

    RESULT           79   a graded quarterly result
    ORDER            32   a win, a contract, an acquisition
    stock-linked     73   news naming a company we can trade
    FII/DII           5   the daily institutional flow
    calendar          5   who reports when
    ---------------------------------------------------------------
    macro            85   the Fed, the Nifty level, brokerage calls
    noise           ~30   YouTube links, tip sheets, channel chatter

MACRO IS KEPT, BUT NEVER ATTACHED TO A STOCK. A Fed hold explains why
everything moved; pinning it to six housing-finance companies is how
one headline produced 140 false links in July. It is market context and
it is stored as such -- scope MARKET, symbol NULL.

NOISE IS MARKED, NOT DELETED
----------------------------
The raw messages stay where they are. On 30 July alone the matching
rules changed three times -- the capitals rule, the lone-name rule, the
name-fragment rule -- and every change recovered links the previous one
had missed by re-reading the raw store. Delete the source and a rule
change becomes permanent data loss.

DIGESTS ARE SKIPPED ON PURPOSE
------------------------------
"Orderbook Recap -- Daily Highlights" carries eight stories in one
message. Running the extractor over it produced

    3,404.57 cr from Kuwait          (two unrelated stories, joined)
    10.00 cr from July               (a date read as a counterparty)

so a message carrying more than one story records no event at all.
Splitting them properly is its own job. A wrong number is worse than a
missing one, because a missing one looks missing.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import re

from config import DEDUPE_EVENTS
import sqlite3
import threading
from datetime import datetime, timedelta

from core.concall import is_concall_card
from core.concall import summary as concall_summary
from core.concall import read_card as read_concall_card
from core.logger import decision, diagnostic, warn
from core.ai_verdict import is_verdict_card
from core.ai_verdict import summary as verdict_summary
from core.market_sentiment import headline_for as sentiment_headline
from core.recap_card import headline_for as recap_headline
from core.recap_card import card_kind, is_recap_card, recap_date
from core.recap_card import rows_from_card as recap_rows
from core.recap_card import rows_from_grid as grid_rows
from core.recap_card import stated_count
from core.market_sentiment import is_sentiment_page
from core.market_sentiment import rows_from_page as sentiment_rows


# ---- THE SHAPE OF A TAG, 2 August 2026 ----
#
#   "Earnings Pulse & Pro both uses same format #Company name.
#    recheck & i'm 100% sure"          -- operator
#
# He was right, and the reason the counts disagreed with him was HERE.
# The pattern was r"#([A-Z][A-Z0-9&\-]{2,19})\b" -- a letter first, and
# no underscore. Measured against the real store, that silently missed:
#
#     #20MICRONS  #63MOONS  #360ONE      start with a digit
#     #M_M  #J_KBANK  #M_MFIN            the publisher writes & as _
#     #VHLTD_RE  #HCG_RE                 rights-entitlement series
#
# On every one of those the caption named the company outright and the
# rule that is supposed to make the caption final never fired, so the
# card fell through to guessing from the prose -- which is the exact
# failure the caption rule exists to prevent.
_CARD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9&_\-]{4,19}")

# Words a calendar card carries that are not companies.
_CARD_NOISE = frozenset({
    "STOCKS", "COMPANIES", "CALENDAR", "TOMORROW", "TODAY", "DURING",
    "MARKET", "HOURS", "AFTER", "BEFORE", "CLOSE", "OPEN", "MORE",
    "FORECAST", "BASED", "BEHAVIOR", "OFFICIAL", "EXCHANGE", "SLOT",
    "PULSE", "EARNINGS", "RESULTS", "PAST", "TIME", "AUGUST", "SEPTEMBER",
})


def _unplaced_names(body, rows, known):
    """Tokens on a calendar card that reached no symbol.

    A count told him a card was partial. It did not tell him whether
    that was OCR damage on a name we hold or a company the master has
    never heard of, and those need opposite fixes. See the caller.
    """
    placed = {str(r.get("symbol") or "").upper() for r in (rows or [])}
    seen, out = set(), []
    for token in _CARD_TOKEN.findall(str(body or "")):
        word = token.upper()
        if word in placed or word in _CARD_NOISE or word in seen:
            continue
        if known and word in known:
            continue
        seen.add(word)
        out.append(word)
    return out


_TAGS = re.compile(r"#([A-Z0-9][A-Z0-9&_\-]{1,19})\b")

# _RE is the rights-entitlement series of an existing scrip, not a
# different company.
_RIGHTS = re.compile(r"_RE$")


def resolve_tag(matcher, tag):
    """A publisher's tag as one of OUR symbols, or None.

    ---- NARROW ON PURPOSE. TWO WIDER RULES WERE MEASURED AND
         REJECTED THE SAME NIGHT. ----

    The obvious fix is "find the master symbol this tag looks most
    like". Run against the 29 unresolved tags it produced:

        #STARHF_RE  -> STARHEALTH     Star HOUSING Finance. Different
                                      company. A rights entitlement in
                                      a micro-cap NBFC would have been
                                      filed as Star Health, a Nifty
                                      insurer, on the panel he clicks
                                      BUY from.
        #LOTUSCHO   -> LOTUSDEV       Lotus Chocolate vs Lotus
                                      Developers. Different companies.
        #INDOBELL   -> INDOBORAX      Indobell Insulations vs Indo
                                      Borax. Different companies.

    A near-miss is not evidence. Only two substitutions are PROVABLE
    from the character set alone, because Telegram will not carry an
    ampersand in a hashtag and the publisher has to write something:

        _  ->  &        #M_M -> M&M, #J_KBANK -> J&KBANK
        strip _RE       #VHLTD_RE -> VHLTD

    Both are reversible and neither can reach a company that is not
    already the one the tag spells. Anything else returns None, and the
    card falls back to the ordinary rules rather than being filed
    against a guess.
    """
    tag = str(tag or "").upper().strip()
    if not tag:
        return None

    def real(candidate):
        if candidate == tag or not candidate:
            return None
        try:
            return candidate if candidate in set(
                matcher.symbols_in(f"#{candidate}")) else None
        except Exception:                                  # noqa: BLE001
            return None

    # The ampersand the publisher could not type.
    if "_" in tag:
        got = real(tag.replace("_", "&"))
        if got:
            return got

    # The rights-entitlement series of a scrip we already carry.
    if _RIGHTS.search(tag):
        base = _RIGHTS.sub("", tag)
        got = real(base) or real(base.replace("_", "&"))
        if got:
            return got

    return None


def symbols_first(matcher, body):
    """The ONE company a card is about, or None.

    A concall card names its company once at the top and then talks
    about customers, plants, subsidiaries and rivals in the takeaways.
    The three-name rule in events_from_message() exists because a news
    DIGEST pairs the wrong figure with the wrong company -- true of a
    digest, wrong here, and it was dropping every concall card.

    The hashtag the publisher puts in the caption is the answer when
    it is there. It is the company THEY say the card is about, and no
    amount of prose underneath changes that.
    """
    # ---- ONE TAG MEANS ONE SUBJECT. SEVERAL MEANS NONE.
    #      2 August 2026. ----
    #
    # This returned the FIRST resolvable tag, which is only correct
    # when the caption names one company. It does not always:
    #
    #     "📅 Tomorrow's Calendar - 30 Jul, 2026
    #      Key companies reporting: #BHARTIARTL #MARUTI #SUNPHARMA ..."
    #
    # On that caption the old rule answered BHARTIARTL, and because
    # events_from_message() uses this answer to NARROW a card to one
    # company, a calendar listing sixty names would have collapsed to
    # the first one. Every other company's REPORTED row would have been
    # filed against Bharti Airtel.
    #
    # The store-wide audit is what surfaced it: 386 REPORTED rows came
    # back "disagreeing with their caption", and the caption was right
    # to name many. The calendar path returns before the narrowing, so
    # nothing on disk was damaged -- but the rule was one refactor away
    # from doing it, and it silently would have.
    #
    # A caption that names several companies does not identify a
    # subject. Saying so out loud is the whole fix.
    hashed = _TAGS.findall(str(body or "").upper())
    try:
        known = set(matcher.symbols_in(" ".join(f"#{h}" for h in hashed))) \
            if hashed else set()
    except Exception:                                      # noqa: BLE001
        known = set()
    tagged = []
    for tag in hashed:
        got = tag if tag in known else resolve_tag(matcher, tag)
        if got and got not in tagged:
            tagged.append(got)
    if len(tagged) == 1:
        return tagged[0]
    if len(tagged) > 1:
        return None

    # ---- A TAG WE CANNOT RESOLVE IS STILL AN ANSWER. 2 August 2026. ----
    #
    #   "no lapse or swapping of results, investor presentations or
    #    mainly in order pulse."             -- operator
    #
    # When the publisher tagged a company and the tag resolves to
    # nothing, the honest reading is "the subject is a company we do
    # not carry" -- NOT "go and find one in the prose". The prose is
    # full of customers and counterparties. Measured on the store,
    # falling through cost 25 links, of which 19 were wrong:
    #
    #   #TAKYON  "Takyon wins Rs 14.32cr HAL IT network upgrade order"
    #                                            -> HAL      the CUSTOMER
    #   #S_SPOWER "New order over Rs 8 crore from Siemens"
    #                                            -> SIEMENS  the CUSTOMER
    #   #ORIRAIL "coach seating from Indian Railways"  -> IRFC
    #   #MODRNSH  a story about the US dollar          -> DOLLAR
    #   #MEGH     a story about Apple                  -> MOL
    #
    # Both order cases put a real order win on the wrong company's row
    # -- the exact failure he named. The six genuine losses are all a
    # tag that ABBREVIATES the same company (#DRL for DRREDDY,
    # #JAYANT for JAYAGROGN). Those are recoverable by naming them;
    # a counterparty filed as the subject is not recoverable at all,
    # because nothing downstream can tell it was wrong.
    #
    # Logged, not silent, so the abbreviations can be aliased on
    # purpose rather than guessed at.
    if hashed:
        diagnostic(f"[EVENT] caption tags {hashed[:3]} resolve to no master "
                   f"symbol -- refusing to name a company from the prose")
        return None
    # No usable hashtag. Fall back to a single unambiguous name -- and
    # refuse when there is more than one, rather than picking the first.
    try:
        found = list(dict.fromkeys(matcher.symbols_in(body)
                                   + matcher.names_in(body)))
    except Exception:                                      # noqa: BLE001
        return None
    return found[0] if len(found) == 1 else None

DB_PATH = os.path.join("data", "stock_events.db")

# ---------------------------------------------------------------
# WHAT KIND OF THING IS THIS
# ---------------------------------------------------------------
RESULT_WORDS = re.compile(
    r"(excellent|great|good|ok|weak|poor)\s+results?|"
    r"results?\s*[-:]?\s*(excellent|great|good|ok|weak|poor)|"
    r"pulse rating", re.I)

# ---------------------------------------------------------------
# THE SAME CHANNEL, THREE DIFFERENT VOCABULARIES
# ---------------------------------------------------------------
# 31 July 2026. GAIL reported. Earnings Pulse posted about it FOUR
# times in sixteen minutes, and the bot scored one of them:
#
#   08:41  #GAIL - Excellent Results          RESULT  EXCELLENT   scored
#   08:52  #GAIL - Excellent Results          RESULT  EXCELLENT   scored
#   08:54  #GAIL - Strong Beat  + the card    NEWS    (none)      ignored
#   08:57  CNBC: Net Profit 4,292 Cr          NEWS    (none)      ignored
#
# The one we ignored was the best one. The card carries the ANALYST
# ESTIMATE beside the reported number -- Sales +10%, OP +210%, PAT
# +203% against consensus -- which is information we hold nowhere else
# in this program. Our own quarterly_results compares one quarter to
# the last. It cannot tell you the market was expecting Rs 1,543 crore
# and got Rs 4,671 crore.
#
# Three formats, all from the same channel, none of them "Results":
#
#   #GAIL - Strong Beat
#   FinAI Rating : Strong Beat          (OCR reads it "FinAl", "FinA1")
#   Verdict: BEAT
#
# "ALGO PULSE" IS NOT AN EARNINGS GRADE, and reading it as one was the
# first version of this code getting it badly wrong. The card carries
# TWO independent ratings side by side:
#
#     Algo Pulse: Weak | Verdict: BEAT
#
# Algo Pulse is a price/technical read. Verdict is the quarter against
# expectations. They disagree often and legitimately -- SYRMA on 30
# July was "Algo Pulse: Weak | Verdict: BEAT" over the words "Blowout
# quarter with revenue surging 67% YoY and PAT more than doubling".
#
# Matching on "pulse" graded that blowout as WEAK. VOLTAMP's "Stellar
# margin recovery" went the same way. Both were caught in the backfill
# only because the headline sat next to the grade and read as nonsense.
# Only "Verdict" and "FinAI Rating" speak about the results.
#
# TIGHT ON PURPOSE. "beat" is an ordinary English word and a loose
# \bbeat\b would tag "Nifty beats Asian peers" as a company result.
# The word must arrive in a rating context: after a verdict label, or
# straight after the ticker dash, or beating something nameable.
_BEAT_CONTEXT = (
    r"(?:fin\s*a[il1]\s*rating|verdict|rating)\s*[:.\-]?\s*"
)
BEAT_WORDS = re.compile(
    _BEAT_CONTEXT + r"(strong\s+beat|strong\s+miss|beat|miss|met|mixed|"
    r"in\s*-?\s*line|inline|excellent|great|good|weak|poor|ok)\b"
    r"|^\s*#[A-Z0-9&\-]{2,}\s*[-–—]\s*(strong\s+beat|strong\s+miss|beat|"
    r"miss|in\s*-?\s*line|inline)\b"
    r"|\b(beat|missed|misses)\s+(?:street\s+)?"
    r"(estimates?|expectations?|consensus|forecasts?)\b",
    re.I | re.M)

# Translated into the vocabulary the score already speaks, rather than
# adding new grade names. core/shortlist.py PULSE_SCORE knows
# EXCELLENT/GREAT/GOOD/OK/WEAK/POOR; teaching it four more words would
# mean two tables that have to be kept in step, and one of them would
# drift. A beat is mapped, not invented.
BEAT_TO_GRADE = {
    "STRONGBEAT": "EXCELLENT",
    "BEAT": "GOOD",
    "INLINE": "OK",
    "IN-LINE": "OK",
    "MISS": "WEAK",
    "MISSED": "WEAK",
    "MISSES": "WEAK",
    "STRONGMISS": "POOR",
    # Earnings Pro's own two words, added 1 August 2026 after finding
    # its cards produced grade=None:
    #
    #     MARUTI  Verdict: MIXED
    #     "Revenue and PAT meet expectations, but EBITDA margins
    #      disappoint"
    #
    # MET is "exactly as expected" -- neither good nor bad news, and
    # emphatically not a beat. MIXED is the honest answer when some
    # metrics landed and others did not, which is most quarters.
    "MET": "OK",
    "MIXED": "MIXED",
}
ORDER_WORDS = re.compile(
    r"\b(wins?|won|secure[sd]?|bags?|bagged|receives?|awarded|"
    r"acquires?|acquisition|letter of intent|\bloi\b)\b", re.I)
ORDER_NOUN = re.compile(r"\b(order|contract|tender|project|deal)\b", re.I)
FLOW_WORDS = re.compile(r"fii\s*/?\s*dii|net (buyers|sellers)", re.I)
CALENDAR_WORDS = re.compile(
    r"week ahead|tomorrow'?s calendar|today earnings|earnings calendar", re.I)

# Things that are not news about a company at all. Measured off the
# real channels -- the last two are the channel owner talking about his
# own product, which is not a market event however enthusiastic.
NOISE = re.compile(
    r"youtu\.be|youtube\.com|/shorts/|"
    # ---- THREE WORDS THAT ARE ALSO FINANCE. 5 Sep 2026. ----
    #
    # Audited by asking, of each word in this rule, what it holds back
    # ON ITS OWN across all 2,016 stored messages. Three were throwing
    # away real filings:
    #
    #   subscribe   24 messages, 17 of them naming a stock, and every
    #               one real. "Subscribed" is finance vocabulary --
    #                 FLAIR WRITING: CO SUBSCRIBES TO 100 CRORE
    #                   RIGHTS ISSUE OF WHOLLY OWNED SUBSIDIARY
    #                 VODAFONE IDEA: JULY NET MOBILE SUBSCRIBER ADDS
    #                 Purple Style Labs IPO ... subscribed 24% on day
    #                   two
    #               It is narrowed to the promo phrasing, which no
    #               filing has ever used.
    #
    #   deadline    4 messages, 3 naming a stock, all real --
    #                 ARTSON LTD: RECEIVES PURCHASE ORDER WORTH
    #                   7.17 CR ... EXECUTION DEADLINES SET FOR 2027
    #                 India sets April 2027 deadline for electric
    #                   truck localisation
    #               An order win states its delivery deadline. The word
    #               was here for tax reminders, and \bitr\b already
    #               catches those, so it is gone.
    #
    #   follow us on   added earlier the same day and reverted the same
    #               hour: 84 messages, 26 naming a stock. The Day Trader
    #               Telugu cards carry "Follow us on @etnowlive" as ET
    #               Now's watermark, so it was about to throw away the
    #               Welspun MoU, the Mahanadi IPO and the Cupid promoter
    #               purchase -- the exact cards saved from the digest
    #               rule that morning. Only the wording a filing never
    #               uses survives, below.
    r"\bitr\b|recharge|must watch|"
    r"subscribe (?:to (?:our|the|my)|now|for more)|"
    r"picking window|arena|"
    r"i worked on|happy to see the validation|guys sharing|"
    # ---- THE AFFILIATE BLOCK. 2 August 2026. ----
    #
    #     "for news Day Trader Telugu is reliable + off the clickable
    #      youtube links; Insurance links; excel sheet links from this
    #      channel"
    #
    # The channel pays for itself with referral links -- term and
    # health policies, and a row of broker sign-ups:
    #
    #     "Support Our Work  1Cr Best Term Policy: bit.ly/_Term_Policy"
    #     "ZERODHA: bit.ly/_ZERODHA_  ANGEL ONE: a.aonelink.in/ANGOne/"
    #
    # These three patterns were picked by MEASURING them against all
    # 3,135 stored messages, not by reading one post:
    #
    #     support our work    2 hits, Day Trader Telugu only
    #     bit.ly/_            4 hits, Day Trader Telugu only
    #     aonelink.in         2 hits, Day Trader Telugu only
    #
    # WHAT WAS TRIED AND REJECTED. "term policy|health policy" caught
    # five -- and one of them was an Earnings Pro expectations page
    # that names a listed insurer. HDFCLIFE, SBILIFE, ICICIGI, LICI
    # and STARHEALTH are STOCKS. A filter on the word "insurance"
    # would silently drop their results, which is the opposite of the
    # job. So the patterns match the AFFILIATE SHAPE -- his own
    # shortener prefix, his own referral host -- and nothing else.
    r"support our work|bit\.ly/_|aonelink\.in|"
    # ---- THE CHANNEL ADVERTISING ITSELF. 5 September 2026. ----
    #
    #     "we made that to avoid links from that channel right?
    #      forgot again??"   "not now since begining"
    #                                          -- the operator
    #
    # He was right, and twice over. This rule has been here since
    # 2 August and it works -- there are ZERO events of kind NOISE on
    # file, so not one of these has ever reached a stock. A second
    # rule was written on 5 September before checking, and measured
    # against all 2,016 stored messages it caught 17 this one already
    # had and 52 fewer besides. It was deleted; these four lines are
    # everything it actually added.
    #
    # RedboxGlobal India advertising its own social accounts:
    #
    #     "WE'RE NOW LIVE ON INSTAGRAM! Get market-moving news
    #      before everyone else."
    #     "We're building something bigger on Facebook."
    #
    # Four messages, no stock named in any of them. The hosts are
    # matched as well as the wording, because the next one will be
    # phrased differently and still link to the same place.
    # Measured: these four catch all four self-promos and cost nothing.
    # "follow us on" alone does not appear -- see the note above.
    r"we'?re now live on|building something bigger|"
    r"(?:follow|join) us on (?:instagram|facebook)|"
    r"instagram\.com|facebook\.com|fb\.watch", re.I)

# An analyst's opinion is not an event. It may be worth reading and it
# is not something that HAPPENED to the company.
OPINION = re.compile(r"brokerage call|stock pick|recommend|target price|"
                     r"'?(buy|sell|hold|underperform|outperform)'? rating", re.I)

# More than one story in one message. See the module docstring.
# ---- A SECTOR NOTE IS ABOUT THE MARKET, NOT A COMPANY. ----
#                                     5 September 2026.
#
#     "this 'SECTORS TO WATCH OMCs, Paint, Aviation...' statement is
#      generalised one which suit the whole market regime. if war news
#      or trump statement & escalation then whole market regime will
#      shift & crude price surge damages the sectors mentioned omcs,
#      paints, aviation. if de-escalates this statement is positive.
#      whats so complex in this?"                 -- the operator
#
# Nothing, and the publisher says so in the heading. This message:
#
#     SECTORS TO WATCH OMCs, Paint, Aviation-Oil Declines For 3rd
#     Session  Cochin Shipyard, Mazgaon Dock, GRSE-India plans to add
#     100 new vessels  Block Deal Today-Groww, Welspun Corp...
#
# is three stories about a dozen companies, and it was filed as NEWS
# against COCHINSHIP, ATULAUTO, ASHOKLEY and WELCORP -- one event
# each, as though somebody had published something about that company.
#
# is_digest() missed it because the companies are named in plain
# English rather than as #TICKERS, so the three-ticker test found
# none, and "sectors to watch" was not among the headings that mark a
# roundup. Six events across four stocks.
#
# WHY IT MATTERS BEYOND SIX ROWS: a regime note is not evidence about
# one company. Crude rising is bad for OMCs, paints and aviation
# TOGETHER, and good for them together when it falls. Reading it as
# "something was published about WELCORP" is the same mistake as
# reading a takeover as a promoter dumping stock -- text about the
# market, filed as text about a company.
#
# A single-company story is untouched: "STSCK IN NEWS WELSPUN CORP Co
# & Perma-Pipe sign MoU" carries no roundup heading and still files.
DIGEST = re.compile(r"recap|daily highlights|stocks in (news|focus)|"
                    r"top \d+|\bhighlights\b|earnings & results|"
                    r"editors'? *picks|the week ahead|"
                    r"sectors? to watch", re.I)

# A bullet list is a digest whatever it calls itself. The first run
# recorded "Crocs Inc. reported Q2 FY26 revenue of $1.18 billion" against
# MAHLIFE and SWIGGY, with Rs 10,384 cr attached, because one message
# carried eight bulleted stories and the extractor took the first number
# it found and the symbols the whole message had accumulated.
_BULLETS = re.compile(r"[•]\s+|^\s*[\-\*]\s+", re.M)
_TICKERS = re.compile(r"#[A-Z][A-Z0-9&\-]{2,}")

# ---- A ROUNDUP STARTS EACH LINE WITH A NEW SUBJECT ----
#                                        5 September 2026.
#
# Day Trader Telugu's morning roundup, as the reader sees it:
#
#     Stocks in News
#     KPI Green - CFO Salim Yahoo ceases as CFO and KMP from Sept 2
#     KSH Intl. - Received Unit 3 factory licence renewal till 2030
#     FACT - Received communication from the Chemicals Ministry
#
# Three companies, three stories, and NOT ONE of the signals already
# here fires: no bullets, no #tickers, no emoji. Measured on the store,
# eight such messages were caught by the heading alone -- "stocks in
# news" -- which is the thread the whole thing was hanging by.
#
# This counts the shape instead: a short Capitalised name, a dash or a
# colon, then a real sentence. Two of them is a roundup whatever the
# heading says, and a card has none -- measured, 0 of 108.
_LEDES = re.compile(
    r"^[ \t]*([A-Z][A-Za-z&.'()/-]*(?:[ ][A-Z0-9][A-Za-z&.'()/-]*){0,4})"
    r"[ \t]*[-\u2013\u2014:][ \t]+(?=[A-Za-z(])(?=.{12,})",
    re.M)

# News Pulse separates stories with a leading emoji rather than a bullet
# or a heading, so a single post can carry six unrelated items:
#
#   "IRAN'S IRGC: TARGETED US BASE ... | The Bank of England is widely
#    expected to maintain interest rates ... | ByteDance has
#    restructured its AI business ..."
#
# TORNTPOWER was recorded against a Strait of Hormuz story that way.
# Three or more of these markers means several stories, whatever the
# post calls itself.
_STORY_MARKS = re.compile(
    "[\U0001F4CC\U0001F6E2\U0001F1EE\U0001F1F3\U0001F4C8\U0001F4CA"
    "\U0001F30D\U0001F680\U0001F4B1\u26FD\U0001F3E6\u2B50]")

# ---- THE CURRENCY MARKER WAS MANDATORY. 22 August 2026. ----
#
# This required ₹ / rs / inr / usd / $ BEFORE the number, and the
# channels do not write one:
#
#     POWERGRID   "CO HAS WON LARGE ORDER WORTH 26000 CRS"
#     ASTRAMICRO  "wins order worth RUPEES 2205 CR"
#     WELCORP     "INVESTOR CALL ON 217,200 CR ORDER"
#
# So value_cr was read off barely half the ORDER events, and the bot
# could not tell a transformative order from a routine one -- the
# operator's point on 22 August, and he was right.
#
# The marker is OPTIONAL now and the UNIT is REQUIRED. That is not a
# loosening: amount_in_crore() already did `continue` on a match with
# no unit ('a bare number is not an amount'), so requiring it here
# changes nothing except where the decision is made. 'rupees' spelled
# out is recognised; 'crs' already was, via cr(?:ore)?s?.
#
# USD still detected the same way -- a bare figure has no prefix, so
# dollars stays False and it is read as rupees, which is correct.
AMOUNT = re.compile(r"""(?:(?:₹|rs\.?|inr|rupees|usd|\$)\s*)?
                        ([\d,]+(?:\.\d+)?)\s*
                        (cr(?:ore)?s?|lakhs?|mn|million|bn|billion)""",
                    re.I | re.X)
COUNTERPARTY = re.compile(r"\bfrom\s+((?:[A-Z][\w&.\-]*\s+){0,4}[A-Z][\w&.\-]*)")
GRADE = re.compile(r"(excellent|great|good|weak|poor|ok)", re.I)

# Only to make a dollar figure comparable to a rupee one. Approximate on
# purpose -- it is used for ORDERING events by size, never for maths
# anybody trades on.
USD_INR = 88.0

KINDS = ("RESULT", "ORDER", "FILING", "NEWS", "FLOW", "CALENDAR",
         "MACRO", "OPINION", "NOISE")


def is_digest(text, companies=None):
    """More than one story in one message.

    Four signals, any of which is enough: it calls itself a recap, it is
    a bullet list, it separates stories with emoji, or two of its lines
    START a new subject ("KPI Green - CFO ceases"). Plus the oldest and
    most reliable: three or more different tickers.

    ==============================================================
    ONE COMPANY IS NOT A ROUNDUP.  5 September 2026.
    ==============================================================

        "for me all info must be tagged properly & never mis ,
         duplicate , thats it"                    -- the operator

    `companies` is how many companies the caller RESOLVED in this
    message. Given it, a message about ONE company is never a roundup,
    whatever it looks like -- and that closes a trap that was one
    settings change away from going off.

    THE TRAP. Day Trader Telugu posts single-company cards that the
    picture-reader currently transcribes as:

        STSCK IN NEWS  VEDANTA  e Reappoints Arun Misra as Executive
        Director  e Vedanta Semiconductors...

    108 of them on record. Two things about that text are accidents:
    "STSCK" is a misread of STOCKS, and those "e" characters are
    bullets the reader could not resolve. Both accidents are the only
    reason the cards survive today -- "stocks in news" IS in DIGEST,
    and two bullets IS a roundup by the rule above.

    Improve the reading -- one API key does it -- and the heading and
    the bullets both resolve, all 108 become "roundups", and every
    single-company story from that channel is refused. Silently. No
    error, no log line. Vedanta, Tata Power, JSW Energy, United
    Spirits, Zee: gone from the door that decides what the bot may even
    look at.

    WHY THE COUNT IS THE RIGHT TEST. Measured through the live path on
    5 September, with the refusal disabled so it reported what it FOUND:

        the 9 roundups   ->  8 of them name 0 companies, 1 names 2
        the 108 cards    ->  1 company each

    A card names its company once, at the top, and every bullet after
    is about that same company. Bullets, headings and emoji are
    decoration; the number of subjects is the thing itself.

    THE TWO GUARDS ON THE ESCAPE, because a roundup can resolve to one
    company by accident -- eight stories of which only SWIGGY is a name
    the bot knows, which is exactly how a Crocs revenue figure was once
    filed against Swiggy:

      1. no lede structure. Two lines that each start a new subject
         means several stories even if only one name resolved.
      2. the company must be named EARLY -- in the first 120
         characters. A card's subject is its heading. A name buried in
         the middle of a list is a mention, not a subject.

    Without `companies` this behaves exactly as it did before, so
    tools/ and every existing caller are unaffected.
    """
    body = text or ""
    # EXACTLY ONE, never zero. A message the bot cannot name a company
    # in is not a card -- it is a message about something that could not
    # be identified, and tests/test_expectation_page.py caught the
    # difference the moment this was written too loosely: a recap of
    # #AAA, #BBB and #CCC resolves to NO master symbol, and letting it
    # through filed "Daily Highlights #AAA wins an order #BBB reports
    # results" as a single ORDER event with no company on it. Zero is
    # not one. The escape exists to protect a subject, so there has to
    # be a subject.
    if companies == 1 and len(_LEDES.findall(body)) < 2:
        return False
    if DIGEST.search(body):
        return True
    if len(_BULLETS.findall(body)) >= 2:
        return True
    if len(_STORY_MARKS.findall(body)) >= 3:
        return True
    if len(_LEDES.findall(body)) >= 2:
        return True
    return len(set(_TICKERS.findall(body))) >= 3


def amount_in_crore(text):
    """The first money figure, normalised to crore rupees.

    Returns None rather than guessing. A message with no number is
    common and perfectly fine -- "wins optical fibre export order" is
    still an order.
    """
    for match in AMOUNT.finditer(text or ""):
        try:
            value = float(match.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
        unit = (match.group(2) or "").lower()
        dollars = bool(re.match(r"(usd|\$)", match.group(0), re.I))
        if unit.startswith("cr"):
            crore = value
        elif unit.startswith("lakh"):
            crore = value / 100.0
        elif unit in ("mn", "million"):
            crore = value * (USD_INR / 10.0 if dollars else 0.1)
        elif unit in ("bn", "billion"):
            crore = value * (USD_INR * 100.0 if dollars else 100.0)
        else:
            continue                      # a bare number is not an amount
        return round(crore, 2)
    return None


# ---------------------------------------------------------------
# WHAT THE MARKET WAS EXPECTING
# ---------------------------------------------------------------
# The single most valuable thing in the FinAI card, and the one piece
# of information this program has no other way of getting.
#
# core/quarterly_results.py compares this quarter to the last one. It
# can tell you GAIL's PAT went from 1,482 to 4,671 crore. It cannot
# tell you the street was expecting 1,543 -- and "tripled" versus
# "tripled when nobody saw it coming" are different trades.
#
# The card lays it out in a fixed grid:
#
#   Metric  QoQ   YoY  Jun'26    Est      dEst   Mar'26  Jun'25
#   Sales   16%   17%  41350.2   37688.3  +10%   35,706  35,429
#   OP     388%   93%   7097.9    2287.7  +210%   1,454   3,669
#   PAT    215%   96%   4671.0    1543.9  +203%   1,482   2,382
#
# Read from OCR, so it must survive OCR: the real card says "OP" and
# Tesseract returned "oP"; "ΔEst" came back as "AEst". Nothing here
# depends on the header row -- only on the shape of a metric line.
_ESTIMATE_ROW = re.compile(
    r"^\s*(sales|revenue|op|ebitda|pat|profit)\b[^\n\d]{0,4}"
    r"([-+]?[\d.]+)\s*%\s+"          # QoQ
    r"([-+]?[\d.]+)\s*%\s+"          # YoY
    r"([\d,]+(?:\.\d+)?)\s+"         # reported
    r"([\d,]+(?:\.\d+)?)\s+"         # estimate
    r"([-+]?[\d.]+)\s*%",            # versus estimate
    re.I | re.M)

_METRIC_NAME = {"sales": "Sales", "revenue": "Sales", "op": "OP",
                "ebitda": "OP", "pat": "PAT", "profit": "PAT"}


def estimate_beat(text):
    """Reported-versus-expected, per metric, from a FinAI card.

    Returns {"Sales": {...}, "OP": {...}, "PAT": {...}} or {} when the
    text is not a card. Never guesses: a row that does not have all six
    numbers in the right order is skipped rather than half-read.
    """
    out = {}
    for row in _ESTIMATE_ROW.finditer(text or ""):
        name = _METRIC_NAME.get(row.group(1).lower())
        if not name or name in out:
            continue
        try:
            reported = float(row.group(4).replace(",", ""))
            estimate = float(row.group(5).replace(",", ""))
            printed = float(row.group(6))
        except (TypeError, ValueError):
            continue

        # ---- COMPUTE THE SURPRISE, DO NOT READ IT ----
        #
        # DIVISLAB, 1 August 2026. The card printed
        #
        #     Sales  3080  2785.8  +11%
        #     PAT     902   744    +21%
        #
        # and Tesseract read the PLUS SIGN AS A FOUR:
        #
        #     Sales 9% 28% 3080 2785.8 411% 2,831 2,410
        #     PAT   20% 66% 902 744    421% 751 545
        #
        # So the chip said "PAT +421% vs est" -- a plausible-looking,
        # completely wrong figure on the operator's screen, which is
        # the one thing this program must never produce.
        #
        # The percentage is derivable from two numbers that OCR reads
        # reliably, because they are plain digits with no glyph a "4"
        # can be confused with. 902/744 - 1 = 21.2%. So it is worked
        # out rather than trusted.
        #
        # The printed value is still read, and used only to CHECK: when
        # the two disagree badly the row was mis-scanned somewhere
        # else, and the whole row is dropped rather than half-believed.
        if estimate <= 0:
            continue
        computed = (reported / estimate - 1.0) * 100.0

        # The printed figure is a CHECK on the two numbers above it,
        # not the answer. It agrees, or it is the known "+ read as 4"
        # mangling, or the row was scanned wrong somewhere and is
        # dropped.
        p, c = abs(printed), abs(computed)
        agrees = abs(c - p) <= max(8.0, c * 0.15)
        # "+11%" comes back as "411%" -- the plus becomes a four, so
        # the printed number ENDS with the real one. Recognised
        # explicitly rather than treated as a disagreement, because
        # rejecting it threw away two correct rows out of three on
        # DIVISLAB.
        plus_as_four = (p > c and
                        str(int(round(p))).endswith(str(int(round(c)))))
        if not (agrees or plus_as_four):
            diagnostic(f"[CARD] {name}: printed {printed:+.0f}% but "
                       f"{reported} against {estimate} is "
                       f"{computed:+.1f}% -- row not used.")
            continue

        out[name] = {
            "qoq_pct": float(row.group(2)),
            "yoy_pct": float(row.group(3)),
            "reported": reported,
            "estimate": estimate,
            "vs_estimate_pct": round(computed, 1),
        }
    return out


def estimate_summary(text):
    """One line for the dashboard, or None.

    "PAT +203% vs est, OP +210% vs est" says more in eight words than
    "Strong Beat" does, and it is checkable -- the operator can put the
    number against the card he is looking at.
    """
    beats = estimate_beat(text)
    if not beats:
        return None
    parts = [f"{m} {beats[m]['vs_estimate_pct']:+.0f}% vs est"
             for m in ("PAT", "OP", "Sales") if m in beats]
    return ", ".join(parts) or None


# ---------------------------------------------------------------
# THE TALLY AGAINST EXPECTATIONS
# ---------------------------------------------------------------
# The single most useful thing in any channel the operator follows,
# and it was being read by nothing. An Earnings Pro card carries:
#
#     Tally Against Expectations
#     THEME              STATUS   DETAILS
#     Revenue            MET      within the expected 51,400-52,600 cr
#     Net Profit (PAT)   MET      meeting the 3,345-3,791 cr expectation
#     EBITDA Margin      MISS     8.2% vs the expected 9.8% to 10.4%
#
# PER METRIC, against WHAT WAS EXPECTED. Nothing else we hold does
# that. core/quarterly_results.py computes growth -- this says whether
# growth was enough.
#
# WHY IT MATTERS, IN ONE STOCK
# ----------------------------
# APTUS, 31 July 2026. Our arithmetic: "STRONG: sales +15% YoY, PAT
# +19% YoY". The market: -5.77%. Both facts, and the second one is
# what the operator's money cared about. Growth was real and it was
# not what the quarter was about -- provisions doubled.
#
# MARUTI on this card is the same shape said out loud: Revenue MET,
# PAT MET, EBITDA Margin MISS, verdict MIXED. A grader reading only
# revenue and profit would have called it fine.
_TALLY_ROW = re.compile(
    r"^\s*([A-Za-z][A-Za-z()/ &.%-]{2,38}?)\s+"
    r"(BEAT|MET|MISS|MISSED|IN[- ]?LINE)\b",
    re.M)

# Only the themes a statement actually reports on. Without this the
# pattern would also catch prose lines that happen to end in a capital
# word before "MET".
_TALLY_THEMES = re.compile(
    r"revenue|sales|pat|profit|ebitda|margin|volume|guidance|order|"
    r"asset\s+quality|nim|nii|provision|subscriber|arpu|realisation",
    re.I)


def expectation_tally(text):
    """{"Revenue": "MET", "EBITDA Margin": "MISS", ...} or {}.

    Reads the Tally Against Expectations block of an Earnings Pro card.
    Returns {} for anything that is not one -- most messages are not.
    """
    out = {}
    for match in _TALLY_ROW.finditer(text or ""):
        theme = " ".join(match.group(1).split())
        if not _TALLY_THEMES.search(theme):
            continue
        status = match.group(2).upper().replace(" ", "-")
        if status == "MISSED":
            status = "MISS"
        out.setdefault(theme[:40], status)
    return out


def tally_summary(text):
    """One line for the dashboard, or None.

    "2 MET, EBITDA Margin MISS" tells the operator in five words the
    thing that took an evening to work out about APTUS: which part of
    the quarter fell short.
    """
    tally = expectation_tally(text)
    if not tally:
        return None
    missed = [k for k, v in tally.items() if v == "MISS"]
    beat = [k for k, v in tally.items() if v == "BEAT"]
    met = sum(1 for v in tally.values() if v in ("MET", "IN-LINE"))
    bits = []
    if beat:
        bits.append("BEAT " + ", ".join(beat[:2]))
    if met:
        bits.append(f"{met} met")
    if missed:
        # Named, always. "One metric missed" is useless; "EBITDA
        # Margin MISS" is the whole story.
        bits.append("MISS " + ", ".join(missed[:2]))
    return " | ".join(bits) or None


# ---------------------------------------------------------------
# THE EARNINGS BRIEF -- "can this quarter be trusted?"
# ---------------------------------------------------------------
#     "the ultimate motive is to gather full confidence, evidence, & in
#      why i must see before buying any share even a 1 stock share
#      also"                          -- operator, 1 August 2026
#
# Earnings 360 and Earnings Pro publish a one-page brief per result,
# and it answers questions this bot cannot ask of a filing:
#
#     GROWTH    Rising        EARNINGS QUALITY   CLEAN
#     MARGINS   Expanding     DISTORTION FLAGS   forex loss Rs 7 Cr
#     CASH FLOW Healthy       RED FLAGS          none flagged
#     QUALITY   Excellent     IMPLIED OUTLOOK    strong start to FY27
#
# core/quarterly_results.py reads sales and profit. It cannot see a
# margin, a cash flow, or a one-off -- so it graded APTUS STRONG on
# +19% YoY profit on a day the stock fell 5.77% because provisions had
# doubled. These four gauges are precisely that blind spot, already
# arriving, already stored: 22 such cards were sitting in telegram.db
# unread when this was written.
#
# OCR MANGLES THE ICONS, NOT THE WORDS. The real card prints arrows
# and ticks which come back as "t Rising", "+ Expanding", "ge Healthy".
# So every pattern here matches the WORD and ignores whatever sits in
# front of it.
# ---- THE VALUES ARE ON THEIR OWN LINE, AND THE FIRST VERSION OF
#      THIS DID NOT KNOW THAT. 1 August 2026. ----
#
# The card prints a header row and then the readings under it:
#
#     GROWTH MARGINS CASH FLOW QUALITY
#     Rising Expanding Healthy Excellent
#
# The first patterns here allowed 80 characters of ANY character
# including newlines between the label and the value. On a card whose
# value row OCR'd badly, "CASH FLOW" matched the word "weak" from a
# completely different section further down the page -- and produced
#
#     WATCH: margins Compressing, cash flow Weak, quality Weak
#
# on a card the channel itself had marked GREEN. A false warning is
# worse than no warning: it is the same confident-wrong-answer failure
# as reading a filing's columns out of alignment, and it would have
# talked the operator out of a good trade.
#
# So the reading must sit on the label's OWN line, or on the line
# directly beneath it. Nothing else is accepted, and a card whose
# value row is unreadable yields nothing at all.
_GAUGE_WORDS = {
    "growth": ("rising", "improving", "falling", "declining", "flat",
               "stable", "slowing"),
    "margins": ("expanding", "improving", "contracting", "compressing",
                "stable", "flat", "declining"),
    # "concern" is the card's own word and it was being missed, so the
    # reading fell through to "weak" borrowed from the QUALITY column
    # one place to the right -- right direction, wrong column.
    "cash_flow": ("healthy", "strong", "weak", "poor", "negative",
                  "concern", "stable", "improving"),
    "quality": ("excellent", "great", "good", "fair", "weak", "poor",
                "clean"),
}
_GAUGE_LABELS = (
    ("growth", re.compile(r"\bGROWTH\b", re.I)),
    ("margins", re.compile(r"\bMARGINS?\b", re.I)),
    ("cash_flow", re.compile(r"\bCASH\s*FLOW\b", re.I)),
    ("quality", re.compile(r"\bQUALITY\b", re.I)),
)

# ONE-OFF WAS NOT IN THIS LIST AND IT IS THE ONE THAT MATTERS.
# 1 August 2026, CDSL Q1 FY27. The card read
#
#     EARNINGS QUALITY | ONE-OFF
#     PAT driven by one-off dividend
#
# and the pill above it said GREAT. PAT printed 118 Cr, +15% YoY --
# except 39.5 Cr of it was a dividend from the subsidiary. Take that
# out and the quarter earned roughly 78 Cr against 102 Cr a year
# before. The +15% headline is the number that puts a stock in the
# gainers list; the one-off is the reason it is there.
_EARNINGS_QUALITY = re.compile(
    r"EARNINGS\s*QUALITY\b\W{0,6}"
    r"(CLEAN|MIXED|POOR|WEAK|DIRTY|ONE-?OFF|DISTORTED|ADJUSTED)\b", re.I)

# What the model should treat as a warning. "None flagged" and an
# empty section both mean nothing is wrong, and both are common.
# ---- THE OCR EATS THE SPACE AFTER "No". 1 August 2026. ----
#
# Read off the 25 briefs actually stored, the card's all-clear line
# comes back as any of:
#
#     Noexceptional items in Q1 FY27
#     Noone-off items apparent
#     Nosignificant one-off distortions
#     No material one-off items
#
# The first three were being filed as FLAGGED ONE-OFFS -- a card
# saying nothing is wrong, turned into a warning chip. Every "no" here
# therefore allows zero spaces after it.
_NOTHING_FLAGGED = re.compile(
    r"none\s*flagged|nothing\s*flagged|numbers\s*hold\s*up|not\s+apparent|"
    r"\bno\s*(significant|material|exceptional|major|unusual|one-?off|"
    r"red\s*flag|distortion)", re.I)

# An amount overrides the all-clear. "No significant one-off items,
# but a forex loss of Rs 400 Cr" says both things, and the 400 Cr is
# the half worth reading -- so a line carrying a figure is kept even
# when it opens with a reassurance.
_HAS_AMOUNT = re.compile(
    r"(?:Rs\.?|₹|INR)\s*[\d,]|"
    r"\b[\d,]+(?:\.\d+)?\s*(?:cr\b|crore|lakh|bn\b|mn\b)", re.I)

_BAD_GAUGE = {"falling", "declining", "slowing", "contracting",
              "compressing", "weak", "poor", "negative", "fair"}


def quality_signals(text):
    """The four gauges and the trust flags from an earnings brief.

    Returns {} when the text is not one of these cards, which is most
    messages.
    """
    body = text or ""
    if not re.search(r"EARNINGS\s*QUALITY|DISTORTION\s*FLAGS", body, re.I):
        return {}

    out = {}
    lines = body.splitlines()
    for index, line in enumerate(lines):
        for key, label in _GAUGE_LABELS:
            if key in out or not label.search(line):
                continue
            # The label's own line first (some cards print
            # "GROWTH Rising"), then the line directly below it, which
            # is where a four-column header puts its readings.
            for candidate in (label.sub(" ", line),
                              lines[index + 1] if index + 1 < len(lines)
                              else ""):
                hit = next((w for w in _GAUGE_WORDS[key]
                            if re.search(rf"\b{w}\b", candidate, re.I)), None)
                if hit:
                    out[key] = hit.title()
                    break

    # A four-column header row with an unreadable value row gives one
    # or two readings out of four. That is a half-read card, and half a
    # card is how the false "cash flow Weak" was produced -- so unless
    # the row was read properly, none of it is reported.
    header = re.search(r"GROWTH\s+MARGINS\s+CASH\s*FLOW\s+QUALITY",
                       body, re.I)
    if header and len(out) < 3:
        out = {}

    quality = _EARNINGS_QUALITY.search(body)
    if quality:
        # "ONEOFF" and "ONE-OFF" are the same reading; the hyphen is
        # whatever the OCR felt like that day.
        word = quality.group(1).upper().replace("-", "")
        out["earnings_quality"] = "ONE-OFF" if word == "ONEOFF" else word
    return out


def quality_summary(text):
    """One line, and it leads with whatever is WRONG.

    A brief that is entirely positive says so in four words. One that
    is not names the problem, because that is the line that stops a
    purchase -- and stopping one is worth more than confirming ten.
    """
    signals = quality_signals(text)
    if not signals:
        return None
    bad = [f"{k.replace('_', ' ')} {v}" for k, v in signals.items()
           if str(v).lower() in _BAD_GAUGE]
    if bad:
        return "WATCH: " + ", ".join(bad[:3])
    if signals.get("earnings_quality") and \
            signals["earnings_quality"] != "CLEAN":
        return f"WATCH: earnings quality {signals['earnings_quality']}"
    parts = [v for k, v in signals.items() if k != "earnings_quality"]
    clean = signals.get("earnings_quality") == "CLEAN"
    if not parts:
        return "earnings quality CLEAN" if clean else None
    return ("CLEAN | " if clean else "") + ", ".join(parts[:3])


# ---------------------------------------------------------------
# THE CARD'S OWN WARNING, WHICH WAS BEING THROWN AWAY
# ---------------------------------------------------------------
#     "as a human we cannot grasp all image data & trade decision
#      right? bot will fill that gap by giving me correct info rather
#      than pasting simple chips at why"
#                                    -- operator, 1 August 2026
#
# CDSL, Q1 FY27, 1 August 2026. Two cards, same company, same minute:
#
#     EARNINGS BRIEF   GREAT
#     FinAI grid       Pulse Rating: Weak
#
# The panel showed one chip -- "PULSE: Weak results" -- and the
# operator had no way to know the two disagreed, or why. Meanwhile the
# brief carried the answer in its own footer:
#
#     CAN EARNINGS BE TRUSTED?
#     Headline is misleading; standalone operating profit fell
#     despite revenue growth.
#
#     DISTORTION FLAGS  ACCOUNTING - ONE-OFFS
#     Dividend income from subsidiary: Rs 39.5 Cr
#
# That is not a label. It is the fact that decides the trade, and it
# was sitting in the picture unread. A chip saying "Weak results"
# tells the operator nothing he can act on; a chip saying "ONE-OFF:
# dividend from subsidiary Rs 39.5 Cr" tells him the whole story in
# the width the panel already has.
#
# WHAT THIS DELIBERATELY DOES NOT DO. It does not decide whether the
# quarter was good. It repeats what the channel published, in the one
# place the operator is looking. Which of the two cards is right is
# outcome tracking's question, not this file's.

# The cards print these headings in caps, one per section, often with
# a bullet glyph or an OCR'd icon in front.
_SECTION_HEADS = re.compile(
    r"^[\s\W]{0,4}("
    r"PERFORMANCE\s+DRIVERS|SEGMENT\s+REALITY|MARGIN\s+DRIVERS|"
    r"BALANCE\s+SHEET\s+SIGNALS|EARNINGS\s+QUALITY|DISTORTION\s+FLAGS|"
    r"RED\s+FLAGS|IMPLIED\s+OUTLOOK|CAN\s+EARNINGS\s+BE\s+TRUSTED"
    r")\b", re.I | re.M)

# The footer, which is not part of the last section.
_BRIEF_FOOTER = re.compile(
    r"earnings\s*pulse\.ai|AI-generated\s+summary|Full\s+analysis|"
    r"Not\s+investment\s+advice|Verify\s+with\s+official", re.I)


def _sections(text):
    """{HEADING: body} for an earnings brief. {} for anything else."""
    body = text or ""
    marks = list(_SECTION_HEADS.finditer(body))
    if not marks:
        return {}
    out = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        chunk = body[mark.end():end]
        stop = _BRIEF_FOOTER.search(chunk)
        if stop:
            chunk = chunk[:stop.start()]
        # The heading's own trailing words are a sub-label the card
        # prints in grey -- "ACCOUNTING - ONE-OFFS", "NUMERICAL /
        # STRUCTURAL". They are not content.
        key = re.sub(r"\s+", " ", mark.group(1)).upper()
        out[key] = chunk.strip()
    return out


# Words that mean the card is warning about its own headline. The
# whole point of the section is that the printed number is not the
# number to trade on.
_TRUST_DOUBT = re.compile(
    r"mislead|overstat|understat|flatter|inflat|distort|one-?off|"
    r"boosted\s+by|propped|mask|optical|cosmetic|caution|"
    r"not\s+(fully\s+)?(sustainab|reliab|represent|compar)|"
    r"driven\s+by\s+(other|non-?operat)", re.I)

_TRUST_OK = re.compile(
    r"numbers\s+hold\s+up|can\s+be\s+trusted|no\s+(material\s+)?distort|"
    r"clean\s+quarter|genuinely|broadly\s+reliab", re.I)


def _tidy(line):
    """One printed bullet, with the card's glyphs taken off the front."""
    text = re.sub(r"^[\s\W]{0,6}", "", line or "")
    return re.sub(r"\s+", " ", text).strip(" .;-")


def trust_verdict(text):
    """The card's answer to "can earnings be trusted?".

    {"trusted": bool, "note": str} or None when the card did not print
    the section -- which is most cards, and is not a reason to worry.
    """
    section = _sections(text).get("CAN EARNINGS BE TRUSTED")
    if not section:
        return None
    note = " ".join(_tidy(ln) for ln in section.splitlines() if _tidy(ln))
    note = note.strip()
    if not note or len(note) < 12:
        return None
    doubt = bool(_TRUST_DOUBT.search(note))
    if doubt and _TRUST_OK.search(note) and not re.search(
            r"mislead|overstat|distort", note, re.I):
        doubt = False
    return {"trusted": not doubt, "note": note[:180]}


def distortion_flags(text):
    """The one-off items the card flagged, each with its amount.

    [] when the section is absent or says nothing was found -- and
    "none flagged" is common and genuinely means nothing is wrong.
    """
    section = _sections(text).get("DISTORTION FLAGS")
    if not section:
        return []
    items = []
    for line in section.splitlines():
        item = _tidy(line)
        # A bare sub-label carried down from the heading row, and the
        # page furniture. Neither is a flagged item.
        if len(item) < 8 or re.fullmatch(
                r"[A-Z\s/&·\-]+", item) or re.match(
                r"\d{1,2}\s+\w{3}\s+20\d\d", item):
            continue
        # ---- TESTED PER LINE, NOT PER SECTION. 1 August 2026. ----
        #
        # This used to drop the WHOLE section the moment any line said
        # "no one-off items". A card listing one reassurance and one
        # real flag would then show neither -- the exact failure this
        # function exists to prevent, with the evidence deleted rather
        # than merely unread.
        if _NOTHING_FLAGGED.search(item) and not _HAS_AMOUNT.search(item):
            continue
        items.append(item.replace("₹", "Rs ").replace("  ", " ")[:90])
    return items[:3]


def trust_summary(text):
    """One line for the chip, carrying the FACT rather than a label.

    Ordered by what the operator can act on. "Dividend income from
    subsidiary: Rs 39.5 Cr" is a number he can subtract; "earnings
    quality ONE-OFF" is a word he cannot.
    """
    verdict = trust_verdict(text)
    flags = distortion_flags(text)
    quality = quality_signals(text).get("earnings_quality")
    suspect = quality in ("ONE-OFF", "DISTORTED", "ADJUSTED", "MIXED",
                          "POOR", "WEAK", "DIRTY")

    if not (flags or suspect or (verdict and not verdict["trusted"])):
        return None
    if flags:
        return f"ONE-OFF: {flags[0]}"
    if verdict and not verdict["trusted"]:
        return f"NOT CLEAN: {verdict['note'][:70]}"
    return f"NOT CLEAN: earnings quality {quality}"


# ---------------------------------------------------------------
# WHAT WAS PRICED IN, BEFORE THE RESULT
# ---------------------------------------------------------------
#     "None of it knows what the market already expected? we have
#      covered by one of our pro channel right? every thing in one
#      page"                          -- operator, 1 August 2026
#
# He was right and it was already arriving. Earnings Pro publishes a
# "Pre-Earnings Market Expectations" page before each session:
#
#     CLEAN BULLISH
#     Steady volume growth in high-margin HALS and backward
#     integration support mid-single digit profit expansion.
#     - Q1 FY27 Revenue estimated at ~264 cr (+8.5% YoY), PAT at ~74 cr
#
#     APLAPOLLO NEUTRAL
#     Volume contraction tests full-year growth guidance.
#
#     AMJLAND BEARISH
#     Market sentiment remains weak with a 'Sell' rating amid lack of
#     specific forward guidance.
#
# A stance, the reasoning, and the consensus figure -- per stock,
# BEFORE the numbers land. That is the hurdle the result has to clear,
# and without it a "weak" quarter and a "weak quarter that everybody
# already feared" look identical.
#
# THE PAGES WERE BEING THROWN AWAY. is_digest() drops any message
# naming three or more tickers, because a digest pairs the wrong
# number with the wrong company. That rule is right for a news recap
# and exactly wrong here: this is a TABLE, and every stock carries its
# own verdict on its own lines.
_EXPECTATION_ROW = re.compile(
    r"^[\s\W]{0,3}([A-Z][A-Z0-9 &.\-]{1,20}?)\s+"
    r"(BULLISH|BEARISH|NEUTRAL)\s*$", re.M)

_EXPECTATION_PAGE = re.compile(
    r"pre-?earnings\s+market\s+expectations|expectation\s+coverage", re.I)


def is_expectation_page(text):
    """Is this the pre-result expectations table?"""
    body = text or ""
    return bool(_EXPECTATION_PAGE.search(body)) and \
        len(_EXPECTATION_ROW.findall(body)) >= 2


def expectations_from_page(text):
    """[{symbol, stance, note}] from one expectations page.

    The symbol has its spaces stripped: OCR splits tickers, and the
    real page that prompted this read "CL EAN BULLISH" for CLEAN.
    Dropping that row would lose the stock most in need of the entry.
    """
    body = text or ""
    if not is_expectation_page(body):
        return []
    rows = list(_EXPECTATION_ROW.finditer(body))
    out = []
    for index, match in enumerate(rows):
        symbol = match.group(1).replace(" ", "").replace(".", "").strip()
        if not (2 <= len(symbol) <= 16):
            continue
        end = rows[index + 1].start() if index + 1 < len(rows) else len(body)
        note = " ".join(body[match.end():end].split())
        # The date stamp the page repeats after every entry is not part
        # of the reasoning.
        note = re.sub(r"\d{1,2}\s+\w{3}\s+20\d\d\s*$", "", note).strip()
        out.append({"symbol": symbol.upper(),
                    "stance": match.group(2).upper(),
                    "note": note[:220]})
    return out


def counterparty(text):
    """Who the order came from, if the sentence says so."""
    match = COUNTERPARTY.search(text or "")
    if not match:
        return None
    who = re.sub(r"[.,;]+$", "", match.group(1).strip())
    # "from July" and "from Kuwait Concession" both came out of digest
    # messages. A month is never a customer.
    if re.match(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                who, re.I):
        return None
    return who[:60] or None


def grade_of(text, given=None):
    """The published verdict, in one word, or None.

    Reads the plain "Excellent Results" form first because it is the
    channel's own headline format and the least ambiguous. Falls back
    to the beat/miss vocabulary of the FinAI card, translated into the
    same six words so nothing downstream needs to learn a second set.
    """
    if given:
        return str(given).upper()
    body = text or ""
    match = RESULT_WORDS.search(body)
    if match:
        word = GRADE.search(match.group(0))
        if word:
            return word.group(1).upper()
    # An earnings brief states its verdict as a bare word on its own
    # line -- a coloured pill on the real card, "GREAT" or "EXCELLENT"
    # in the OCR. Neither "Excellent Results" nor "Verdict: X", so both
    # of the patterns above miss it and 22 stored briefs graded as
    # nothing.
    #
    # Safe to match a bare word ONLY because quality_signals() has
    # already confirmed this is one of these cards. The same pattern
    # loose on ordinary text would grade any message containing the
    # word "good".
    dot = DOT_GRADE.get((body.strip()[:1] if body.strip() else ""))
    pill = None
    if quality_signals(body):
        found = re.search(
            r"^\s*(EXCELLENT|GREAT|GOOD|FAIR|MIXED|WEAK|POOR)\s*$",
            body, re.M | re.I)
        pill = found.group(1).upper() if found else None

    if dot and pill:
        # ---- WHEN THE CARD DISAGREES WITH ITS OWN HEADLINE ----
        #
        # TCC, 1 August 2026. The channel opened the message with a
        # GREEN dot and the card underneath it read:
        #
        #     WEAK
        #     GROWTH MARGINS CASH FLOW QUALITY
        #     Rising  Compressing  Concern  Weak
        #     EARNINGS QUALITY | ONE-OFF
        #     Tax reversal flipped tax expense to...
        #
        # Their dot and their own verdict contradict each other. Taking
        # the dot would have put GOOD on that stock; taking the pill
        # would mean trusting OCR over a character that cannot be
        # misread.
        #
        # Neither is defensible, so neither is chosen. A disagreement
        # between two readings of the SAME card is not noise to be
        # resolved by preference -- it is the reason to look, and MIXED
        # is the only honest word for it.
        #
        # 1 of 22 cards on the day this was written.
        positive = {"EXCELLENT", "GREAT", "GOOD"}
        negative = {"WEAK", "POOR"}
        if (dot in positive and pill in negative) or \
                (dot in negative and pill in positive):
            diagnostic(f"[EVENTS] card disagrees with its own dot "
                       f"(dot={dot}, card={pill}) -- grading MIXED")
            return "MIXED"

    if dot:
        return dot
    if pill:
        return pill

    beat = BEAT_WORDS.search(body)
    if beat:
        # Whichever alternative fired, the verdict is the one group
        # that captured. Spaces and hyphens are stripped so "Strong
        # Beat", "strong  beat" and "In-Line" all key the same.
        raw = next((g for g in beat.groups() if g), None)
        if raw:
            key = re.sub(r"[\s\-]+", "", raw).upper()
            if key in BEAT_TO_GRADE:
                return BEAT_TO_GRADE[key]
            if key in ("EXCELLENT", "GREAT", "GOOD", "OK", "WEAK", "POOR"):
                return key
    return None


def classify(text, grade=None, has_symbol=False):
    """(kind, scope). scope is STOCK or MARKET.

    Order matters. A graded result is a result even if the sentence also
    contains the word "order"; noise is checked first because a YouTube
    link that mentions a company is still a YouTube link.
    """
    body = (text or "").strip()
    if not body:
        return "NOISE", "MARKET"
    if NOISE.search(body):
        return "NOISE", "MARKET"
    # OPINION BEFORE RESULT, 30 July 2026. A tip sheet reading
    #
    #   "STOCK PICK  NBCC, Hirect, Indo-MIM, Xtranet Tech, MOIL,
    #    MTAR Tech, Eicher Motors, Prestige Estates ... excellent"
    #
    # was recorded as REDINGTON RESULT grade=EXCELLENT, because the
    # grade words were checked first and one of them appeared somewhere
    # in the list. A recommendation is an opinion whatever adjectives it
    # contains, and calling it a result would let a tip sheet set a
    # score the same way an audited filing does.
    if OPINION.search(body):
        return "OPINION", "MARKET"
    if grade or RESULT_WORDS.search(body) or BEAT_WORDS.search(body):
        return "RESULT", "STOCK" if has_symbol else "MARKET"
    if FLOW_WORDS.search(body):
        # Institutional flow is the whole market's, never one stock's.
        return "FLOW", "MARKET"
    if ORDER_WORDS.search(body) and ORDER_NOUN.search(body):
        return "ORDER", "STOCK" if has_symbol else "MARKET"
    if CALENDAR_WORDS.search(body):
        return "CALENDAR", "MARKET"
    if has_symbol:
        return "NEWS", "STOCK"
    return "MACRO", "MARKET"


# Which kinds are worth keeping at all. OPINION and NOISE are recorded
# nowhere -- but the message they came from is never deleted, so a later
# change of mind costs a re-run, not the data.
USEFUL_KINDS = ("RESULT", "ORDER", "FILING", "NEWS", "FLOW", "CALENDAR",
                "MACRO", "EXPECTATION", "CONCALL", "MARKET_ANSWER",
                "REPORTED", "SETUP", "AI_VERDICT")


def _detail_json(detail):
    """The card's own findings, as text, or None.

    None and an EMPTY structure both store NULL. An empty dict written
    as "{}" reads back as "we looked and there was nothing", which is
    not the same as "nothing was captured", and the second is what an
    unread card means. Telling them apart is the whole reason the
    partial-read warning exists on the calendar path.
    """
    if not detail:
        return None
    if isinstance(detail, str):
        return detail.strip() or None
    if isinstance(detail, dict):
        detail = {k: v for k, v in detail.items() if v}
        if not detail:
            return None
    try:
        return json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        diagnostic(f"[EVENTS] detail not storable: {exc}")
        return None


def detail_of(row):
    """The findings back out of a stored row, as a dict. Never raises."""
    raw = (row or {}).get("detail")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}

# ---------------------------------------------------------------
# WHAT A VERDICT MAY SAY
# ---------------------------------------------------------------
# Three of these are obvious. UNRELATED is the one that earns its
# place, and it exists because of what the event store actually looked
# like on 31 July:
#
#   DOLLAR     "The Indian Rupee recorded its strongest weekly gain"
#   CENTRALBK  "European shares reached a record high on Friday"
#   URBANCO    "Afcons secures Rs 900 crore in new infrastructure"
#
# None of those stories is about that company. DOLLAR matched the word
# "dollar". They are keyword false positives, and they were being
# printed on the operator's screen as reasons.
#
# NEUTRAL and UNRELATED are NOT the same answer and collapsing them
# would waste the more useful one:
#
#   NEUTRAL    it affects this company, but not clearly either way
#   UNRELATED  this story is not about this company at all
#
# The second is actionable -- the chip should disappear. A model that
# is only allowed to say POSITIVE or NEGATIVE about a story it can see
# is unrelated will pick one, confidently, and make the dashboard
# worse than keywords left it.
VERDICTS = ("POSITIVE", "NEGATIVE", "NEUTRAL", "UNRELATED")

# ---------------------------------------------------------------
# THE COLOURED DOT -- the most reliable thing on these cards
# ---------------------------------------------------------------
# Earnings 360 and Earnings Pro open every result post with a traffic
# light, in the message TEXT rather than inside the picture:
#
#     🟢 #NEUEON — Q1 FY27      Strong standalone with robust growth
#     🟡 #AARTIDRUGS — Q1 FY27  ...
#     🔴 ...
#
# It needs no OCR, it cannot be mangled by a bad scan, and it is the
# channel's own verdict rather than our reading of their layout.
# Measured on 1 August 2026: 16 green, 4 amber, 1 red.
#
# It is checked BEFORE anything that reads the picture, because
# everything inside the picture is a guess about a font and this is
# not. Chasing the OCR'd verdict word had reached 3 cards out of 12
# and was about to become an evening of layout patterns -- the same
# trap as the filing parser the night before.
DOT_GRADE = {
    "\U0001F7E2": "GOOD",     # green
    "\U0001F7E1": "MIXED",    # amber
    "\U0001F534": "WEAK",     # red
    "\U0001F7E0": "MIXED",    # orange, used interchangeably with amber
}


# ---------------------------------------------------------------
# ONE MESSAGE -> THE EVENTS IT CONTAINS
# ---------------------------------------------------------------
# Lifted out of tools/build_stock_events.py on 31 July 2026 so that the
# LIVE session and the after-close tool run identically.
#
# Until tonight there was only one caller: a tool the operator ran by
# hand after the market shut. Measured on 31 July, every one of the
# day's 119 events was written in a single batch at 14:35:54 --
#
#     YASHO      Excellent Results   posted 12:19  ->  filed 14:35
#     STAR       Good Results        posted 12:37  ->  filed 14:35
#     BSE        Good Results        posted 12:47  ->  filed 14:35
#
#     fastest 5 min | typical 91 min | worst 429 min
#
# On an ordinary day the tool runs after the close, so a result posted
# at 12:19 first affects the score TOMORROW. He put it plainly:
#
#     "if today result came excellent & if the stock moved high even
#      though we get them in top gainers but without why cards. i
#      cannot trust the price movement right? genuine gap between
#      trusted & vague buying"
#
# That is the whole argument. A stock up 13% with a reason is a
# different object from a stock up 13% without one, and the reason was
# sitting in our own database, unread, for an hour and a half.
#
# WHY A SHARED FUNCTION AND NOT A SECOND COPY
# -------------------------------------------
# Two paths filing events by two sets of rules would disagree, and the
# disagreement would show up as the live screen and the evening review
# telling the operator different things about the same day. There is
# one set of rules and both callers use it.
# A card's own vocabulary can BE a ticker. Checked against the master
# file: of every word these briefs print -- CLEAN, MIXED, POOR, WEAK,
# GREAT, RISING, EXPANDING, HEALTHY, QUALITY -- exactly one is a listed
# company:
#
#     CLEAN  ->  CLEAN SCIENCE & TECH LTD
#
# So "EARNINGS QUALITY | CLEAN" on a NEUEON brief filed the whole card
# against Clean Science. Found on the first run, 1 August 2026.
#
# The label is removed before symbol matching and nowhere else -- the
# text stored, classified and graded is untouched, because "CLEAN" is
# the answer to "can this quarter be trusted" and losing it would cost
# the very signal this card was added for.
_VERDICT_WORD = r"CLEAN|MIXED|POOR|WEAK|DIRTY|ONE-?OFF|DISTORTED|ADJUSTED"

_CARD_LABEL = re.compile(
    rf"EARNINGS\s*QUALITY\s*[|:\-]?\s*({_VERDICT_WORD})\b", re.I)

# ---- THE VALUE IS ON THE LINE BELOW. 1 August 2026. ----
#
# The rule above assumed the verdict sits beside its label. On a
# two-column card it does not -- the headings run along one line and
# the readings sit under them:
#
#     EARNINGS QUALITY DISTORTION FLAGS ACCOUNTING - ONE-OFFS
#     CLEAN
#
# so NITTAGELA's and PRICOLLTD's briefs were still being filed against
# Clean Science after the first fix. This is the same mistake
# quality_signals() had already been taught not to make, and it was
# not carried across.
#
# Bounded to the line DIRECTLY beneath, and to a line holding nothing
# but the verdict. A stray "CLEAN" three lines down is a different
# thing and is left alone.
_CARD_LABEL_BELOW = re.compile(
    rf"(^[^\n]*\bEARNINGS\s*QUALITY\b[^\n]*)\n([\s\W]{{0,4}})"
    rf"({_VERDICT_WORD})\b",
    re.I | re.M)


# ---- THE X ACCOUNT CARD, 1 August 2026 ----
#
#     "THEY WILL POST/FORWARD ONLY IMAGES FROM X WHICH ARE USEFUL FOR
#      OUR CAUSE & EFFECT ON STOCKS + RESULTS + NDTV LIST"
#                                    -- operator
#
# Day Trader Telugu forwards SCREENSHOTS of tweets, and every one opens
# with the poster's account card:
#
#     a= RedboxGlobal India @          <- display name, verified badge
#     i= @REDBOXINDIA                  <- the handle
#     DABUR: CO AIMS DOUBLE-DIGIT VOLUME GROWTH
#
# The news starts on line three. 143 stored event headlines opened with
# that header, so the chip and the stock card both spent their first
# forty characters saying REDBOXINDIA.
#
# It has to be stripped HERE, when the event is built, because the
# headline is stored as one line -- once " ".join(body.split()) has run
# the line breaks are gone and no line-based rule can find it again.
#
# The classes are "anything but @" on purpose: the OCR prefixes each
# line with its own guess at the avatar ("a=", "i=", "cRec"), and a
# spelled-out character class missed both on the first attempt.
_X_HEADER = re.compile(
    r"^[^@\n]{0,32}@\s*$"                       # display name + badge
    r"|^.{0,8}?@[A-Za-z0-9_]{3,}\s*$",          # the handle, alone
    re.I)


# ---- THE WATERMARK THE OCR MANGLED, 1 August 2026 ----
#
# The line-based rule above needs an "@" to recognise a handle, and
# the OCR does not always leave one. 26 event headlines still opened
# with the publisher's watermark, in three shapes:
#
#     H#IQWithCNBCTV18 | #SJVN reports its Q1 results...
#     #1QWithCNBCTV18 | #CenturyPly reports its Q1...
#     HONCNBCTV18 ¢ L&T Order Inflows Have Remained Strong...
#
#     a= RedboxGlobal India @ i= @REDBOXINDIA SYRMA SGS: Q1 CONS...
#     De eReDBOXINDIA SYRMA SGS: CO SAYS CONFIDENT OF EXCEEDING...
#     Be oReDBOXINDIA VIKRAN ENGINEERING: SECURES 2120.69 CRORE...
#
# "IQWithCNBCTV18" came back seven different ways, so the patterns key
# on the one part the OCR keeps: CNBCTV18, and REDBOXINDIA.
#
# WHY A PUBLISHER-SPECIFIC RULE IS ALLOWED HERE, having reverted two
# others today: this only ever removes a PREFIX from a forwarded
# screenshot's watermark. It decides nothing. A rule that guesses
# whether a word is a ticker can lose a true link; this can at worst
# leave the headline exactly as it found it.
#
# LEADING POSITION ONLY, and that is the whole guard. One real story
# in the same batch reads
#
#     IDFC FIRST Bank is presenting the Fintech Cohort of
#     LeapToUnicorn Season 4, in association with CNBC-TV18
#
# -- CNBC is the SUBJECT there, not the watermark, and it survives
# because it is not at the front.
# The junk prefix has to be allowed to contain a SPACE. One headline
# stacks two watermarks and the first attempt left it untouched:
#
#     cNec CNBC-TV18 @& #1QWithCNBCTV18 | #Vedanta reports its Q1...
#          ^ a space here, and \S could not cross it
#
# Bounded to 12 characters and non-greedy, so it can only ever eat a
# short prefix.
_LEAD_WATERMARK = re.compile(
    r"^\W{0,4}.{0,12}?CNBC\s?-?\s?TV\s?18\b[\s|¢@&:,.\-]*"   # the campaign tag
    r"|^.{0,44}?REDBOX\s?INDIA\b[\s|¢@&:,.\-]*",             # the handle
    re.I)

# Two passes, because that Vedanta headline carries the publisher's
# watermark AND its campaign tag. Two is enough for every shape seen;
# a loop would invite a pattern that eats the whole line.
_WATERMARK_PASSES = 2


def strip_x_header(body):
    """The tweet, without the account card or watermark above it."""
    kept = [line for line in str(body or "").splitlines()
            if not _X_HEADER.match(" ".join(line.split()))]
    text = "\n".join(kept).lstrip()
    for _ in range(_WATERMARK_PASSES):
        stripped = _LEAD_WATERMARK.sub("", text, count=1).lstrip()
        if stripped == text:
            break
        text = stripped
    return text


# ---- TICKERS THAT ARE ALSO ORDINARY ENGLISH WORDS ----
#      6 August 2026.
#
#     "so pls do not miss or club one data to other stock"
#     "pls make sure these chips & related stocks are never mis
#      matched as they are the one we trust"
#
# Measured on one day of real traffic, these took the MOST result
# images of any symbol in the store:
#
#     CURRENT   33 images        VALUE   31        TOTAL   26
#     GLOBAL    14
#
# More than TRENT, which actually reported. They are real NSE tickers
# -- so every guard passed them -- but a results table printing the
# word "Total", or a card headed "CURRENT VALUE", is not a filing by
# those companies. Other companies' figures were being stored against
# them.
#
# Same class of fault as CLEAN below, and the same fix: a bare
# occurrence is not a match. These need a "$" or "#" prefix, or the
# company name spelled out, before the link is made. Nothing is
# deleted from the stored text -- only the SYMBOL match is withheld.
_WORD_TICKERS = ("VALUE", "TOTAL", "CURRENT", "GLOBAL", "TECH", "METAL",
                 "ENERGY", "DIVIDEND", "FOCUS", "QUALITY", "GROWTH",
                 "ALPHA", "MOMENTUM", "CONSUMER", "INFRA")
_BARE_WORD = re.compile(
    r"(?<![#$\w])(" + "|".join(_WORD_TICKERS) + r")(?![\w])")


def _for_matching(body):
    """The text with card labels removed, for SYMBOL matching only.

    CLEAN is Clean Science & Technology's real ticker AND the word
    every brief prints when a quarter is honest. Nothing else in this
    module strips anything -- the text stored, classified and graded is
    untouched, because "CLEAN" is the answer to "can this quarter be
    trusted" and losing it would cost the signal the card was read for.
    """
    text = _CARD_LABEL.sub(" EARNINGS QUALITY ", body or "")
    text = _CARD_LABEL_BELOW.sub(r"\1\n\2", text)
    # A hashtag or dollar prefix survives, because that IS someone
    # naming the company. A bare word does not.
    return _BARE_WORD.sub(lambda m: m.group(1).lower(), text)


def events_from_message(matcher, text=None, ocr_text=None, at=None,
                        channel=None, url=None, grade=None,
                        from_image=False, word_boxes=None):
    """Everything worth recording from one Telegram message.

    Returns a list of dicts ready to hand straight to
    StockEvents.remember(**item). Empty list is the common and correct
    answer -- most chat is not an event.

    `matcher` is anything with symbols_in() and names_in(); in the live
    session that is the TelegramFeed itself, so the same name index
    that tagged the message tags the event.
    """
    typed = (text or "").strip()
    read = (ocr_text or "").strip()
    body = (typed + "\n" + read).strip()
    if not body:
        return []

    out = _events_from_message(matcher, typed, read, body, at, channel,
                               url, grade, from_image, word_boxes)
    return _only_market_wide(out, channel)


# ---- NEWS PULSE DOES NOT NAME A STOCK ANY MORE. 2 August 2026. ----
#
#   "news pulse is not reliable so drop that for tagging as of now."
#                                       -- operator
#
# The measurement agreed with him before he said it. Of its 820
# messages only 308 carry a hashtag at all -- 38%, against 99-100% on
# every card channel -- and its per-stock rows are the ones that keep
# turning up wrong:
#
#     a Nifty close        -> SWIGGY
#     a Rupee story        -> DOLLAR      (Dollar Industries)
#     an Apple story       -> MOL
#     an ICRA gold-loan    -> RAMCOCEM
#
# because a News Pulse message is a DIGEST. "MORNING PULSE (Part 1/5)"
# carries five unrelated stories and five hashtags, and nothing in it
# says which paragraph belongs to which tag. 10 of the 18 remaining
# store-wide disagreements are that exact shape.
#
# What it is still good for is the market-wide half, and that is kept:
#
#     160 MACRO   policy, rates, global cues
#      41 FLOW    FII / DII net figures, which nothing else carries
#
# So the channel is not muted -- its scope is. A MARKET row claims
# nothing about any single company and cannot be mis-tagged.
NO_STOCK_TAGGING = ("News Pulse",)


def _only_market_wide(events, channel):
    """Drop per-stock rows from a channel we do not trust to name one."""
    if not events or (channel or "") not in NO_STOCK_TAGGING:
        return events
    kept = [e for e in events if e.get("scope") != "STOCK"]
    lost = len(events) - len(kept)
    if lost:
        diagnostic(f"[EVENT] {channel}: {lost} per-stock row(s) dropped -- "
                   f"this channel is trusted for market-wide context only")
    return kept


def _events_from_message(matcher, typed, read, body, at, channel,
                         url, grade, from_image, word_boxes):
    """The body of events_from_message(). See the wrapper above."""

    # ---- THE EXPECTATIONS TABLE IS NOT A DIGEST ----
    #
    # Checked BEFORE is_digest(), which drops anything naming three or
    # more tickers. That rule exists because a news recap pairs the
    # wrong number with the wrong company -- true of a recap, and
    # exactly wrong here. This is a TABLE: every stock carries its own
    # stance on its own lines, and reading it row by row is safe in a
    # way reading a recap never is.
    #
    # It cost 23 expectations across three pages before anyone
    # noticed, and they are the only thing in the whole system that
    # says what was priced in BEFORE the result.
    if is_expectation_page(body):
        return [{
            "symbol": row["symbol"],
            "at": at,
            "kind": "EXPECTATION",
            "scope": "STOCK",
            "headline": f"EXPECTED {row['stance']}: {row['note']}"[:200],
            "grade": None,
            "value_cr": None,
            "counterparty": None,
            "source": channel,
            "url": url,
            "from_image": bool(from_image or (read and not typed)),
        } for row in expectations_from_page(body)]

    # ---- THE CONCALL CARD, 1 August 2026 ----
    #
    #   "conviction on business + confidence on management"
    #
    # Earnings 360 sends this after every concall and the bot filed it
    # as ordinary news, grade None, the whole card mashed into a
    # headline and cut off mid-word:
    #
    #     kind=NEWS grade=None
    #     "ADANIENSOL - Concall Summary ... SENTIMENT TONE = Positive
    #      Confid"
    #
    #     79 cards received, 78 carrying SENTIMENT TONE, 0 read.
    #
    # Checked BEFORE is_digest() for the same reason the expectations
    # table is: the card names its company once, at the top, and then
    # lists takeaways that mention OTHER companies, customers and
    # plants. The three-name rule would drop it, and did.
    #
    # Filed as its own kind rather than folded into RESULT. A result is
    # arithmetic that has happened; a concall is what management said
    # about what has not happened yet, and the two must not average
    # into one grade. Whether a confident tone is worth buying is
    # unmeasured -- core/outcomes.py answers that once there are
    # samples, and until then this is a sentence on the row, not a
    # reason to trade.
    #
    # ---- AND THE COLUMNS, 2 August 2026 ----
    #
    # The card prints KEY TAKEAWAYS / WHAT CHANGED above RED FLAGS /
    # WHAT TO TRACK NEXT, two columns wide. Read as flat text the two
    # halves interleave line by line, so RED FLAGS came back empty on
    # the BLUSPRING card and the summary said "no red flags" about a
    # card printing three. word_boxes carry the x of every word, which
    # is the only thing on the page that says which column a line is in.
    #
    # The findings are stored in `detail` against THIS symbol -- the one
    # the caption names -- because a concall names customers, plants and
    # peers in nearly every bullet and those are not the company the
    # card is about.
    if is_concall_card(body):
        subject = symbols_first(matcher, typed) or symbols_first(matcher, body)
        card = read_concall_card(body, word_boxes) or {}
        head = card.get("summary") or concall_summary(body)
        if head and subject:
            detail = {k: card.get(k) for k in
                      ("takeaways", "changed", "red_flags", "track_next",
                       "mixed", "guidance", "gauges")}
            kept = sum(len(v) for k, v in detail.items()
                       if k != "gauges" and isinstance(v, list))
            if word_boxes and kept:
                diagnostic(f"[CONCALL] {subject}: {kept} findings kept "
                           f"({len(detail.get('red_flags') or [])} red flags, "
                           f"{len(detail.get('track_next') or [])} to track)")
            return [{
                "symbol": subject,
                "at": at,
                "kind": "CONCALL",
                "scope": "STOCK",
                "headline": head[:200],
                "grade": None,
                "value_cr": None,
                "counterparty": None,
                "source": channel,
                "url": url,
                "from_image": bool(from_image or (read and not typed)),
                "detail": detail,
            }]

    # ---- THE MARKET'S ANSWER, ROW BY ROW, 1 August 2026 ----
    #
    #   "are we utilizing all what we have from PRO?"
    #
    # No. This was the largest single answer:
    #
    #      52 pages received
    #     258 stock rows printed on them
    #       3 events produced
    #
    # Earnings Pulse publishes "Market Sentiment for <date> Reportings"
    # the morning after results. Each row is one company with its own
    # grade, its own sentiment and its own sentence saying what the
    # price did and why. The PRO page calls it "market confirmation and
    # your safety blanket".
    #
    # It was being eaten by the three-company rule below -- the SECOND
    # structured page that rule has swallowed. The first cost 23
    # expectations. This one cost 258 rows. Same fix, same reason: this
    # is a TABLE, every row carries its own symbol, and reading it row
    # by row cannot pair the wrong figure with the wrong company.
    #
    # Checked BEFORE is_digest() for that reason.
    if is_sentiment_page(body):
        try:
            known = matcher._known_symbols()
        except Exception:                                  # noqa: BLE001
            known = None
        out = []
        for row in sentiment_rows(body, known=known):
            head = sentiment_headline(row)
            if not head:
                continue
            out.append({
                "symbol": row["symbol"],
                "at": at,
                "kind": "MARKET_ANSWER",
                "scope": "STOCK",
                "headline": head,
                # Deliberately ungraded. The row carries the
                # publisher's grade of the QUARTER, which the result
                # card already filed. Repeating it here would double-
                # count one opinion as two sources -- the exact thing
                # the support tally exists to prevent.
                "grade": None,
                "value_cr": None,
                "counterparty": None,
                "source": channel,
                "url": url,
                "from_image": bool(from_image or (read and not typed)),
            })
        if out:
            return out

    # ---- THE EVENING RECAP GRID, 1 August 2026 ----
    #
    #   "sorted list of results which will get impacted on monday
    #    market"
    #
    # A result released after 15:30 on Friday has not been priced --
    # the market was shut. It moves Monday morning, which is the
    # early-bird window he has asked for since the morning.
    #
    #     5 cards, 193 companies named, 0 events produced.
    #
    # Third structured page eaten by the three-company rule below,
    # after the expectations page (23 lost) and the market sentiment
    # pages (258 lost).
    #
    # THE GRADE IS DELIBERATELY NOT TAKEN. It is on the card and OCR
    # detaches it -- the five rating rows come back as a stack above
    # the title with nothing tying them to any company, and on one of
    # the five cards only three of the five survived. Putting a WEAK
    # company under EXCELLENT is the mismatch rule, and the grade is
    # already stored properly from the individual brief cards.
    if is_recap_card(body):
        try:
            known = matcher._known_symbols()
        except Exception:                                  # noqa: BLE001
            known = None
        when = recap_date(body, at)
        which = card_kind(body)

        # ---- READ THE GRID BY POSITION FIRST. 2 August 2026. ----
        #
        #     "what if i didn't asked you to tell me what our bot will
        #      do this image? we never know right"
        #
        # TOMORROW'S CALENDAR is a wall of logos, and Tesseract walks
        # it column by column. On the 03 August card the flat text
        # split put NINE stocks that report while the market is open
        # into the after-the-close bucket -- ESCORTS, CAMS, PARKHOSPS,
        # JAINREC, BLUEJET, ETHOSLTD, HUBTOWN, STOVEKRAFT, MOBIKWIK --
        # and six more were never read at all. Four of nineteen right.
        #
        # A y-coordinate does not care what order anything was read in.
        # When the word boxes are available the grid path wins; when
        # they are not, everything below is exactly as it was.
        rows = []
        if word_boxes:
            rows = grid_rows(word_boxes, known=known)
        if not rows:
            rows = recap_rows(body, known=known)

        # ---- AND SAY SO WHEN IT IS PARTIAL ----
        # The card counts itself: "03 Aug, 2026 - 60 Companies". A
        # half-read grid that reports 34 names as though they were the
        # list is the silent failure he caught. Loud, every time.
        says = stated_count(body)
        if says and rows and len(rows) < says:
            # ---- NAME THEM. 4 August 2026. ----
            #
            #   "calendar first"
            #
            # The count alone sent him looking for an OCR bug. Measured
            # against the real 03 August card: 246 tokens, 157 matched
            # the master exactly, 89 did not. Seventeen of those 89 are
            # OCR damage on names we DO hold -- GOPREJPROP, KALYANKUJIL,
            # MAPMYINBIA, CUMMINSINP -- one letter each, J read as U,
            # D read as P.
            #
            # But the rest are not OCR at all. METROBRAND, SYMPHONY,
            # WONDERLA, HMVL, CANTABIL, AJMERA, VENTIVE, AUTOAXLES are
            # real NSE companies that are simply NOT IN THE MASTER. The
            # bot cannot match a name it has never heard of, and no
            # amount of OCR work will change that.
            #
            # Two different problems behind one number, and the fix for
            # the second is tools/discover_stocks.py, which exists for
            # exactly this. So the warning names what it could not
            # place instead of counting it.
            #
            # DELIBERATELY NOT FUZZY-MATCHED HERE. A one-letter guess
            # that lands on the wrong company is the mismatch rule --
            # "pls make sure these chips & related stocks are never mis
            # matched" -- and a calendar entry becomes a results
            # expectation the gate trades on. Naming them is safe;
            # guessing them is not.
            unread = _unplaced_names(body, rows, known)
            warn(f"[CALENDAR] {which} card for {when} lists {says} "
                 f"companies and only {len(rows)} could be read. "
                 f"{says - len(rows)} are NOT on the watchlist -- treat "
                 f"it as a partial list and check the card.")
            if unread:
                warn(f"[CALENDAR] Could not place: {', '.join(unread[:20])}"
                     f"{' ...' if len(unread) > 20 else ''}")
                warn("[CALENDAR] Names the master has never heard of are "
                     "added by: py tools/discover_stocks.py --apply")

        out = [{
            "symbol": row["symbol"],
            "at": at,
            "kind": "REPORTED",
            "scope": "STOCK",
            "headline": recap_headline(row, on=when, kind=which),
            "grade": None,
            "value_cr": None,
            "counterparty": None,
            "source": channel,
            "url": url,
            "from_image": bool(from_image or (read and not typed)),
        } for row in rows]
        if out:
            return out

    # ---- LAYER 04, THE AUDIT, 2 August 2026 ----
    #
    #   "AI Verdict is what we get on the one page of stock = after
    #    assessing all AI will create a page & we will get them from
    #    EARNINGS PRO"
    #
    # 363 were already stored. The bot read the headline and threw the
    # page away. The top line carries TWO ratings:
    #
    #     Algo Pulse: Weak | Verdict: MET
    #
    # and on 70 of 281 readable pairs -- ONE IN FOUR -- the audit
    # CONTRADICTS the algorithm. 57 companies graded WEAK were cleared
    # by it. SYRMA: algo Weak, audit BEAT, "revenue surging 67% YoY".
    #
    # Checked before is_digest() because the page cites customers,
    # segments and rivals in its own tables. The company is the one in
    # the caption's hashtag, which the publisher put there.
    #
    # THE FIGURES ARE NOT TAKEN FROM THE PICTURE. OCR destroys the
    # rupee sign on every amount -- Rs 5,455 Cr comes back as
    # "75,455 Cr". The summary line comes from the CAPTION, which is
    # real text. See core/ai_verdict.py.
    if is_verdict_card(body):
        head = verdict_summary(body, caption=typed)
        symbol = symbols_first(matcher, body)
        if head and symbol:
            return [{
                "symbol": symbol,
                "at": at,
                "kind": "AI_VERDICT",
                "scope": "STOCK",
                "headline": head,
                # Ungraded on purpose. The card carries the ALGO's
                # grade, which the result card already filed. Repeating
                # it would count one opinion twice.
                "grade": None,
                "value_cr": None,
                "counterparty": None,
                "source": channel,
                "url": url,
                "from_image": bool(from_image or (read and not typed)),
            }]

    # A digest carries several stories and the extractor pairs the
    # wrong number with the wrong company. A wrong figure is worse
    # than none.
    #
    # ---- COUNT THE COMPANIES BEFORE JUDGING. 5 September 2026. ----
    #
    # This asked is_digest() FIRST and resolved the companies after, so
    # the one fact that actually settles the question -- how many
    # companies is this about -- was not available when the question was
    # asked. Swapping the two lines is the whole change; see the note in
    # is_digest() for the 108 single-company cards it saves.
    try:
        symbols = list(dict.fromkeys(
            matcher.symbols_in(_for_matching(body))
            + matcher.names_in(_for_matching(body))))
    except Exception:                                      # noqa: BLE001
        return []

    if is_digest(body, companies=len(symbols)):
        return []

    # ---- ONE CARD IS ABOUT ONE COMPANY. 2 August 2026. ----
    #
    #     "this channel provide 3 documents = CONCALL, INVESTOR
    #      PRESENTATION, EARNINGS BREIF. with stock name. so pls do not
    #      miss or club one data to other stock."
    #
    # Measured on the 432 Earnings 360 cards in the store: 415 name
    # exactly one company in the CAPTION, and 23 of those were ALSO
    # filed against a second stock -- because the card's own body
    # mentions one:
    #
    #   #BIRLACABLE  "Proposed amalgamation with Vindhya"  -> VINDHYATEL
    #   #SAGCEM      a cement peer named in the text       -> ACL
    #   #BAJAJFINSV  its own subsidiary                    -> BAJFINANCE
    #   #MGL         a gas peer                            -> GAIL
    #
    # Every one of those put BIRLACABLE's EXCELLENT result on Vindhya
    # Telelinks' row. It is the POWERGRID bug in a different costume:
    # a company MENTIONED is not the company the card is ABOUT.
    #
    # The publishers settle it themselves. The caption hashtag is the
    # subject -- it is what THEY say the card is about, and no amount
    # of prose underneath changes that. symbols_first() has read it
    # that way for the concall and verdict cards since 1 August; this
    # is the same rule applied to the path everything else falls down.
    #
    # Only when the caption carries a hashtag. A plain news line with
    # two companies in it is untouched, and so is the three-company
    # rule below.
    subject = symbols_first(matcher, typed) if typed else None
    if subject and len(symbols) > 1:
        dropped = [s for s in symbols if s != subject]
        diagnostic(f"[EVENT] {subject}: card also mentions "
                   f"{', '.join(dropped)} -- not filed against them. "
                   f"The caption says whose card this is.")
        symbols = [subject]

    # A MESSAGE ABOUT THREE COMPANIES IS ABOUT NONE OF THEM.
    if len(symbols) >= 3:
        return []

    # ---- THE GRADE WAS READ TWICE, AND ONLY THE SECOND ONE COUNTED ----
    #
    # classify() was given the grade the CALLER passed -- almost always
    # None -- while the row underneath was written with grade_of(),
    # which reads the card. So CDSL's brief, whose only verdict is the
    # word GREAT on its own line, was filed kind=NEWS grade=GREAT: a
    # result the panel would not treat as one. Reading it once, here,
    # makes the two agree.
    grade = grade_of(body, grade)
    kind, scope = classify(body, grade=grade, has_symbol=bool(symbols))
    if kind not in USEFUL_KINDS:
        return []

    # The account card comes off BEFORE the line breaks do -- see
    # strip_x_header(). Once this is one line it cannot be found again.
    headline = " ".join(strip_x_header(body).split())[:200]
    # A FinAI card OCRs into 300 characters of grid whose first 200 are
    # the header row. Lead with the comparison or the truncation eats
    # the only part worth having.
    # THE TALLY FIRST, then the estimate grid, then the raw text.
    #
    # Ordered by how much each one tells the operator in the 80
    # characters the chip actually shows. "MISS EBITDA Margin" is the
    # reason a stock falls on a quarter that grew; "PAT +203% vs est"
    # is the size of a beat; the raw headline is neither.
    # WHAT LEADS THE CHIP, in the order that decides a purchase.
    #
    # The chip shows about 80 characters. Four things compete for them,
    # and the ranking is not about which is most interesting -- it is
    # about which would STOP a trade:
    #
    #   1  a WATCH   "margins Compressing, cash flow Weak"
    #                the reason not to buy. Nothing outranks it.
    #   2  the tally "MISS EBITDA Margin"
    #                was the growth enough. The APTUS question.
    #   3  a clean brief    "CLEAN | Rising, Expanding, Healthy"
    #   4  the estimate grid "PAT +203% vs est"
    #
    # Stopping one bad purchase is worth more than confirming ten good
    # ones, so the warning goes first even though it is the rarest.
    # ---- A FLAGGED ONE-OFF OUTRANKS EVERYTHING, 1 August 2026 ----
    #
    # CDSL printed GREAT on one card and Weak on another, and the fact
    # that settles it -- 39.5 Cr of the 118 Cr profit was a dividend
    # from the subsidiary -- sat in a section nothing read. A gauge
    # saying "margins Compressing" is a direction. An amount is a
    # number the operator can subtract himself, and it belongs in the
    # 80 characters before anything else competes for them.
    quality = quality_summary(body)
    trust = trust_summary(body)
    if trust:
        lead = trust
    elif quality and quality.startswith("WATCH"):
        lead = quality
    else:
        lead = tally_summary(body) or quality or estimate_summary(body)
    if lead:
        headline = f"{lead} -- {headline}"[:200]

    # A RUPEE FIGURE IS ONLY AN ORDER VALUE INSIDE AN ORDER. GAIL's
    # results headline stored value_cr=1262 off "Vs 1,262 Cr (QoQ)" --
    # last quarter's profit, filed as a contract win.
    is_order = kind == "ORDER"
    common = {
        "at": at, "kind": kind, "headline": headline,
        "grade": grade,
        "value_cr": amount_in_crore(body) if is_order else None,
        "counterparty": counterparty(body) if is_order else None,
        "source": channel, "url": url,
        "from_image": bool(from_image or (read and not typed)),
    }

    # THE BUYER IS NOT THE WINNER. "Astra Microwave secures Rs 2,205 Cr
    # order from HAL" recorded an ORDER against HAL too. HAL is the
    # customer -- one company won revenue, the other spent money.
    who = common.get("counterparty") or ""
    if is_order and who:
        symbols = [s for s in symbols
                   if s.upper() not in who.upper().split()
                   and not who.upper().startswith(s.upper())]

    # ---- ONE ORDER HAS ONE WINNER. 22 August 2026. ----
    #
    #     "fix the multi symbol attribution bug"   -- operator
    #
    # `common` carries value_cr, and this handed the SAME dict to every
    # symbol the card mentioned. Live rows that produced:
    #
    #     VIKRAN      2,120.7 cr  |  POWERGRID   2,120.7 cr
    #     ASTRAMICRO  2,205.2 cr  |  HAL         2,205.2 cr
    #     WEALTH / LANDMARK / NUVAMA  15,840 cr each, one garbled card
    #
    # VIKRAN's order became POWERGRID's. The counterparty rule above
    # catches the buyer when it is NAMED as the buyer; it cannot help
    # when a card simply mentions several companies, which is what an
    # OCR'd news-channel screenshot does constantly.
    #
    # A figure that cannot be pinned to ONE company is not that
    # company's order value. The EVENT is still recorded against each
    # symbol -- the card did mention them, and that is worth knowing --
    # but the RUPEE FIGURE is dropped, because attributing it is a
    # guess and a wrong value is worse than none.
    #
    # Same doctrine as symbols_first(): one tag means one subject,
    # several means none. This applies it to the money.
    if scope == "STOCK" and symbols:
        if len(symbols) > 1 and common.get("value_cr") is not None:
            common = dict(common, value_cr=None)
        return [dict(common, symbol=s, scope="STOCK") for s in symbols]
    # Market context, deliberately symbol-less: a Fed hold explains why
    # everything moved, and pinning it to six housing-finance names is
    # how one headline produced 140 false links in July.
    return [dict(common, symbol=None, scope="MARKET")]


class StockEvents:
    """One row per event. Idempotent on (symbol, at, kind, headline)."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure()

    def _ensure(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    at TEXT,
                    kind TEXT,
                    scope TEXT,
                    grade TEXT,
                    value_cr REAL,
                    counterparty TEXT,
                    headline TEXT,
                    source TEXT,
                    url TEXT,
                    from_image INTEGER DEFAULT 0,
                    created_at TEXT
                )""")
            # The uniqueness that makes a re-run safe. A backfill that
            # doubles every row on the second run is a backfill nobody
            # dares repeat -- and re-running is exactly how a matcher
            # improvement reaches the old data.
            #
            # ---- 31 July 2026: it had never worked for half the table.
            #
            # NULL IS NOT EQUAL TO NULL. That is the SQL standard, and it
            # means a UNIQUE index over a nullable column cannot catch a
            # repeat when that column is NULL. Market-scope events are
            # stored with symbol=NULL deliberately -- a Fed hold belongs
            # to no company -- so every one of them was re-inserted on
            # every run, silently, while the log said "already there".
            #
            # Measured: two identical runs back to back added 254 rows.
            # Duplicated groups where a symbol was present: ZERO.
            # Duplicated groups where symbol was NULL: 150.
            #
            # DAILY_ROUTINE.md tells the operator to run
            # build_stock_events --apply after every close, so this had
            # been compounding once a day.
            #
            # COALESCE in the index expression gives NULLs a real value
            # to collide on. Duplicates must go first -- a UNIQUE index
            # cannot be built over a table that already violates it.
            conn.execute("DROP INDEX IF EXISTS ux_event")
            conn.execute("""
                DELETE FROM events WHERE id NOT IN (
                    SELECT MIN(id) FROM events
                    GROUP BY COALESCE(symbol,''), at, kind, headline)""")
            conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_event_v2
                            ON events (COALESCE(symbol,''), at, kind,
                                       headline)""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_symbol "
                         "ON events (symbol, at DESC)")

            # ---- THE AI VERDICT, ADDED 31 July 2026 -----------------
            #
            # 269 of the events on file carry a kind and no direction.
            # "GAIL Board Approves Merger Of Konkan LNG" is stored, is
            # matched to the right company, and says nothing about
            # whether it is good or bad -- because no keyword table can
            # ever answer that.
            #
            # These five columns are where the model's answer lives.
            # They are stored NEXT TO THE EVENT, not in a separate
            # table, for one reason: tools/refused_review.py has to be
            # able to ask, weeks from now, "when it said POSITIVE, what
            # did the stock actually do?" A verdict that cannot be
            # scored against an outcome is an opinion nobody can ever
            # check, and this bot has enough of those.
            #
            #   ai_direction    POSITIVE / NEGATIVE / NEUTRAL
            #   ai_confidence   0.0 - 1.0, the model's own
            #   ai_reason       one sentence naming the mechanism
            #   ai_model        which model said it -- they will change
            #   ai_at           when, so a re-grade is visible as one
            #
            # ai_model is not decoration. When the model is upgraded,
            # every verdict before that date was produced by a
            # different reader, and any measurement that mixes them is
            # measuring two things at once.
            existing = {row[1] for row in
                        conn.execute("PRAGMA table_info(events)")}
            #
            # ---- detail, 2 August 2026 ----
            #
            #   "this channel provide 3 documents = CONCALL, INVESTOR
            #    PRESENTATION, EARNINGS BREIF. with stock name. so pls
            #    do not miss or club one data to other stock."
            #
            # A concall card carries four columns of findings -- key
            # takeaways, what changed, red flags, what to track next --
            # and the row could hold ONE headline of 200 characters.
            # Fifteen findings went in, one sentence came out, and the
            # rest was thrown away at the door. That is the opposite of
            # the standing rule.
            #
            # JSON, in the SAME row as the event, for the reason the ai_
            # columns are: the findings belong to that company's card and
            # a side table is one more join that can put them on the
            # wrong stock. The column is nullable and every other kind
            # leaves it NULL.
            for column, kind in (("ai_direction", "TEXT"),
                                 ("ai_confidence", "REAL"),
                                 ("ai_reason", "TEXT"),
                                 ("ai_model", "TEXT"),
                                 ("ai_at", "TEXT"),
                                 ("detail", "TEXT")):
                if column not in existing:
                    conn.execute(f"ALTER TABLE events "
                                 f"ADD COLUMN {column} {kind}")
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            warn(f"[EVENTS] Could not open {self.db_path}: {exc}")

    def remember(self, symbol, at, kind, headline, scope="STOCK",
                 grade=None, value_cr=None, counterparty=None,
                 source=None, url=None, from_image=False, detail=None):
        """Record one event. Returns True if it was new.

        ---- INSERT ONLY. TWO ATTEMPTS TO MAKE IT REPLACE WERE MADE
             AND BOTH WERE WRONG. 1 August 2026. ----

        The unique index is on (symbol, at, kind, HEADLINE), so a
        parser improvement writes a SECOND row rather than correcting
        the first. 389 stocks were carrying more than one version of
        the same event; GAIL's 31 July result had four. The panel
        showed the oldest.

        The obvious fix -- UPDATE the row where
        (symbol, at, kind, source) matches -- was written here, and
        tests/test_events_idempotent.py caught it in one run:

            "Deduplication that swallows real events is worse than the
             duplication it replaced."

        That key does NOT identify one message. Market-wide events
        carry no symbol, and two genuinely different stories arriving
        in the same second would have collapsed into one. A bulk
        collapse tool hit the identical wall and was thrown away after
        its dry run offered to delete "INDIA-EU FTA WILL BE A GAME
        CHANGER" as a duplicate of a solar-power story.

        So nothing is replaced and nothing is deleted. recent() reads
        `at DESC, id DESC` instead, which shows the newest version of
        an event without touching what is on disk. Extra rows cost
        disk; a swallowed event costs a trade.
        """
        if kind not in USEFUL_KINDS:
            return False

        # ---- THE SAME EVENT ON TWO CHANNELS. 29 August 2026. ----
        #
        #     "Duplicates of data is not acceptable at all & if it
        #      still do this is riducolus"          -- operator
        #
        # The unique index is (symbol, at, kind, headline), so the same
        # story posted by two channels two minutes apart inserts twice
        # -- different `at`, different wording, same event:
        #
        #     10:53 RedboxGlobal    ACUTAAS CHEMICALS: APPROVAL RECEIVED
        #     10:55 Day Trader      ACUTAAS CHEMICALS: APPROVAL RECEIVED
        #     14:46 Day Trader      #HCC bags $524 cr HNHPC contract
        #     14:51 OrderBook       HCC secures Rs 524 crore NHPC contract
        #
        # TWO ATTEMPTS AT THIS WERE WRONG BEFORE (see below), and both
        # failed the same way -- a key that did not identify one story.
        # A bulk tool offered to delete "INDIA-EU FTA WILL BE A GAME
        # CHANGER" as a duplicate of a solar story.
        #
        # So this matches on the story ITSELF, inside one symbol, one
        # day and one kind:
        #
        #   the normalised headline is identical  -- 101 rows of 13,103
        #   or the same rupee AMOUNT appears      -- 164 rows
        #
        # Measured on the whole store before shipping. Every group
        # inspected was one event on two channels; the amount rule is
        # what catches HCC and SAATVIKGL, where the wording differs but
        # "524 cr" and "476 cr" do not.
        #
        # It cannot reach across symbols or days, which is exactly what
        # the FTA/solar collapse did. DEDUPE_EVENTS = False disables it
        # and restores insert-only.
        if DEDUPE_EVENTS and symbol and self._already_have(symbol, at, kind,
                                                           headline, value_cr):
            return False

        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                before = conn.total_changes
                conn.execute(
                    "INSERT OR IGNORE INTO events (symbol, at, kind, scope,"
                    " grade, value_cr, counterparty, headline, source, url,"
                    " from_image, created_at, detail)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (symbol, str(at or ""), kind, scope, grade, value_cr,
                     counterparty, (headline or "")[:400], source, url,
                     1 if from_image else 0,
                     datetime.now().isoformat(timespec="seconds"),
                     _detail_json(detail)))
                conn.commit()
                added = conn.total_changes - before
                conn.close()
            return bool(added)
        except sqlite3.Error as exc:
            diagnostic(f"[EVENTS] write failed: {exc}")
            return False

    @staticmethod
    def _same_headline_key(headline):
        """The headline stripped to the words that identify the story.

        Leading #TICKER, case and punctuation all differ between
        channels reposting the same line; none of them change what
        happened.
        """
        text = re.sub(r"^#\S+\s*", "", str(headline or ""))
        text = re.sub(r"[^a-z0-9]+", " ", text.lower())
        return " ".join(text.split())

    def _already_have(self, symbol, at, kind, headline, value_cr=None):
        """Is this story already stored for this stock, today, as this
        kind? See remember() for the measurement behind the two rules.

        Fail-open: any error here means the event is stored. A missing
        event costs a trade; a duplicate costs a row.
        """
        try:
            day = str(at or "")[:10]
            if not day:
                return False
            key = self._same_headline_key(headline)
            amounts = set(self._amounts(headline))
            if value_cr:
                amounts.add(round(float(value_cr), 2))
            if not key and not amounts:
                return False
            rows = self._query(
                "SELECT headline, value_cr FROM events "
                "WHERE symbol = ? AND kind = ? AND substr(at,1,10) = ?",
                (str(symbol).upper(), kind, day))
            for row in rows:
                if key and self._same_headline_key(row.get("headline")) == key:
                    return True
                if amounts:
                    theirs = set(self._amounts(row.get("headline")))
                    if row.get("value_cr"):
                        theirs.add(round(float(row["value_cr"]), 2))
                    if amounts & theirs:
                        return True
                # ==================================================
                # THE SAME STORY IN SOMEBODY ELSE'S WORDS.
                #                             5 September 2026.
                # ==================================================
                #
                #     "Duplicates of data is not acceptable at all"
                #                                  -- the operator
                #
                # The two rules above need the headline to match
                # WORD FOR WORD after normalising, or to name the same
                # rupee figure. Two channels carrying one announcement
                # do neither:
                #
                #   RedboxGlobal  "ACME SOLAR: CO RECEIVES LOI FOR
                #                  300 MW, AT A TARIFF OF RS 6.00..."
                #   Day Trader    "ACME SOLAR: CO RECEIVES LOI FOR
                #                  300 MW, AT A TARIFF OF RS 6.00..."
                #
                # -- same event, different transcription, no crore
                # figure in either. Counted on the store: 349 events
                # since 25 July are one announcement stored more than
                # once. 146 of them arrived on a DIFFERENT channel.
                #
                # _same_story() was written for this in August and only
                # ever used to tidy the DISPLAY -- the recurring fault
                # in this codebase, machinery built and never called on
                # the path that matters. It is called here now.
                #
                # WHY IT CANNOT MERGE TWO REAL STORIES: when BOTH
                # headlines name money it requires the SAME money, so
                # Ather's Rs 960cr on the 26th and Rs 1,758cr on the
                # 28th stay two events. The word-overlap fallback runs
                # only when at least one side names no figure at all,
                # and needs four shared words and 60% containment.
                # Verified against every event since 25 July: of the
                # 349 it suppresses, none is a second real story.
                if self._same_story(headline, row.get("headline")):
                    return True
            return False
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[EVENTS] duplicate check failed ({exc}); storing it.")
            return False

    def _query(self, sql, params=()):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            diagnostic(f"[EVENTS] read failed: {exc}")
            return []

    def for_symbol(self, symbol, limit=20):
        """Everything that has happened to one stock, newest first.

        The question the stock card exists to answer.
        """
        if not symbol:
            return []
        return self._query(
            "SELECT * FROM events WHERE symbol = ? "
            "ORDER BY at DESC, id DESC LIMIT ?", (str(symbol).upper(), limit))

    @staticmethod
    def _story_key(headline):
        """The words that identify a story, for comparing two of them.

        Lowercased, punctuation dropped, short words dropped. Numbers
        are KEPT -- "1,758 cr" is what makes the 28 August Ather story
        a different story from the "960 cr" one on the 26th, and
        dropping figures would merge two real events into one.
        """
        import re
        text = re.sub(r"[^a-z0-9 ]", " ", str(headline or "").lower())
        return frozenset(w for w in text.split() if len(w) > 3)

    @staticmethod
    def _amounts(headline):
        """The rupee figures a headline names, normalised.

        ---- THE NUMBER IS THE STORY. 29 August 2026 ----

        Word overlap is the wrong tool on this feed. The same Ather
        announcement arrived as:

            "To buy additional stake in Ather Energy for 1,758 cr
             ... phe 4 y NOW IN|"            (OCR'd, noisy)
            "HERO MOTOCORP: CO TO ACQUIRE ADDITIONAL STAKE ...
             FOR UP TO 1,758 CRORE"

        Different verbs, different length, OCR rubbish in one -- 4
        shared words out of 8, which no sensible text threshold calls
        the same. Yet a human reads them as one announcement instantly,
        because of 1,758.

        The figure is also what separates the two REAL events: Rs 960cr
        on the 26th, Rs 1,758cr on the 28th. A text rule that merged
        those would be worse than counting repeats.

        Returns the set of numbers appearing near cr/crore/lakh, so a
        percentage or a date does not become a story id.
        """
        import re
        text = str(headline or "").lower().replace(",", "")
        found = set()
        for match in re.finditer(
                r"(\d+(?:\.\d+)?)\s*(cr\b|crore|lakh)", text):
            try:
                found.add(round(float(match.group(1)), 1))
            except ValueError:
                continue
        return found

    @classmethod
    def _same_story(cls, a, b, threshold=0.6, min_shared=4):
        """Are these two headlines the same news told twice?

        A shared rupee FIGURE settles it -- see _amounts(). Falling
        back to word containment only when neither names an amount,
        with min_shared so two short headlines cannot match on three
        common words.
        """
        amounts_a, amounts_b = cls._amounts(a), cls._amounts(b)
        if amounts_a and amounts_b:
            # Both name money: same story only if they name the SAME
            # money. This is what keeps Rs 960cr and Rs 1,758cr apart.
            return bool(amounts_a & amounts_b)
        ka, kb = cls._story_key(a), cls._story_key(b)
        if not ka or not kb:
            return False
        shared = len(ka & kb)
        if shared < min_shared:
            return False
        return shared / min(len(ka), len(kb)) > threshold

    @classmethod
    def distinct_stories(cls, rows, headline_of=None, at_of=None):
        """Collapse a stock's events to the STORIES behind them.

        ---- THE SAME NEWS, COUNTED TWICE. 29 August 2026 ----

            "pls check incase of duplicate info being taken as multiple
             times as different channels are being sourced"
            "chip should show stories not repeats"
                                    -- operator, 29 August 2026

        ATHERENERG, 28 August:

            08:15  "To buy additional stake in Ather Energy for 1,758 cr"
            09:01  "HERO MOTOCORP: CO TO ACQUIRE ADDITIONAL STAKE ...
                    FOR UP TO 1,758 CR"

        One announcement, 46 minutes apart -- a channel reposting
        another channel's card. Across the store since 22 August: 899
        events, 171 stock-day groups with two or more, and 80 that are
        the same story repeated.

        That is ~9% of the feed, and it inflated the run chip: Ather
        read "4 events / 2 days" when it is TWO stories -- Rs 960cr on
        the 26th and Rs 1,758cr on the 28th -- told four times.

        Keeps the EARLIEST of each group, which is also the fastest
        source and therefore the one worth measuring lag against.
        Returns the kept rows, oldest first.
        """
        headline_of = headline_of or (lambda r: r["headline"])
        at_of = at_of or (lambda r: r["at"])
        ordered = sorted(rows or [], key=lambda r: str(at_of(r) or ""))
        kept = []
        for row in ordered:
            text = headline_of(row)
            if any(cls._same_story(text, headline_of(k)) for k in kept):
                continue
            kept.append(row)
        return kept

    def _move_on(self, symbol, day):
        """What the stock did on `day`, and since. Or None.

        {"day_pct": that session open->close,
         "since_pct": that session's open -> the latest close on file}

        From core/daily_store.py -- the settled record. Never live
        ticks: an outcome that moves while you read it is not an
        outcome. None when the day is not on file, which is the honest
        answer for today's own story before today has closed.
        """
        if not symbol or not day:
            return None
        try:
            if getattr(self, "_daily", None) is None:
                from core.daily_store import DailyStore
                self._daily = DailyStore()
            from sqlalchemy import select
            bars = self._daily.bars
            with self._daily.engine.connect() as conn:
                row = conn.execute(
                    select(bars.c.open, bars.c.close)
                    .where(bars.c.symbol == str(symbol).upper())
                    .where(bars.c.date == str(day))).first()
                if not row or not row[0]:
                    return None
                opened, closed = float(row[0]), float(row[1])
                latest = conn.execute(
                    select(bars.c.close)
                    .where(bars.c.symbol == str(symbol).upper())
                    .where(bars.c.date >= str(day))
                    .order_by(bars.c.date.desc())).first()
            last = float(latest[0]) if latest and latest[0] else closed
            return {
                "day_pct": round((closed - opened) / opened * 100.0, 2),
                "since_pct": round((last - opened) / opened * 100.0, 2),
            }
        except Exception:                                   # noqa: BLE001
            return None

    def running_story(self, symbol, days=7, now=None):
        """Has this stock had a RUN of events, not just one? Or None.

        ---- ONE STOCK, FOUR EVENTS, TWO DAYS. 29 August 2026 ----

            "in this case ather energy got multiple events in multi
             days & bot must relate & show the details highlighting
             the info next to ather energy stock"
                                    -- operator, 29 August 2026

        ATHERENERG, 26-28 August:

            26 Aug 08:56  Hero invests Rs 960cr via convertible warrants
            28 Aug 08:15  To buy additional stake for Rs 1,758cr
            28 Aug 09:01  Hero to acquire additional stake, Rs 1,758cr
            28 Aug 11:07  Ather up 7%, F&O entrant, largest shareholder

        One story told four times across two sessions, and the stock
        ran +8.9% from where the bot named it on the 26th to Friday's
        close. Every row was already on file. Nothing ever asked the
        question "has this happened before, recently, to this stock" --
        so each event was read alone, on the day it arrived, and the
        run was invisible.

        A single event is news. A RUN is a situation: somebody is
        buying a company in public, in instalments, and the tape has
        two or three days to react rather than twenty minutes.

        Returns {"events", "days", "first_at", "last_at", "kinds",
        "headlines"} or None when there is only one event -- one is
        not a story and saying so would be inventing a pattern.

        Reads what is already stored. No new collection, no AI.
        """
        if not symbol:
            return None
        try:
            from datetime import datetime, timedelta
            clock = now or datetime.now()
            since = (clock - timedelta(days=int(days))).strftime("%Y-%m-%d")
            rows = self._query(
                "SELECT at, kind, headline, source FROM events "
                "WHERE symbol = ? AND at >= ? AND kind IN "
                "('NEWS','ORDER','RESULT','CONCALL','AI_VERDICT') "
                # `id DESC`, not `at DESC` alone. When an event is
                # CORRECTED the store keeps both rows with the same
                # `at`, and without the tiebreak SQLite returns an
                # arbitrary one -- in practice the oldest, so the
                # panel would show the version that was corrected.
                # tests/test_event_row_cap.py bans the bare form.
                "ORDER BY at DESC, id DESC LIMIT 20",
                (str(symbol).upper(), since))
        except Exception:                                   # noqa: BLE001
            return None
        # STORIES, not repeats. ~9% of the feed is one channel
        # reposting another, and counting those inflated Ather to
        # "4 events / 2 days" when it is two announcements.
        rows = self.distinct_stories(
            rows,
            headline_of=lambda r: r["headline"] if hasattr(r, "keys") else r[2],
            at_of=lambda r: r["at"] if hasattr(r, "keys") else r[0])
        if not rows or len(rows) < 2:
            return None

        def _get(row, key, index):
            try:
                return row[key]
            except Exception:                               # noqa: BLE001
                return row[index]

        stamps = [str(_get(r, "at", 0) or "") for r in rows]
        sessions = {stamp[:10] for stamp in stamps if stamp}
        # ---- AND WHAT DID THE STOCK DO? 29 August 2026 ----
        #
        #     "i want to see the linkage (memory brain + map = links to
        #      stocks + news/events + outcome if the stock movement
        #      from that day)"           -- operator, 29 August 2026
        #
        # A story with no outcome is a headline. The point of keeping a
        # run is to see whether the run WORKED: Hero raised its Ather
        # stake on the 26th (+3.4% that session) and again on the 28th
        # (+6.1%), and the stock closed +8.9% above where the bot named
        # it. Without the move attached, the chip is trivia.
        #
        # Read from the daily store, which is the settled record --
        # never from live ticks, which would make an outcome that
        # changes while you look at it.
        # ---- THREE, NEWEST FIRST. 29 August 2026 ----
        #
        #     "ather chip showed but the info looks ugly next to
        #      welcorp. can u show them in neat & precise"
        #                                    -- operator, 29 Aug 2026
        #
        # WELCORP carried nine, and reading them one by one showed
        # what nine really means: three tellings of one 26 August
        # block deal, a sector list that never mentions the company,
        # and a Welspun LIVING headline filed against Welspun CORP.
        # Four real stories at most.
        #
        # The count is left honest -- it still says nine, because that
        # is what is on file and hiding it would be worse -- but the
        # chip shows the three most recent and says how many remain.
        # A tooltip nobody can read is not evidence.
        # The most RECENT three, still in date order so "first event,
        # second event" reads the way he asked for it. rows arrive
        # oldest-first from distinct_stories(), so the tail is newest.
        total = len(rows)
        rows = rows[-3:]
        told = []
        for row in rows:
            at = str(_get(row, "at", 0) or "")
            told.append({
                "at": at,
                "headline": str(_get(row, "headline", 2) or "")[:110],
                "kind": str(_get(row, "kind", 1) or ""),
                "outcome": self._move_on(symbol, at[:10]),
            })

        return {
            "stories": total,
            "events": total,          # kept: existing readers
            "told": told,
            "more": max(0, total - len(told)),
            "days": len(sessions),
            "first_at": min(stamps) if stamps else None,
            "last_at": max(stamps) if stamps else None,
            "kinds": sorted({str(_get(r, "kind", 1) or "") for r in rows}),
            "headlines": [str(_get(r, "headline", 2) or "")[:110]
                          for r in rows[:4]],
        }

    def needing_a_verdict(self, limit=500, hours=None):
        """Events with a kind but no direction -- what the model is for.

        Deliberately EXCLUDES anything already graded. An Earnings
        Pulse "Excellent Results" is already a direction, published by
        a source we trust, and paying a model to agree with it would be
        spending money to learn nothing.

        That single filter is why this costs Rs 53 a month instead of
        Rs 657: about a third of events arrive with a grade already on
        them.
        """
        # STOCK SCOPE ONLY, and that is not a saving -- it is the
        # definition of the job.
        #
        # core/shortlist.py reads events with scope="STOCK". A
        # market-scope row has no symbol by design ("a Fed hold belongs
        # to no company") and can never reach a why-chip, so a verdict
        # on one could not be acted on, shown, or measured.
        #
        # It also happens to be where the money is. Of the 270 ungraded
        # events on 31 July, 129 were market scope and included
        # "Earnings Pulse pinned a photo" and "How to add stocks to the
        # watchlist" -- channel housekeeping. Paying a model to have an
        # opinion about those is the exact waste this filter prevents.
        sql = ("SELECT * FROM events WHERE (grade IS NULL OR grade = '') "
               "AND (ai_direction IS NULL OR ai_direction = '') "
               "AND scope = 'STOCK' AND symbol IS NOT NULL "
               "AND kind IN ('NEWS', 'ORDER')")
        params = []
        if hours:
            sql += " AND at >= ?"
            params.append((datetime.now() - timedelta(hours=hours)).isoformat())
        # ---- id DESC IS NOT DECORATION. 1 August 2026. ----
        #
        # The unique index includes the HEADLINE, so a parser
        # improvement writes a SECOND row beside the old one rather
        # than correcting it. 389 stocks carried more than one version
        # of the same event; GAIL's 31 July result had four.
        #
        # With only "at DESC" and identical timestamps SQLite hands
        # them back in insertion order, so the panel showed the OLDEST
        # -- a headline fix that wrote correctly displayed nothing,
        # which is indistinguishable from a fix that does not work.
        #
        # remember() now updates in place, so this stops accumulating.
        # This line makes the rows ALREADY on disk read correctly, and
        # it deletes nothing. A bulk collapse was written and measured
        # first: its grouping key merged genuinely different market
        # news that happened to share a timestamp, so it was thrown
        # away rather than run.
        sql += " ORDER BY at DESC, id DESC LIMIT ?"
        params.append(limit)
        return self._query(sql, params)

    def record_verdict(self, event_id, direction, confidence=None,
                       reason=None, model=None, when=None):
        """Attach one model verdict to one event. Returns True if written.

        Keyed by the event's own id rather than by (symbol, at), so a
        story filed against three companies gets three verdicts and
        they are allowed to disagree -- which they should, because the
        same news is often good for one and bad for another.
        """
        direction = str(direction or "").strip().upper()
        if direction not in VERDICTS:
            diagnostic(f"[EVENTS] refusing verdict {direction!r} -- not one "
                       f"of {' / '.join(VERDICTS)}")
            return False
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "UPDATE events SET ai_direction = ?, ai_confidence = ?,"
                    " ai_reason = ?, ai_model = ?, ai_at = ? WHERE id = ?",
                    (direction,
                     None if confidence is None else float(confidence),
                     (reason or "")[:300] or None, model or None,
                     (when or datetime.now()).isoformat(timespec="seconds"),
                     int(event_id)))
                conn.commit()
                conn.close()
            return True
        except (sqlite3.Error, TypeError, ValueError) as exc:
            diagnostic(f"[EVENTS] could not store verdict: {exc}")
            return False

    def recent(self, limit=40, hours=None, kind=None, scope="STOCK"):
        sql = "SELECT * FROM events WHERE 1=1"
        params = []
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if hours:
            sql += " AND at >= ?"
            params.append((datetime.now() - timedelta(hours=hours)).isoformat())
        # ---- id DESC IS NOT DECORATION. 1 August 2026. ----
        #
        # The unique index includes the HEADLINE, so a parser
        # improvement writes a SECOND row beside the old one rather
        # than correcting it. 389 stocks carried more than one version
        # of the same event; GAIL's 31 July result had four.
        #
        # With only "at DESC" and identical timestamps SQLite hands
        # them back in insertion order, so the panel showed the OLDEST
        # -- a headline fix that wrote correctly displayed nothing,
        # which is indistinguishable from a fix that does not work.
        #
        # remember() now updates in place, so this stops accumulating.
        # This line makes the rows ALREADY on disk read correctly, and
        # it deletes nothing. A bulk collapse was written and measured
        # first: its grouping key merged genuinely different market
        # news that happened to share a timestamp, so it was thrown
        # away rather than run.
        sql += " ORDER BY at DESC, id DESC LIMIT ?"
        params.append(limit)
        return self._query(sql, params)

    def market_context(self, limit=15, hours=36):
        """The things that moved everything -- never pinned to a stock."""
        return self.recent(limit=limit, hours=hours, scope="MARKET")

    def symbols_with_events(self, hours=36):
        rows = self._query(
            "SELECT symbol, COUNT(*) n FROM events "
            "WHERE scope='STOCK' AND at >= ? GROUP BY symbol ORDER BY n DESC",
            ((datetime.now() - timedelta(hours=hours)).isoformat(),))
        return {r["symbol"]: r["n"] for r in rows if r["symbol"]}

    def status(self):
        rows = self._query("SELECT kind, COUNT(*) n FROM events GROUP BY kind")
        total = sum(r["n"] for r in rows)
        return {"total": total,
                "by_kind": {r["kind"]: r["n"] for r in rows},
                "available": True}
