"""
==========================================================
Channel chatter, and the words that are also finance
==========================================================

    "daytrader telugu needs to be avoided on weekends & links they
     are posting"
    "they will be posting their youtube links all weekends"
    "we made that to avoid links from that channel right? forgot
     again??"   "not now since begining"
                                -- the operator, 5 September 2026

He was right on the last point, and it is the reason this file exists.

WHAT WAS ALREADY THERE. core/stock_events.NOISE has matched YouTube
links, /shorts/ and "must watch" since 2 August, from his own
instruction -- "off the clickable youtube links; Insurance links; excel
sheet links from this channel". It works: there are ZERO events of kind
NOISE on file, so not one of those posts has ever reached a stock.

WHAT WAS DONE WRONG. A second rule, is_video_promo(), was written on 5
September before checking whether one existed. Measured across all
2,016 stored messages it caught 17 the old rule already had, missed 52
it catches, and added exactly 4. It was deleted and those four patterns
folded into the rule that was already there.

WHAT THE AUDIT THEN FOUND -- the part worth keeping. Asking of EACH
word what it holds back ON ITS OWN turned up three that were throwing
real filings away:

    follow us on   84 messages, 26 naming a stock. Added that same
                   hour, and reverted within it: the Day Trader Telugu
                   cards carry "Follow us on @etnowlive" as ET Now's
                   watermark. It was about to discard the Welspun MoU,
                   the Mahanadi IPO and the Cupid promoter purchase --
                   the exact cards saved from the digest rule that
                   morning.

    subscribe      24 messages, 17 naming a stock, every one real.
                   "Subscribed" is finance vocabulary:
                     FLAIR WRITING: CO SUBSCRIBES TO 100 CRORE RIGHTS
                       ISSUE OF WHOLLY OWNED SUBSIDIARY
                     VODAFONE IDEA: JULY NET MOBILE SUBSCRIBER ADDS
                     Purple Style Labs IPO subscribed 24% on day two

    deadline       4 messages, 3 naming a stock. An order win states
                   its delivery deadline:
                     ARTSON LTD: RECEIVES PURCHASE ORDER WORTH 7.17 CR
                       ... EXECUTION DEADLINES SET FOR 2027

Noise fell from 157 messages to 45, and 112 real ones came back.

WHY IT MATTERS. A published reason is MANDATORY before the ranker will
evaluate a stock at all. A word that silently discards a filing does
not cost a panel row -- it costs the door.

AND THE CHANNEL. He watches Day Trader Telugu and I do not: "they will
be posting their youtube links all weekends." So it is not polled on
Saturday or Sunday. That is NOT a rule about collecting at the weekend
in general -- the weekend is exactly when gaps form, and every other
channel must keep being read.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

import pytest

from core.stock_events import NOISE, classify
from core.telegram_feed import TelegramFeed


def noisy(text):
    return bool(NOISE.search(text))


# ------------------------------------------------------------------
# what must be refused
# ------------------------------------------------------------------

def test_the_telugu_youtube_post_is_chatter():
    """Post 208202, verbatim. 'ACC' sits inside the Telugu word for
    ACCOUNT and ACC is a real NSE ticker."""
    assert noisy("మీకు SBI ACC ఉందా ?🤩 శుభవార్త "
                 "https://youtube.com/shorts/R3Z86")
    assert classify("Must Watch Shorts https://youtu.be/8YUdkQ2J5pk",
                    has_symbol=True)[0] == "NOISE"


def test_the_channel_advertising_itself_is_chatter():
    """RedboxGlobal India, four messages, no stock named in any."""
    for text in ("WE'RE NOW LIVE ON INSTAGRAM! Get market-moving news "
                 "before everyone else.",
                 "We're building something bigger on Facebook.",
                 "Follow us on Facebook. "
                 "https://www.facebook.com/people/RedboxGlobal-India/",
                 "JOIN US ON INSTAGRAM"):
        assert noisy(text), text


# ------------------------------------------------------------------
# what must NOT be refused -- the three that were
# ------------------------------------------------------------------

def test_the_et_now_watermark_is_not_chatter():
    """'Follow us on @etnowlive' is printed on every Day Trader Telugu
    news card. 26 real cards were about to go."""
    assert not noisy(
        "STSCK IN NEWS WELSPUN CORP Co & Perma-Pipe International "
        "Holdings sign MoU with Govt of Jordan. Follow us on @etnowlive")
    assert not noisy(
        "NEWS ALERT Mahanadi Coalfields files for India IPO. Coal India "
        "offers up to 661.8 mn shares. Follow us on @etnowlive")


def test_subscribing_to_a_rights_issue_is_not_chatter():
    assert not noisy("FLAIR WRITING INDUSTRIES: CO SUBSCRIBES TO 100 "
                     "CRORE RIGHTS ISSUE OF WHOLLY OWNED SUBSIDIARY")
    assert not noisy("VODAFONE IDEA: JULY NET MOBILE SUBSCRIBER ADDS "
                     "240,114")
    assert not noisy("Purple Style Labs IPO enters its final day after "
                     "being subscribed 24% on day two")


def test_an_orders_delivery_deadline_is_not_chatter():
    assert not noisy(
        "ARTSON LTD: CO. RECEIVES PURCHASE ORDER WORTH 7.17 CR FROM "
        "L&T - MHI POWER BOILERS; EXECUTION DEADLINES SET FOR 2027")
    assert not noisy("India has set an April 2027 deadline for electric "
                     "truck manufacturers to localize production")


def test_the_promo_phrasing_still_works():
    """Narrowed, not removed -- a real promo still says it plainly."""
    assert noisy("Subscribe to our channel for daily updates")
    assert noisy("Subscribe now for market alerts")


# ------------------------------------------------------------------
# and no second rule
# ------------------------------------------------------------------

def test_there_is_only_one_rule_for_this():
    """A duplicate was written on 5 September and deleted the same
    hour. This is the check that it does not come back."""
    import io
    src = io.open("core/stock_events.py", encoding="utf-8").read()
    assert "is_video_promo" not in src, \
        "a second chatter rule has appeared; NOISE is the one"


# ------------------------------------------------------------------
# the weekend rule
# ------------------------------------------------------------------

@pytest.fixture()
def feed(tmp_path):
    got = TelegramFeed(db_path=str(tmp_path / "tg.db"))
    got.channels = [
        {"handle": "daytradertelugu", "name": "Day Trader Telugu"},
        {"handle": "orders_pulse", "name": "OrderBook Pulse"},
        {"handle": "Indiaredboxglobal", "name": "RedboxGlobal India"},
    ]
    return got


def _names(feed, fast, monkeypatch, weekend):
    import core.telegram_feed as tf

    class _When:
        @staticmethod
        def now():
            # 2026-09-05 is a Saturday; 2026-09-07 a Monday.
            return datetime(2026, 9, 5 if weekend else 7, 10, 0)

    monkeypatch.setattr(tf, "datetime", _When)
    return {c["name"] for c in feed._channels_for(fast=fast)}


def test_it_is_skipped_on_a_saturday(feed, monkeypatch):
    picked = _names(feed, None, monkeypatch, weekend=True)
    assert "Day Trader Telugu" not in picked
    assert "OrderBook Pulse" in picked, "only that one channel is skipped"


def test_it_is_read_on_a_weekday(feed, monkeypatch):
    assert "Day Trader Telugu" in _names(feed, None, monkeypatch,
                                         weekend=False)


def test_the_fast_pass_skips_it_too(feed, monkeypatch):
    assert "Day Trader Telugu" not in _names(feed, True, monkeypatch,
                                             weekend=True)


def test_every_other_channel_still_runs_at_the_weekend(feed, monkeypatch):
    """The weekend is exactly when the gaps form."""
    picked = _names(feed, None, monkeypatch, weekend=True)
    assert {"OrderBook Pulse", "RedboxGlobal India"} <= picked


def test_the_list_is_never_emptied(feed, monkeypatch):
    feed.channels = [{"handle": "daytradertelugu",
                      "name": "Day Trader Telugu"}]
    assert _names(feed, None, monkeypatch, weekend=True) == \
        {"Day Trader Telugu"}


# ==========================================================
#  A LINK IS NOT A REASON -- AT THE DOOR.  6 September 2026.
# ==========================================================
#
#     "do not get the youtube links & any other links . not only in
#      this channel , this applies to all other channels"
#                                             -- the operator
#
# The NOISE patterns already refused these as EVENTS. He asked for
# something stronger: do not collect them at all. So the test is on
# the store, not the classifier.
#
# NOT "any message containing http". All 31 link-bearing messages were
# read before the rule was written, and the morning briefing carries
# both a t.me pointer and the day's F&O ban list -- INOXWIND, KAYNES,
# LICHSGFIN, SAIL. A blanket rule throws that away.
#
# Measured over the whole store: 27 of 1,612 messages refused, and of
# the six that had named a stock, four were "Gold in Bank Locker" shorts
# filed against ACC and two were video contents-lists.

def test_a_youtube_short_is_never_collected():
    from core.telegram_feed import is_just_a_link
    assert is_just_a_link(
        "Must Watch Shorts - Gold in Bank Locker? Not Safe? "
        "https://youtube.com/shorts/KI-SIubw1-g") is True


def test_every_advertisement_destination_is_refused():
    from core.telegram_feed import is_just_a_link
    for text in (
            "watch this https://youtu.be/3oEIE_n5VTo",
            "WE'RE NOW LIVE ON INSTAGRAM https://instagram.com/redbox",
            "building something bigger https://facebook.com/redbox",
            "clip here https://fb.watch/xyz",
            "Support Our Work Term Policy https://bit.ly/_Term_Policy",
            "Add all Pro channels https://t.me/addlist/Dxp1klf3",
            "deal https://aonelink.in/abc"):
        assert is_just_a_link(text) is True, text


def test_the_morning_briefing_survives():
    """It ends in a t.me pointer and carries the day's F&O ban list.
    A blanket http rule would have thrown it away -- the same
    over-reach that nearly cost the Welspun MoU."""
    from core.telegram_feed import is_just_a_link
    assert is_just_a_link(
        "#MorningMarketWithDTT ~ 4 SEPT\nToday's Stocks in News\n"
        "https://t.me/daytradertelugu/208120\nF&O BAN\n1,INOXWIND\n"
        "2,KAYNES\n3,LICHSGFIN\n4,SAIL") is False


def test_a_filing_with_no_link_is_untouched():
    from core.telegram_feed import is_just_a_link
    assert is_just_a_link(
        "WELSPUN CORP: CO. SECURES LARGEST-EVER SINGLE ORDER") is False


def test_the_store_itself_turns_them_away():
    """The rule has to be ON the store, not only importable. He asked
    for them not COLLECTED, not merely not classified."""
    import io
    src = io.open("core/telegram_feed.py", encoding="utf-8").read()
    assert "if is_just_a_link(text):" in src, \
        "the rule exists and _store never calls it"


def test_the_rule_lives_outside_the_class():
    """---- IT ENDED THE CLASS. 6 September 2026. ----

    First attempt put NEVER_A_REASON and is_just_a_link at column 0 in
    the middle of the class body, which closed the class. _store and
    every method after it became module functions, and 22 tests failed
    with "'TelegramFeed' object has no attribute '_store'".
    """
    from core.telegram_feed import TelegramFeed
    for method in ("_store", "poll", "channel_report", "listen"):
        assert hasattr(TelegramFeed, method), \
            f"TelegramFeed lost {method} -- something closed the class early"
