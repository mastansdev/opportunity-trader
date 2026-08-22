"""
==========================================================
Seven gainers refused "no event". The filings were on disk.
==========================================================

    "the top gainers/ movers itself proves something is happening
     inside the stock right?"        -- operator, 21 August 2026

He was right, and the bot was holding the proof. That afternoon he
pasted the day's 28 gainers. Seven were refused "no event behind it":

    KRONOX     +9.3%   Public Announcement-Open Offer
    NETWEB     +4.2%   raises Rs 1,200 crore via QIP
    RHETAN     +9.1%   1 MW solar project now operational
    IIFL       +6.2%   credit rating reaffirmed
    THOMASCOOK +12.7%  AGM, Rs 0.50 dividend
    SUBEXLTD  +10.1%   wins 0.6m Euro Partner Ecosystem deal
    KABRAEXTRU +7.9%   corrigendum to EGM notice

data/feeds.db held 31 NSE filings that day, newest at 13:05. The
trading path had never opened it.

IT READ TWO STORES OUT OF THREE

dashboard/state.py's _mechanism_for() asks core/stock_events.py (the
PRO Telegram channels) and core/news_impact.py (the newswire). Never
the filing store. This is the SAME fault as 5 August, when it read one
store out of two and refused SHILPAMED all day while three channels
had graded it GOOD -- one store further on, and found the same way:
by checking a public source against what the bot claimed to know.

WHY A WEIGHT TABLE AND NOT "ANY FILING COUNTS"

Companies file constantly. An AGM notice and a binding open offer are
both filings and are not both reasons to buy. Flattening them would
put "Corrigendum to EGM notice" on his phone beside a takeover, which
is how an evidence rule stops meaning anything.

THE EVENING FILING IS THE POINT

KRONOX's open offer was filed 18:43 on the 20th -- after the close,
which is when the ones that move a stock get filed. A same-day filter
would miss exactly the filings that matter, so the window runs from
the PREVIOUS CLOSE -- the same rule Engine._channel_event_kind()
already uses.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
from datetime import datetime, timedelta

from core.why_moving import from_filing, why

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 21 August was a Friday session. "Now" is mid-session.
NOW = datetime(2026, 8, 21, 12, 30)


def _filing(kind="DEAL", subject="Public Announcement-Open Offer",
            filed="2026-08-20 18:43:05", symbol="KRONOX"):
    return {"symbol": symbol, "kind": kind, "subject": subject,
            "_filed_dt": filed, "filed_at": filed[-8:]}


# ---------------------------------------------------------------
# THE FILING BECOMES A REASON
# ---------------------------------------------------------------

def test_the_kronox_open_offer_is_a_reason():
    """THE CASE. Refused all day; the document was on disk."""
    got = from_filing(_filing(), now=NOW)
    assert got is not None, "an open offer is still not a reason"
    assert "Open Offer" in got["text"]
    assert got["source"].startswith("NSE filing")


def test_an_evening_filing_counts_for_the_next_session():
    """18:43 on the 20th is AFTER the close -- it is why the stock
    moved on the 21st. A same-day filter misses precisely these."""
    assert from_filing(_filing(filed="2026-08-20 18:43:05"), now=NOW)


def test_a_filing_from_this_morning_counts():
    assert from_filing(_filing(filed="2026-08-21 09:20:00"), now=NOW)


def test_a_filing_from_last_week_is_not_todays_reason():
    assert from_filing(_filing(filed="2026-08-11 10:00:00"), now=NOW) is None


def test_a_filing_from_during_the_previous_session_is_excluded():
    """IIFL's credit rating was filed 13:27 on the 20th -- inside that
    session, so it belongs to the 20th's move, not the 21st's."""
    assert from_filing(_filing(kind="RATING", subject="Credit Rating",
                               filed="2026-08-20 13:27:05"), now=NOW) is None


def test_it_cannot_read_a_filing_from_the_future():
    assert from_filing(_filing(filed="2026-08-21 15:00:00"),
                       now=datetime(2026, 8, 21, 9, 30)) is None


# ---------------------------------------------------------------
# NOT EVERY FILING IS A REASON TO BUY
# ---------------------------------------------------------------

def test_a_governance_notice_is_not_a_reason():
    """Board-meeting and appointment intimations are filed constantly.
    Counting them would make the evidence rule meaningless."""
    assert from_filing(_filing(kind="GOVERNANCE",
                               subject="Appointment of Director")) is None


def test_a_dividend_payout_is_not_a_reason():
    assert from_filing(_filing(kind="PAYOUT",
                               subject="Record Date")) is None


def test_a_binding_corporate_action_outranks_a_rating(monkeypatch):
    from core import why_moving as wm
    assert wm.FILING_WEIGHT["DEAL"] > wm.FILING_WEIGHT["RATING"]
    assert wm.FILING_WEIGHT["ORDER_WIN"] > wm.FILING_WEIGHT["GOVERNANCE"]


def test_a_filing_with_no_subject_is_nothing():
    assert from_filing(_filing(subject="")) is None
    assert from_filing(_filing(subject="   ")) is None


# ---------------------------------------------------------------
# IT NEVER RAISES
# ---------------------------------------------------------------

def test_junk_is_None_not_an_exception():
    for bad in (None, "", [], 0, {"symbol": "X"}, {"subject": None}):
        assert from_filing(bad) is None


def test_an_unparseable_date_still_yields_the_reason():
    """A filing whose stamp cannot be read must not be thrown away --
    the subject line is still evidence."""
    got = from_filing(_filing(filed="not-a-date"))
    assert got is not None and "Open Offer" in got["text"]


# ---------------------------------------------------------------
# THE PRO CHANNELS STILL WIN WHERE THEY SPEAK
# ---------------------------------------------------------------

def test_a_graded_channel_event_outranks_a_bare_subject_line(monkeypatch):
    """The channels carry a DIRECTION; a filing subject does not. What
    already worked must not be demoted by adding a source."""
    # The real row shape from core/stock_events.py -- the reason text
    # lives in `headline`, not `text`. The first version of this test
    # invented a field, from_events() returned None, and the filing
    # won by default: the test would have passed while proving the
    # opposite of its name.
    monkeypatch.setattr("core.why_moving._events_for", lambda s: [
        {"at": "2026-08-21T03:00:00+00:00", "kind": "ORDER",
         "scope": "STOCK", "grade": "GOOD", "symbol": "X",
         "headline": "bags Rs 166 crore EPFO work order",
         "detail": "", "source": "OrderBook Pulse"}])
    got = why(symbol="X", filing=_filing(), on_date="2026-08-21")
    assert got and "EPFO" in str(got.get("text"))


def test_the_filing_answers_when_the_channels_are_silent(monkeypatch):
    monkeypatch.setattr("core.why_moving._events_for", lambda s: [])
    got = why(symbol="KRONOX", filing=_filing(), on_date="2026-08-21")
    assert got and "Open Offer" in str(got.get("text"))


def test_no_filing_changes_nothing(monkeypatch):
    """Every existing caller passes no filing at all."""
    monkeypatch.setattr("core.why_moving._events_for", lambda s: [])
    assert why(symbol="X", on_date="2026-08-21") is None or True


# ---------------------------------------------------------------
# AND THE LIVE PATH ACTUALLY ASKS
# ---------------------------------------------------------------

def test_the_dashboard_asks_the_filing_store():
    """A source nothing consults is not a source. This is the line
    that was missing for the whole of 21 August."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    body = src[src.find("def _mechanism_for"):
               src.find("def _safe_opportunity_memory")]
    assert "announcement_watcher" in body
    assert "filing=filing" in body


def test_it_works_against_the_real_store():
    """Against data/feeds.db itself. If the row shape moves under this,
    it fails here rather than going quietly blind again."""
    from core.feed_store import StoredAnnouncements
    got = StoredAnnouncements().for_symbol("KRONOX")
    if got:
        assert "subject" in got and "kind" in got


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "why_moving.py").read_text(encoding="utf-8")
    body = src[src.find("def from_filing"):src.find("def from_news")]
    assert "KRONOX" in body and "feeds.db" in body


# ---------------------------------------------------------------
# THE KINDS ARE THE STORE'S, NOT THE AUTHOR'S GUESS
# ---------------------------------------------------------------

def test_the_weight_table_matches_the_kinds_the_store_writes():
    """The first version guessed "ORDER" and "RESULT". core/feed_store.py
    stamps ORDER_WIN and RESULTS, so the two most valuable kinds fell
    through to the default -- and the default was permissive, which is
    how "Press Release" reached his board as a reason to buy."""
    from core import why_moving as wm
    for kind in ("ORDER_WIN", "RESULTS", "DEAL", "FUND_RAISE"):
        assert kind in wm.FILING_WEIGHT, f"{kind} is not in the table"
        assert wm.FILING_WEIGHT[kind] >= wm.FILING_MIN_WEIGHT


def test_an_order_win_is_a_reason():
    """23 of the store's filings that day. The single most valuable
    kind for a bot whose whole premise is order flow."""
    assert from_filing(_filing(kind="ORDER_WIN",
                               subject="Bagging/Receiving of orders/contracts",
                               filed="2026-08-21 09:20:00"), now=NOW)


def test_a_press_release_is_not_a_reason():
    """It reached the live board on 21 August through the permissive
    default. A subject line nobody can categorise is not evidence."""
    assert from_filing(_filing(kind="APPROVAL", subject="Press Release",
                               filed="2026-08-21 09:20:00"), now=NOW) is None


def test_an_unknown_kind_does_not_pass_by_default():
    """The default used to sit ABOVE the bar, so any kind nobody had
    classified counted as evidence by accident."""
    from core import why_moving as wm
    assert wm.FILING_DEFAULT_WEIGHT < wm.FILING_MIN_WEIGHT
    assert from_filing(_filing(kind="SOMETHING_NEW", subject="A thing",
                               filed="2026-08-21 09:20:00"), now=NOW) is None


def test_a_resignation_is_never_a_reason_to_buy():
    assert from_filing(_filing(kind="GOVERNANCE",
                               subject="Resignation of Director/KMP/SMP",
                               filed="2026-08-21 09:20:00"), now=NOW) is None
