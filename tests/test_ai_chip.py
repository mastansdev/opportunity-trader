"""
==========================================================
The model's view is visible, and worth nothing
==========================================================

Staircase step 2, out of the four written down in config.py:

    1  the model reads news and says what it means. Recorded.
    2  its view becomes a why-chip. VISIBLE, still not scored.   <-- here
    3  its view MOVES THE SCORE.
    4  it chooses between simultaneous breakouts.

WHY STEP 3 IS NOT THIS FILE
---------------------------
On 30 July 2026 the bot's own arithmetic reported +Rs 9,498 on a day
it really lost Rs 11,239. An unchecked model stacked on an unchecked
scorer is two things nobody can audit, and there is no honest way to
skip the measurement. Every verdict is stored beside its event so
tools/refused_review.py can ask, in a fortnight: when it said
POSITIVE, what did the stock actually do?

THE PART THAT PAYS FOR ITSELF IMMEDIATELY
-----------------------------------------
UNRELATED. The keyword matcher produced 22 wrong pairings out of 142,
and they were on screen as reasons:

    POWERGRID  "Vikran wins a subcontract FROM PowerGrid"
    URBANCO    "Afcons secures Rs 900 crore"
    NMDC  x3   "GMDC reports Q1 results"
    SBC        "Texmaco Rail wins an order"

POWERGRID is the CUSTOMER. The panel was crediting the buyer with
winning its own order. The model's first useful act is REMOVING a
wrong chip rather than adding a new one -- and unlike a score change,
that needs no measurement to justify.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.shortlist import ShortlistBuilder


class Events:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=None, hours=None, scope=None):
        return self.rows


def _event(**kw):
    base = {"symbol": "BEL", "kind": "ORDER", "at": "2026-07-31T10:00:00",
            "value_cr": 847.0, "grade": None, "counterparty": None,
            "ai_direction": None, "ai_confidence": None, "ai_reason": None}
    base.update(kw)
    return base


def _rank(events, move=4.0):
    builder = ShortlistBuilder(stock_events=Events(events))
    out = builder.rank([{"symbol": "BEL", "ltp": 250.0, "change_pct": move,
                         "sector": "Defence"}], top=5, today="2026-07-31")
    rows = out.get("rows") or []
    return rows[0] if rows else None


# ---------------------------------------------------------------
# 1. THE CHIP APPEARS
# ---------------------------------------------------------------
def test_a_positive_verdict_becomes_a_chip():
    got = _rank([_event(ai_direction="POSITIVE", ai_confidence=0.8,
                        ai_reason="large defence order lifts the backlog")])
    assert any(w.startswith("AI +:") for w in got["why"]), got["why"]
    assert any("backlog" in w for w in got["why"])


def test_a_negative_verdict_is_marked_as_negative():
    got = _rank([_event(kind="NEWS", value_cr=None,
                        ai_direction="NEGATIVE", ai_confidence=0.8,
                        ai_reason="margin compression despite the profit beat")])
    assert any(w.startswith("AI -:") for w in got["why"]), got["why"]


# ---------------------------------------------------------------
# 2. IT IS WORTH NOTHING -- ON PURPOSE
# ---------------------------------------------------------------
def test_the_verdict_does_not_change_the_score():
    """Step 2, not step 3. If this ever fails, someone has promoted
    the model up the staircase without the measurement that justifies
    it."""
    plain = _rank([_event()])
    with_ai = _rank([_event(ai_direction="POSITIVE", ai_confidence=0.95,
                            ai_reason="huge order")])
    assert plain["score"] == with_ai["score"]


def test_the_verdict_is_not_counted_as_backing():
    """The backing count means "independent things that pushed the
    score UP". A chip worth zero points has not pushed anything, and
    counting it would quietly make every row look better evidenced."""
    plain = _rank([_event()])
    with_ai = _rank([_event(ai_direction="POSITIVE", ai_confidence=0.95,
                            ai_reason="huge order")])
    assert plain["support"] == with_ai["support"]


# ---------------------------------------------------------------
# 3. UNRELATED REMOVES THE EVENT ENTIRELY
# ---------------------------------------------------------------
def test_an_unrelated_event_contributes_nothing_at_all():
    """POWERGRID: "Vikran wins a subcontract FROM PowerGrid". The
    ORDER WIN chip, and its points, must both disappear -- not just
    the AI chip."""
    got = _rank([_event(ai_direction="UNRELATED", ai_confidence=0.95,
                        ai_reason="PowerGrid is the customer here")])
    why = got["why"] if got else []
    assert not any("ORDER WIN" in w for w in why), why
    assert not any(w.startswith("AI ") for w in why), why


def test_an_unrelated_event_does_not_score():
    unrelated = _rank([_event(ai_direction="UNRELATED", ai_confidence=0.9,
                              ai_reason="different company")])
    nothing = _rank([])
    assert unrelated["score"] == nothing["score"], (
        "a story that is not about this company must be worth exactly "
        "as much as no story")


def test_a_real_event_beside_an_unrelated_one_still_counts():
    """The filter must remove the wrong pairing without taking the
    right one with it."""
    got = _rank([
        _event(ai_direction="UNRELATED", ai_reason="different company"),
        _event(at="2026-07-31T11:00:00", kind="RESULT", value_cr=None,
               grade="EXCELLENT"),
    ])
    assert any("PULSE" in w for w in got["why"]), got["why"]


# ---------------------------------------------------------------
# 4. A SHRUG IS NOT A VIEW
# ---------------------------------------------------------------
def test_neutral_is_not_shown():
    """"Affects this company but not clearly either way" is true of
    most news. A chip on every row is how a panel stops being read."""
    got = _rank([_event(ai_direction="NEUTRAL", ai_confidence=0.9,
                        ai_reason="mixed signals")])
    assert not any(w.startswith("AI ") for w in got["why"])


def test_a_low_confidence_verdict_is_not_shown():
    got = _rank([_event(ai_direction="POSITIVE", ai_confidence=0.2,
                        ai_reason="might possibly help")])
    assert not any(w.startswith("AI ") for w in got["why"])


def test_a_verdict_with_no_reason_is_not_shown():
    """The reason IS the chip. A bare direction tells the operator
    nothing he can check."""
    got = _rank([_event(ai_direction="POSITIVE", ai_confidence=0.9,
                        ai_reason=None)])
    assert not any(w.startswith("AI ") for w in got["why"])


# ---------------------------------------------------------------
# 5. NOTHING BREAKS WITHOUT THE MODEL
# ---------------------------------------------------------------
def test_events_with_no_verdict_behave_exactly_as_before():
    """Every row in the database was like this until 31 July, and any
    day the key is missing they all will be again."""
    got = _rank([_event()])
    assert any("ORDER WIN" in w for w in got["why"])
    assert not any(w.startswith("AI ") for w in got["why"])
    assert got["score"] > 0


@pytest.mark.parametrize("junk", ["", "  ", "bullish", "positive!", 7, None])
def test_an_unrecognised_direction_is_ignored_not_guessed(junk):
    got = _rank([_event(ai_direction=junk, ai_confidence=0.9,
                        ai_reason="something")])
    assert not any(w.startswith("AI ") for w in got["why"])
    assert any("ORDER WIN" in w for w in got["why"]), (
        "an unreadable verdict must not suppress the event either -- "
        "only an explicit UNRELATED does that")
