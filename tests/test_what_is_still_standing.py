"""
==========================================================
"Rs 15,840 crore order, fourteen sessions ago"
==========================================================

    "this is not measurement on intraday or long term move, this is
     real company order & this 'Rs 15,840 crore order, fourteen
     sessions ago' is worth tracking"
                                -- the operator, 5 September 2026

WORTH TRACKING, NOT WORTH TRADING, and the difference is the whole
design. The memory was asked before any of this was built:

    what followed, by kind        n      median next session
    ORDER                       454                   +0.01%
    NEWS                      4,150                   -0.20%
    RESULT                    2,092                   -0.81%

The event alone is worth nothing. And the big-order band does not
survive inspection -- nine rows above Rs 10,000 cr, of which THREE are
real orders; the rest are an investor presentation classified as an
order, an acquisition approach, and Welspun's own filing landed on a
second company. Three is not a rule.

Keeping such an order alive as a GATE was measured too. At Rs 10,000 cr
held ten sessions it admits 68 extra stock-days, 11 of which move more
than 3%, median -0.02%. One or two candidates a day, mostly going
nowhere, into a queue already 84 to 400 deep against five seats. More
candidates is not the constraint.

SO NOTHING HERE CHANGES WHAT THE BOT MAY BUY. why_moving.STALE_REASON_
HOURS is still 24 and no gate imports this. It is a SENTENCE, on the
same footing as the result chips: when WELCORP is up 4.7% he can read
"Rs 15,840 cr order, 10 sessions ago" beside it and decide himself,
instead of reading "nothing published, volume 4.1" while the cause sits
in this bot's own store.

TWO GUARDS, both found by building it and looking at the output.

  THE HEADLINE MUST NAME THE COMPANY. The first run put the same
  sentence on four stocks -- WELCORP, WEALTH, NUVAMA and LANDMARK --
  because Welspun's filing preamble ("we wish to inform the Exchange of
  a landmark...") names nobody, and LANDMARK and WEALTH are English
  words that are also tickers. Both are in _WORD_TICKERS now, and this
  asks the LIVE matcher rather than keeping a second naming rule that
  would not know that.

  IT MUST STILL READ AS AN ORDER TODAY. The store holds rows filed by
  older code: JNPR's Investor Presentation as a Rs 26,231 cr order,
  where 26,231 is a MW capacity target. Today's classifier calls it
  NEWS with no amount, so the bug is fixed at the source and only
  history is wrong -- and history is exactly what a memory reads. The
  row is re-read as it is DRAWN. The store is left alone: rewriting
  stored events to tidy a display is how a record stops being one.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import tempfile
from datetime import date

import pytest

from core import cause_effect as ce


def _events(rows):
    """An events store holding just these."""
    path = os.path.join(tempfile.mkdtemp(), "stock_events.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, symbol TEXT,"
                 " at TEXT, kind TEXT, value_cr REAL, headline TEXT)")
    for sym, at, kind, val, head in rows:
        conn.execute("INSERT INTO events (symbol, at, kind, value_cr,"
                     " headline) VALUES (?,?,?,?,?)",
                     (sym, at, kind, val, head))
    conn.commit()
    conn.close()
    return path


WELSPUN = ("WELCORP", "2026-08-21T03:23", "ORDER", 15840.0,
           "WELSPUN CORP: CO. SECURES LARGEST-EVER SINGLE ORDER IN "
           "COMPANY HISTORY VALUED AT APPROX USD 1.8 BILLION FOR "
           "SUPPLY OF PIPES FROM ITS USA UNIT")

# Welspun's own filing, landed on a second company.
PREAMBLE = ("LANDMARK", "2026-08-21T07:41", "ORDER", 15840.0,
            "Pursuant to Regulation 30 of the SEBI (Listing Obligations "
            "and Disclosure Requirements) Regulations, 2015, we wish to "
            "inform the Exchange of a landmark order")

# An investor presentation, filed as an order, where the figure is a
# capacity target in megawatts.
PRESENTATION = ("JNPR", "2026-08-26T19:45", "ORDER", 26231.0,
                "\U0001F4DD #JNPR - Investor Presentation Period: "
                "2026-06-30 STRATEGY IN PLAIN LANGUAGE Aggressive "
                "scaling of renewable capacity targeting 26,231 MW")

ON = date(2026, 9, 5)


# ------------------------------------------------------------------
# the sentence
# ------------------------------------------------------------------

def test_it_answers_the_welspun_question():
    got = ce.standing_cause("WELCORP", on=ON, events_db=_events([WELSPUN]))
    assert got is not None
    assert got["value_cr"] == 15840.0
    assert got["text"].startswith("Rs 15,840 cr order")
    assert "session" in got["text"]
    # The share of the company is added when the size is known -- see
    # tests/test_how_big_against_the_company.py. The rupee figure and
    # the age are what this test is for, and both survive either way.


def test_the_age_is_counted_in_sessions():
    """"Fourteen sessions ago" is what he said and what a trader
    counts. A fortnight of calendar days spans two weekends and reads
    as older than it is."""
    db = _events([WELSPUN])
    same = ce.standing_cause("WELCORP", on=date(2026, 8, 21),
                             events_db=db)
    assert same["sessions_ago"] == 0
    later = ce.standing_cause("WELCORP", on=ON, events_db=db)
    assert later["sessions_ago"] > same["sessions_ago"]


def test_it_goes_quiet_once_the_cause_is_old():
    assert ce.standing_cause("WELCORP", on=date(2026, 11, 1),
                             events_db=_events([WELSPUN])) is None


def test_a_small_order_is_not_a_standing_cause():
    small = ("ACME", "2026-09-01T10:00", "ORDER", 12.0,
             "ACME LTD: CO RECEIVES ORDER WORTH 12 CRORE")
    assert ce.standing_cause("ACME", on=ON,
                             events_db=_events([small])) is None


def test_an_unknown_stock_is_quiet_not_an_error():
    assert ce.standing_cause("NOSUCH", on=ON,
                             events_db=_events([WELSPUN])) is None


# ------------------------------------------------------------------
# the two guards
# ------------------------------------------------------------------

def test_a_headline_that_names_nobody_is_not_shown():
    """Welspun's filing preamble, landed on Landmark Cars."""
    assert ce.standing_cause("LANDMARK", on=ON,
                             events_db=_events([PREAMBLE])) is None


def test_a_row_that_no_longer_reads_as_an_order_is_not_shown():
    """JNPR's Investor Presentation, stored as a Rs 26,231 cr order."""
    assert ce.standing_cause("JNPR", on=ON,
                             events_db=_events([PRESENTATION])) is None


def test_the_stored_event_is_never_rewritten():
    """Tidying a record to make a display look right is how a record
    stops being a record."""
    db = _events([PRESENTATION])
    ce.standing_cause("JNPR", on=ON, events_db=db)
    conn = sqlite3.connect(db)
    still = conn.execute("SELECT kind, value_cr FROM events").fetchone()
    conn.close()
    assert still == ("ORDER", 26231.0)


# ------------------------------------------------------------------
# the batch the board uses
# ------------------------------------------------------------------

def test_the_batch_agrees_with_the_single_lookup():
    db = _events([WELSPUN, PREAMBLE, PRESENTATION])
    many = ce.standing_causes(on=ON, events_db=db)
    assert set(many) == {"WELCORP"}
    one = ce.standing_cause("WELCORP", on=ON, events_db=db)
    assert many["WELCORP"]["text"] == one["text"]


def test_the_biggest_cause_wins_when_a_stock_has_two():
    db = _events([
        WELSPUN,
        ("WELCORP", "2026-09-02T10:00", "ORDER", 900.0,
         "WELSPUN CORP: CO RECEIVES ORDER WORTH 900 CRORE"),
    ])
    got = ce.standing_causes(on=ON, events_db=db)
    assert got["WELCORP"]["value_cr"] == 15840.0


# ------------------------------------------------------------------
# and what it must NOT touch
# ------------------------------------------------------------------

def test_no_gate_reads_this_except_the_one_that_was_decided():
    """---- THE DECISION WAS REVISITED, ON PURPOSE. 5 Sep 2026. ----

    This test read "no gate reads this" and it caught the hour that one
    did, which is what it was for. The original note said: "if that
    decision is ever revisited it should be a deliberate act, not a
    drift." It was revisited, deliberately, the same evening --

        "why WELCORP is showing Still refused? its a clear winner with
         +3 % right"                             -- the operator

    -- and only after re-measuring with his yardstick rather than mine.
    See tests/test_a_standing_order_opens_the_door.py for the evidence
    and the bar.

    So core/why_moving.py may read it, through exactly one function and
    only when nothing fresher answered. Everything else still may not:
    the ranker, the entry path, the engine and the results gate all get
    their reason from why_moving and have no business asking a memory
    of their own.
    """
    import io
    for path in ("core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/results_gate.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "cause_effect" not in src, \
            f"{path} reads the memory -- that was never decided"

    why = io.open("core/why_moving.py", encoding="utf-8").read()
    assert "from core.cause_effect import standing_reason" in why
    assert "standing_causes" not in why, \
        "why_moving may ask for ONE stock's standing cause, never the "\
        "whole board's -- that is the display's question"


def test_the_stale_window_is_untouched():
    from core.why_moving import STALE_REASON_HOURS
    assert STALE_REASON_HOURS == 24.0


def test_the_board_actually_shows_it():
    """The fault this codebase keeps producing is machinery nothing
    calls -- and this one was caught with the dashboard open: the
    payload carried 36 causes and the page drew none of them."""
    import io
    src = io.open("dashboard/state.py", encoding="utf-8").read()
    assert '"standing_causes": self._standing_causes()' in src
    assert "def _standing_causes" in src


def test_the_page_actually_draws_it():
    """Verified in the browser on the live desk: PURVA and TEJASNET
    carried their causes under the reason line."""
    import io
    page = io.open("dashboard/static/desk.html", encoding="utf-8").read()
    assert "function standingOf" in page, \
        "the page has no way to draw a standing cause"
    assert "standingOf(d, r.symbol)" in page, \
        "standingOf() exists and the row never calls it"
    assert ".op .standing{" in page, \
        "the cause would draw unstyled, indistinguishable from today's news"
