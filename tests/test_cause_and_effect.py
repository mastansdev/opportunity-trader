"""
==========================================================
One story, every stock it hits, and which way
==========================================================

    "whats the use for trader without cause & effect on the stocks?"
    "any one can open telegram , x and see the news, orders, results
     but thats not our aim in building the bot"
    "again why user need to bother on this? provide him the completed
     picture. our bot had complete pipe line from scratch to AI where
     the decision can be build along with direction . why can't we make
     trader life simpler by using advanced mechanism & sorting
     everything"
                                    -- operator, 3 August 2026

THE DAY THIS WAS BUILT FROM
---------------------------
The government suggested scrapping MDR on digital payments. Every part
of the bot did its job:

    09:28  Day Trader Telugu posts it as an IMAGE
           OCR reads it
           the matcher finds PAYTM and MOBIKWIK by name
           core/news_impact.py reasons OUTWARD and adds three companies
           nobody named -- PINELABS, CCAVENUE, FINOPB -- each with a
           written mechanism:

               "Zero MDR removes a key merchant transaction fee revenue
                stream for Paytm's payments business"       conf 0.70
               "Payment gateway revenue tied to merchant fees shrinks
                if MDR cannot be charged"                   conf 0.55

    09:42  News Pulse finally carries the same story

Fourteen minutes of edge, five stocks, reasoning for each. He learned
about MDR from the news, because all of it went into a database and
the screen showed him thirty-nine panels.

AND THE TWO READERS DISAGREED
-----------------------------
core/news_impact.py said NEGATIVE for PAYTM -- no MDR, no fee revenue.
core/ai_news.py said POSITIVE at 0.75 -- lower friction, more volume.
The tape rallied. The AI reader was right; the rule engine was wrong,
five times over.

The first build of this panel printed that argument on screen under
the word CONTESTED:

    "i do not want user to trouble with some highfive name ("tape
     agrees / disagrees", "contested") ... let the background work as
     required but on dashboard end user will see the impacted direction
     of the impacted stock & JUST BUY / SELL"

He is right, and the MDR story is why. Under that panel the action on
offer for all five names was SHORT, into a rally, with a word he was
expected to decode first. A split between the readers means the bot has
no direction, and a stock with no direction gets NO ROW. It is dropped
in build_causes, before the payload exists.

THE TAPE AND THE SPLIT STILL RUN
--------------------------------
Every affected stock is still checked against what it is actually
doing -- "volumes supports the data", his own rule, applied to news.
That check decides the ORDER of the list and the disagreement decides
what is withheld from it. Neither is printed. They are the bot's
reasoning, and reasoning is background work.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


class Impact:
    """Stands in for core/news_impact.py."""

    def __init__(self, stories):
        self.stories = stories
        self.asked = None

    def recent(self, limit=20, hours=None):
        self.asked = hours
        if isinstance(self.stories, Exception):
            raise self.stories
        return self.stories


class Events:
    def __init__(self, rows=None):
        self.rows = rows or []

    def recent(self, hours=None, **kw):
        return self.rows


def state(stories, ai_rows=None):
    st = DashboardState.__new__(DashboardState)
    st.news_impact = Impact(stories)
    st.stock_events = Events(ai_rows)
    return st


def hit(symbol, direction="NEGATIVE", conf=0.7, why="because"):
    return {"symbol": symbol, "direction": direction,
            "confidence": conf, "reason": why}


# The real MDR story, as core/news_impact.py stored it.
MDR = {
    "headline": "The government has suggested no Merchant Discount Rate "
                "(MDR) on digital payment modes",
    "at": "2026-08-03T09:28:00", "source": "Day Trader Telugu",
    "positive": [],
    "negative": [
        hit("PAYTM", conf=0.70, why="Zero MDR removes a key merchant "
                                    "transaction fee revenue stream"),
        hit("MOBIKWIK", conf=0.65, why="No MDR eliminates merchant fee income"),
        hit("PINELABS", conf=0.60, why="Pine Labs loses transaction-fee revenue"),
        hit("CCAVENUE", conf=0.55, why="Payment gateway revenue shrinks"),
        hit("FINOPB", conf=0.40, why="Zero MDR reduces fee-based income"),
    ],
}


def tape(**moves):
    """change_pct per symbol, split into the two lists the panel reads."""
    rows = [{"symbol": s, "change_pct": p, "moving": abs(p) > 1,
             "recent_pct": p / 2} for s, p in moves.items()]
    return {"gainers": [r for r in rows if r["change_pct"] >= 0],
            "losers": [r for r in rows if r["change_pct"] < 0]}


# ---------------------------------------------------------------
# 1. THE FAN-OUT REACHES THE SCREEN
# ---------------------------------------------------------------
def test_one_story_produces_every_stock_it_hits():
    got = state([MDR]).build_causes(tape(PAYTM=-3.4))
    assert len(got["rows"]) == 1
    assert got["rows"][0]["n_stocks"] == 5


def test_companies_the_message_never_named_are_included():
    """PINELABS, CCAVENUE and FINOPB appear nowhere in the headline.
    That reasoning is the whole point -- a feed cannot do it."""
    got = state([MDR]).build_causes(tape())
    names = {s["symbol"] for s in got["rows"][0]["stocks"]}
    assert {"PINELABS", "CCAVENUE", "FINOPB"} <= names


def test_every_stock_carries_its_mechanism():
    """     "without any thing stock doesn't move, that something is we
             need to find out"   """
    got = state([MDR]).build_causes(tape())
    for stock in got["rows"][0]["stocks"]:
        assert stock["why"], stock["symbol"]


def test_the_most_confident_leads():
    got = state([MDR]).build_causes(tape())
    assert got["rows"][0]["stocks"][0]["symbol"] == "PAYTM"


# ---------------------------------------------------------------
# 2. THE TAPE IS THE ARBITER
# ---------------------------------------------------------------
def test_a_stock_falling_on_bad_news_reads_as_confirmed():
    got = state([MDR]).build_causes(tape(PAYTM=-3.4))
    paytm = next(s for s in got["rows"][0]["stocks"] if s["symbol"] == "PAYTM")
    assert paytm["tape_agrees"] is True


def test_a_stock_rising_on_bad_news_reads_as_disagreeing():
    """Computed, never printed. The story says down and the market says
    up; that gap sinks the story down the list instead of being drawn
    as a word he has to interpret."""
    got = state([MDR]).build_causes(tape(PAYTM=2.2))
    paytm = next(s for s in got["rows"][0]["stocks"] if s["symbol"] == "PAYTM")
    assert paytm["tape_agrees"] is False


def test_no_price_is_not_disagreement():
    """"we have no quote" and "the market disagrees" are different
    sentences, and only one of them is evidence."""
    got = state([MDR]).build_causes(tape())
    assert all(s["tape_agrees"] is None for s in got["rows"][0]["stocks"])


def test_good_news_confirms_on_a_rise():
    # Two stocks, not one -- a story that reaches a single company is
    # news about that company and this panel now drops it. See
    # test_one_company_is_not_a_cause below.
    story = dict(MDR, negative=[],
                 positive=[hit("X", "POSITIVE"), hit("Y", "POSITIVE")])
    got = state([story]).build_causes(tape(X=3.0, Y=2.0))
    assert got["rows"][0]["stocks"][0]["tape_agrees"] is True


# ---------------------------------------------------------------
# A CAUSE HAS TO HAVE EFFECTS, 3 August 2026
# ---------------------------------------------------------------
#
#     "WHY THINGS ARE MOVING ... showing like same the news i do not
#      want this type at all. once you check u will get better clarity
#      than i say. pls check"
#
# Checked. Read out of the real news_memory.db, eleven of the twelve
# stories in this panel were a single company's own earnings --
# #BUTTERFLY, #SAMHI, #THOMASCOOK -- which the News panel and Filed
# Today already carry, with a button. The panel was the same list a
# third time.
#
# The twelfth was the reason this panel exists: a concall saying
# telecom towers are moving from lead-acid to lithium-ion reached
# INDUSTOWER, GRAVITA and POCL. Two of those three are companies the
# message never names.
def test_one_company_is_not_a_cause():
    solo = dict(MDR, negative=[hit("BUTTERFLY")], positive=[])
    assert state([solo]).build_causes(tape())["rows"] == []


def test_a_story_that_reaches_a_second_company_is_kept():
    chain = dict(MDR, positive=[],
                 negative=[hit("INDUSTOWER"), hit("GRAVITA")])
    got = state([chain]).build_causes(tape())
    assert len(got["rows"]) == 1
    assert got["rows"][0]["n_stocks"] == 2


def test_a_routing_note_is_not_used_as_the_headline():
    """     The best row this panel produced all day arrived titled
            "INDUSTOWER - Concall Recording -> Concall Transcript",
            while the thing that moved three stocks was written on the
            rows underneath."""
    chain = dict(MDR,
                 headline="\U0001F504 #INDUSTOWER — Concall Recording "
                          "→ Concall Transcript + Concall Summary",
                 positive=[],
                 negative=[hit("INDUSTOWER", why="Telecom towers shifting "
                                                 "from lead-acid to lithium-ion"),
                           hit("GRAVITA", why="Lead demand falls")])
    got = state([chain]).build_causes(tape())
    headline = got["rows"][0]["headline"]
    assert "Concall Recording" not in headline
    assert "lithium-ion" in headline


def test_a_real_headline_is_left_alone():
    got = state([dict(MDR, negative=MDR["negative"][:2])]).build_causes(tape())
    assert "Merchant Discount Rate" in got["rows"][0]["headline"]


def test_a_story_the_market_is_acting_on_outranks_one_it_ignores():
    quiet = dict(MDR, headline="nobody cares",
                 negative=[hit("ZZQUIET")], positive=[])
    got = state([quiet, MDR]).build_causes(tape(PAYTM=-3.4, MOBIKWIK=-2.1))
    assert "MDR" in got["rows"][0]["headline"]


# ---------------------------------------------------------------
# 3. WHEN THE TWO READERS SPLIT, THE BOT SAYS NOTHING
# ---------------------------------------------------------------
#
#   "i do not want user to trouble with some highfive name ("tape
#    agrees / disagrees", "contested") ... let the background work as
#    required but on dashboard end user will see the impacted direction
#    of the impacted stock & JUST BUY / SELL"
#                                   -- operator, 3 August 2026
#
# The first build printed the disagreement under the word CONTESTED and
# let him referee it. On the MDR story that meant offering a SHORT on
# five stocks that then rallied. A split means this bot has no
# direction, and no direction means no row.
def test_a_stock_the_two_readers_split_on_is_withheld():
    ai = [{"symbol": "PAYTM", "ai_direction": "POSITIVE"}]
    got = state([MDR], ai_rows=ai).build_causes(tape(PAYTM=-3.4))
    shown = {s["symbol"] for s in got["rows"][0]["stocks"]}
    assert "PAYTM" not in shown
    assert got["rows"][0]["n_stocks"] == 4


def test_the_disagreement_is_still_recorded_for_scoring():
    """Withheld from the screen, kept in the payload. core/outcomes.py
    has to be able to grade which reader was right -- and on MDR the AI
    reader was."""
    ai = [{"symbol": "PAYTM", "ai_direction": "POSITIVE"}]
    got = state([MDR], ai_rows=ai).build_causes(tape(PAYTM=-3.4))
    assert got["rows"][0]["withheld"] == ["PAYTM"]
    assert got["rows"][0]["contested"] is True


def test_a_story_where_every_stock_is_split_disappears_entirely():
    ai = [{"symbol": h["symbol"], "ai_direction": "POSITIVE"}
          for h in MDR["negative"]]
    assert state([MDR], ai_rows=ai).build_causes(tape())["rows"] == []


def test_agreement_is_not_treated_as_a_dispute():
    ai = [{"symbol": "PAYTM", "ai_direction": "NEGATIVE"}]
    got = state([MDR], ai_rows=ai).build_causes(tape())
    paytm = next(s for s in got["rows"][0]["stocks"] if s["symbol"] == "PAYTM")
    assert paytm["contested_by_ai"] is False


def test_no_second_opinion_is_not_a_dispute_either():
    got = state([MDR], ai_rows=[]).build_causes(tape())
    assert got["rows"][0]["contested"] is False
    assert got["rows"][0]["n_stocks"] == 5


def test_the_disagreement_is_never_averaged_away():
    """Two readers splitting is information. A single blended number
    would destroy it and look more certain than either input."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.find("def build_causes"):src.find("def _ai_direction")]
    assert "contested" in block
    # COMMENTS STRIPPED. 4 August 2026 -- this went red because an
    # unrelated comment elsewhere in the slice used the word "average"
    # in a sentence. Six times now a test on this project has asserted
    # against prose and been wrong. What must not blend the two readers
    # is the CODE.
    code = "\n".join(line for line in block.splitlines()
                     if not line.strip().startswith("#"))
    for blend in ("mean(", "average", "/ 2)"):
        assert blend not in code, blend


# ---------------------------------------------------------------
# 4. IT NEVER TAKES THE SCREEN DOWN
# ---------------------------------------------------------------
def test_an_unreadable_impact_store_is_survivable():
    got = state(RuntimeError("locked")).build_causes(tape())
    assert got["rows"] == []
    assert "locked" in got["note"]


def test_no_impact_engine_at_all():
    st = DashboardState.__new__(DashboardState)
    st.news_impact = None
    st.stock_events = None
    assert st.build_causes({})["rows"] == []


def test_a_story_with_no_stocks_is_dropped():
    """A headline with nothing attached is a feed item, and he can read
    those on Telegram."""
    bare = dict(MDR, positive=[], negative=[])
    assert state([bare]).build_causes(tape())["rows"] == []


def test_it_only_looks_at_todays_stories():
    st = state([MDR])
    st.build_causes(tape())
    assert st.news_impact.asked == DashboardState.CAUSE_HOURS


def test_the_list_stays_short():
    many = [dict(MDR, headline=f"story {i}") for i in range(20)]
    got = state(many).build_causes(tape())
    assert len(got["rows"]) <= DashboardState.CAUSE_MAX


# ---------------------------------------------------------------
# 5. IT REACHES THE PAGE, WITH BUTTONS
# ---------------------------------------------------------------
def _html():
    return open("dashboard/static/index.html", encoding="utf-8").read()


def test_the_causes_are_in_the_payload_and_drawn():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"causes": self.build_causes(gainers_losers),' in src
    html = _html()
    assert "function renderCauses" in html
    assert "renderCauses(snap.causes)" in html
    assert 'id="otCause"' in html


def test_every_affected_stock_has_a_button():
    """A row he cannot act on wasted his time -- the same complaint that
    fixed TURNED AROUND, the watchlist and search."""
    html = _html()
    block = html[html.find("function renderCauses"):]
    block = block[:block.find("function otGradeChip")]
    assert "data-short=" in block and "data-buy=" in block
    assert "data-qtyfor=" in block


def test_bad_news_gets_sell_and_good_news_gets_buy():
    html = _html()
    block = html[html.find("function renderCauses"):]
    block = block[:block.find("function otGradeChip")]
    assert 'var down = s.direction === "NEGATIVE";' in block
    assert ">SELL</button>" in block and ">BUY</button>" in block


def test_the_screen_never_shows_the_bot_arguing_with_itself():
    """     "do u really think the user can able to understand the words
             & act on it? even if he understand why bot needs to show ?"

    The direction IS the button. A row does not need HURTS written above
    a SELL, and it must never ask him to settle a disagreement between
    two of my own modules."""
    html = _html()
    block = html[html.find("function renderCauses"):]
    block = block[:block.find("function otGradeChip")]
    for word in ("HURTS", "HELPS", "CONTESTED", "tape agrees",
                 "tape disagrees", "confidence", "conviction"):
        # Comments explain WHY these are gone; only emitted markup counts.
        emitted = [ln for ln in block.splitlines()
                   if word in ln and not ln.strip().startswith("//")]
        assert not emitted, (word, emitted)


def test_the_withheld_list_is_never_drawn():
    """It exists for core/outcomes.py, not for him."""
    html = _html()
    block = html[html.find("function renderCauses"):]
    block = block[:block.find("function otGradeChip")]
    assert "withheld" not in block
    assert "ai_says" not in block


def test_the_panel_sits_above_his_positions():
    html = _html()
    assert html.index('id="otCause"') < html.index('id="otBook"')
