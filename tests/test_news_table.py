"""
==========================================================
One row per stock, not one row per message
==========================================================

    "News collected - now it is a hell of mess with repeated items
     without clarity ... i need a clean table with
     Symbol  News (here details)  Time
     and mostly if the same stock gets more news, results from our
     sources. simply add them next to news column . not to print a
     separate line alone."
                                    -- operator, 1 August 2026

MEASURED ON THE REAL STORE, 1 AUGUST 2026
-----------------------------------------
300 stored messages produced 300 lines. After this module: 140 stock
rows and 128 market items, with every message still reachable.

FIVE THINGS WERE WRONG, AND EACH ONE COST A LINE OF THE OPERATOR'S
ATTENTION AT 09:10 WITH A MINUTE TO DECIDE
------------------------------------------------------------------
1. A BOT'S OWN CHATTER RANKED AS NEWS. @WLPulseBot is a bot we talk
   to, so "/start", "Logged in!" and "Subscription Activated!" landed
   in the same table as earnings -- at the TOP, being the most recent
   thing that had happened.

2. THE SAME STOCK APPEARED AS UNRELATED PARAGRAPHS.

       Earnings 360    GHCL - Q1 FY27 Exceptional gain from ESOS...
       Earnings Pulse  #GHCL - OK Results - 32 seconds ago

   Two readings of one quarter, printed as two separate items.

3. THE HEADLINE WAS THE TITLE, WITH THE NEWS ON THE NEXT LINE.
   Earnings 360 writes

       #GHCL - Q1 FY27
       Exceptional gain from ESOS Trust settlement inflates an
       otherwise solid quarter.

   Taking the first usable line gave a table of "GHCL — Q1 FY27" and
   "CLEAN — Q1 FY27": a list of things that happened with the news
   removed.

4. YESTERDAY LOOKED LIKE THE NEWEST THING IN THE ROW. JIOFIN showed
   08:11, 07:03 and 14:28 -- and 14:28 was the PREVIOUS DAY. A time
   column that puts yesterday above this morning is worse than no
   time column.

5. A WHOLE-SESSION PAGE SAT ON INDIVIDUAL STOCKS. "Today Earnings -
   01 Aug, 2026" names a dozen tickers, so a few of them carried it
   at the top of their row, above their own result.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No judging, no scoring, no ranking. Ordering is by time. Deciding
which news matters is core/shortlist.py's job, and it has the evidence
to do it -- this table's only promise is that everything received is
visible and readable.

Author : H&M Opportunity Trader
==========================================================
"""

import json

import pytest

from core.news_table import _clean, _hhmm, build, is_news


def tg(text, channel="Earnings Pulse", at="2026-08-01T08:00:00", symbols=()):
    return {"text": text, "channel": channel, "at": at,
            "symbols": list(symbols)}


# ---------------------------------------------------------------
# 1. A BOT'S OWN CHATTER IS NOT NEWS
# ---------------------------------------------------------------
@pytest.mark.parametrize("junk", [
    "/start",
    "✅ Logged in! You're now signed in on earningspulse.ai as Md.",
    "✅ Subscription Activated! 📦 Plan: Pro Quarterly What's included:",
    "Choose an option below",
    "ok",
])
def test_a_bot_conversation_never_reaches_the_table(junk):
    assert is_news(junk) is False


def test_real_news_is_not_mistaken_for_chatter():
    assert is_news("#GHCL - OK Results") is True
    assert is_news("Reliance bags Rs 2,205 crore order from HAL") is True


def test_the_junk_is_gone_from_the_built_table():
    out = build(telegram_rows=[
        tg("/start", channel="WLPulseBot"),
        tg("✅ Logged in! signed in on earningspulse.ai", channel="WLPulseBot"),
        tg("#GHCL — Q1 FY27\nExceptional gain from ESOS Trust settlement.",
           symbols=["GHCL"]),
    ])
    assert [r["symbol"] for r in out["stocks"]] == ["GHCL"]
    assert out["market"] == []


# ---------------------------------------------------------------
# 2. ONE ROW PER STOCK
# ---------------------------------------------------------------
def test_two_channels_on_one_quarter_make_one_row():
    """The GHCL case. Two readings of one result, and they belong
    beside each other or the operator reads the stock twice without
    knowing it."""
    out = build(telegram_rows=[
        tg("#GHCL — Q1 FY27\nExceptional gain from ESOS Trust settlement "
           "inflates an otherwise solid quarter.",
           channel="Earnings 360", at="2026-08-01T07:51:00", symbols=["GHCL"]),
        tg("#GHCL - 🌱 OK Results - 32 seconds ago",
           channel="Earnings Pulse", at="2026-08-01T07:51:30",
           symbols=["GHCL"]),
    ])
    assert len(out["stocks"]) == 1
    row = out["stocks"][0]
    assert row["symbol"] == "GHCL" and row["count"] == 2
    assert {i["source"] for i in row["items"]} == {"Earnings 360",
                                                   "Earnings Pulse"}


def test_every_item_keeps_its_own_source_and_clock():
    """"clear what happened & from which sources we got them & at what
    time" -- the source cannot be collapsed to the row.

    `today` is PINNED. Without it this test read the real clock, so it
    passed on 1 August and failed on 2 August with

        ['1 Aug 07:51'] != ['07:51']

    -- because _hhmm() adds the date once an item is no longer today's,
    which is exactly what it was built to do. A test that only passes
    on the day it was written is a test that will cry wolf on a
    Saturday and be ignored on the Monday it matters. The neighbouring
    tests already pin it; this one was the odd man out.
    """
    out = build(telegram_rows=[
        tg("#GHCL — Q1 FY27\nExceptional gain from ESOS Trust.",
           channel="Earnings 360", at="2026-08-01T07:51:00", symbols=["GHCL"]),
        tg("#GHCL - OK Results", channel="Earnings Pulse",
           at="2026-08-01T06:20:00", symbols=["GHCL"]),
    ], today="2026-08-01")
    items = out["stocks"][0]["items"]
    assert [i["time"] for i in items] == ["07:51", "06:20"]
    assert items[0]["source"] == "Earnings 360"


def test_the_row_is_stamped_with_its_newest_item():
    out = build(telegram_rows=[
        tg("#GHCL old news here", at="2026-08-01T05:00:00", symbols=["GHCL"]),
        tg("#GHCL newer news here", at="2026-08-01T08:30:00", symbols=["GHCL"]),
    ], today="2026-08-01")
    assert out["stocks"][0]["time"] == "08:30"


def test_a_repeated_symbol_does_not_repeat_the_item():
    """The stored column really does say "GHCL,GHCL" -- a card
    hashtagged twice. Keying on the symbol TUPLE made ('GHCL',) and
    ('GHCL','GHCL') different, so the same sentence printed twice."""
    out = build(telegram_rows=[
        tg("#GHCL — Q1 FY27\nExceptional gain from ESOS.",
           symbols=["GHCL", "GHCL"]),
        tg("#GHCL — Q1 FY27\nExceptional gain from ESOS.",
           symbols=["GHCL"]),
    ])
    assert out["stocks"][0]["count"] == 1


# ---------------------------------------------------------------
# 3. THE HEADLINE CARRIES THE NEWS
# ---------------------------------------------------------------
def test_the_title_is_joined_to_the_sentence_beneath_it():
    """"GHCL — Q1 FY27" is a label. The operator cannot act on it."""
    got = _clean("🟢 #GHCL — Q1 FY27\nExceptional gain from ESOS Trust "
                 "settlement inflates an otherwise solid quarter.\n\n#GHCL")
    assert "Exceptional gain" in got
    assert got.startswith("GHCL")


def test_the_channels_own_freshness_stamp_is_dropped():
    """"- 32 seconds ago" is true for thirty seconds and misleading
    for the rest of the day."""
    assert _clean("#GHCL - OK Results - 32 seconds ago") == "GHCL - OK Results"


def test_page_furniture_is_not_a_headline():
    got = _clean("earningspulse.ai\nAI-generated summary · Not investment "
                 "advice\n#TATAMOTORS wins an order worth Rs 400 Cr")
    assert "earningspulse" not in got.lower()
    assert "wins an order" in got


def test_a_long_card_is_cut_to_a_readable_length():
    got = _clean("#ABC — Q1 FY27\n" + "revenue grew strongly ".join(
        str(n) for n in range(60)))
    assert len(got) <= 152 and got.endswith("…")


# ---------------------------------------------------------------
# 4. YESTERDAY MUST NOT LOOK LIKE THE NEWEST THING
# ---------------------------------------------------------------
def test_todays_item_shows_a_bare_clock():
    assert _hhmm("2026-08-01T08:11:31+00:00", today="2026-08-01") == "08:11"


def test_an_older_item_carries_its_date():
    """JIOFIN's row put 14:28 under 07:03 and both looked like today."""
    assert _hhmm("2026-07-31T14:28:53+00:00",
                 today="2026-08-01") == "31 Jul 14:28"


def test_an_unparseable_stamp_does_not_raise():
    assert _hhmm(None) == ""
    assert _hhmm("nonsense") == ""


# ---------------------------------------------------------------
# 5. MARKET NEWS KEEPS ITS OWN SECTION
# ---------------------------------------------------------------
def test_news_naming_no_stock_goes_to_the_market_section():
    out = build(telegram_rows=[
        tg("Chris Wood cautions that capital expenditure on AI by "
           "hyperscalers could lead to significant overcapacity.",
           channel="News Pulse"),
    ])
    assert out["stocks"] == []
    assert len(out["market"]) == 1
    assert "Chris Wood" in out["market"][0]["text"]


def test_a_whole_session_page_is_not_news_about_one_stock():
    """"Today Earnings - 01 Aug, 2026" names a dozen tickers and says
    nothing about any of them."""
    out = build(telegram_rows=[
        tg("Today Earnings - 01 Aug, 2026\nKey companies reporting results "
           "today across sectors.", symbols=["GHCL", "CLEAN"]),
    ])
    assert out["stocks"] == []
    assert len(out["market"]) == 1


def test_market_news_is_never_sorted_against_stock_news():
    out = build(telegram_rows=[
        tg("Chris Wood cautions on AI capex overcapacity ahead.",
           at="2026-08-01T09:00:00"),
        tg("#GHCL — Q1 FY27\nExceptional gain from ESOS Trust.",
           at="2026-08-01T07:00:00", symbols=["GHCL"]),
    ])
    assert [r["symbol"] for r in out["stocks"]] == ["GHCL"]
    assert len(out["market"]) == 1


# ---------------------------------------------------------------
# 6. IT MUST SURVIVE THE SOCKET, AND EMPTINESS
# ---------------------------------------------------------------
def test_the_payload_is_json_safe():
    """A set in the payload takes the whole dashboard down, and the
    grouping uses one internally."""
    out = build(telegram_rows=[tg("#GHCL — Q1 FY27\nGood quarter here.",
                                  symbols=["GHCL"])])
    json.dumps(out)
    assert "_seen" not in out["stocks"][0]


def test_nothing_collected_is_not_an_error():
    out = build()
    assert out == {"stocks": [], "market": [], "stock_count": 0,
                   "market_count": 0}


def test_a_malformed_row_does_not_take_the_panel_down():
    out = build(telegram_rows=[{}, {"text": None}, {"symbols": ["X"]},
                               tg("#GHCL — Q1 FY27\nA real quarter here.",
                                  symbols=["GHCL"])])
    assert [r["symbol"] for r in out["stocks"]] == ["GHCL"]


def test_rss_and_telegram_land_in_the_same_row():
    out = build(
        rss_rows=[{"headline": "GHCL board approves fund raise of Rs 500 Cr",
                   "source": "Moneycontrol", "at": "2026-08-01T06:00:00",
                   "symbols": ["GHCL"]}],
        telegram_rows=[tg("#GHCL - OK Results", at="2026-08-01T07:51:00",
                          symbols=["GHCL"])])
    assert len(out["stocks"]) == 1
    assert {i["source"] for i in out["stocks"][0]["items"]} == {
        "Moneycontrol", "Earnings Pulse"}


# ---------------------------------------------------------------
# 7. DAY TRADER TELUGU: THE IMAGES, NOT THE PROMO CLIPS
# ---------------------------------------------------------------
#     "DAY TRADER TELUGU WILL NOT USE THIS #COMPANY. THEY WILL
#      POST/FORWARD ONLY IMAGES FROM X WHICH ARE USEFUL FOR OUR CAUSE
#      & EFFECT ON STOCKS + RESULTS + NDTV LIST & WE NEED TO STOP
#      USING THEIR YOUTUBE LINKS (NOT IMPORTANT)"
#                                    -- operator, 1 August 2026
#
# Measured on the store that day: 503 messages, of which 463 are
# images that were OCR'd and 19 are video links.
@pytest.mark.parametrize("clip", [
    "Must Watch Shorts 👇 Gold in Bank Locker? Not Safe https://youtu.be/x",
    "LATEST MARKET UPDATES https://www.youtube.com/watch?v=abcd",
    "BREAKING NEWS https://youtube.com/shorts/xyz",
])
def test_a_video_link_is_not_news(clip):
    """core/stock_events.NOISE has blocked these from becoming EVENTS
    since it was written. This panel reads the stored symbols column,
    not events, so the block never applied here -- and four stocks
    carried a video thumbnail as their news: NTPC, KAYNES, CARTRADE,
    ACC."""
    assert is_news(clip) is False


def test_the_video_block_is_imported_not_restated():
    """Two copies of "what is noise" is how one of them silently stops
    matching the other."""
    src = open("core/news_table.py", encoding="utf-8").read()
    assert "from core.stock_events import NOISE" in src
    # The PATTERN, not the word. The operator's own instruction is
    # quoted in the docstring and says "YOUTUBE LINKS", which is not a
    # second copy of anything -- an earlier version of this test failed
    # on exactly that.
    assert r"youtu\.be" not in src, (
        "the noise pattern must not be spelled out a second time here")
    assert "youtube.com" not in src.replace("YOUTUBE", ""), (
        "the noise pattern must not be spelled out a second time here")


def test_a_video_link_takes_its_stock_row_with_it():
    out = build(telegram_rows=[
        tg("Must Watch Shorts 👇 https://youtu.be/x", channel="Day Trader Telugu",
           symbols=["NTPC"]),
        tg("DIXON TECH: Q1 CONS NET PROFIT 6.6B RUPEES VS 2.25B",
           channel="Day Trader Telugu", symbols=["DIXON"]),
    ])
    assert [r["symbol"] for r in out["stocks"]] == ["DIXON"]


# ---------------------------------------------------------------
# 8. THE TWEET, NOT THE ACCOUNT THAT POSTED IT
# ---------------------------------------------------------------
# The forwarded images are SCREENSHOTS of tweets, and every one opens
# with the poster's account card:
#
#     a= RedboxGlobal India @
#     i= @REDBOXINDIA
#     DIXON TECH: Q1 CONS NET PROFIT 6.6B RUPEES VS 2.25B (YOY)
#
# 23 of 34 rows spent their first forty characters saying REDBOXINDIA.
@pytest.mark.parametrize("header", [
    "a= RedboxGlobal India @",
    "i= @REDBOXINDIA",
    "CNgc CNBC-TV18 @",
    "TV18 @CNBCTV18Live",
    "@REDBOXINDIA",
])
def test_the_x_account_card_is_not_the_headline(header):
    from core.news_table import _X_HEADER
    assert _X_HEADER.match(header)


@pytest.mark.parametrize("real", [
    "DIXON TECH: Q1 CONS NET PROFIT 6.6B RUPEES VS 2.25B (YOY)",
    "#IQWithCNBCTV18 | #SJVN reports its Q1",
    "IRGC SAYS HORMUZ STRAIT IS CLOSED, REQUIRES IRAN PERMIT: IRIB",
    "Clean Science inks 5-year supply deal with Kemin Industries",
])
def test_the_tweet_itself_is_never_mistaken_for_the_header(real):
    from core.news_table import _X_HEADER
    assert not _X_HEADER.match(real)


def test_the_headline_starts_at_the_news():
    """Verbatim from the store, OCR damage included."""
    got = _clean("a= RedboxGlobal India @\ni= @REDBOXINDIA\n"
                 "DIXON TECH: Q1 CONS NET PROFIT 6.6B\n"
                 "RUPEES VS 2.25B (YOY); EST 2.4B\n")
    assert got.startswith("DIXON TECH:")
    assert "REDBOX" not in got.upper()
