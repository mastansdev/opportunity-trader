"""
==========================================================
Six reads, one line
==========================================================

    "in live markets i cannot see +10/+8 chips right? thats your work
     to make sure the code does the backgorund & show the final output
     to end user with clear case"
                                    -- operator, 2 August 2026

He is right, and it is the argument against everything built this
weekend if it goes unanswered. Ten chips on a fifty-row table at 09:15
is not a screen anybody reads.

So the chain is assembled in the background and the row leads with ONE
line. Nothing is dropped -- the chips collapse behind a "+N", one
click, unchanged.

WHAT THE CHIP SAYS
------------------
    "on display at why? only chips buy , wait , avoid can be used
     right? this is our own bot & we r not selling anything to any one
     at all"
                                    -- operator, 2 August 2026

Three words. He asked four times before I built it.

I had refused, citing SEBI. That was my error: he raised SEBI to
explain why the CHANNELS publish verdicts instead of calls -- they
sell to the public. I turned his own point back on him and applied it
to a private dashboard he built for himself, which is not what the
rule covers.

The reason still exists. It lives on the hover, not on the row.

THE ORDER OF THE STATES IS THE ARGUMENT
---------------------------------------
FLAGGED outranks everything. A ONE-OFF measured -1.61% and beat the
market 28% of the time; letting three agreeing reads bury it is how a
screen flatters itself.

SPLIT outranks ALIGNED. A contradiction is worth more than an
agreement, because the agreement is the part everybody else can see
too. SYRMA: algo said Weak, the audit read the concall and said BEAT
on 67% revenue growth, and the tape did nothing. Measured across the
store the audit contradicts the algorithm ONE TIME IN FOUR.

The Cockpit's own description of itself is "compare every layer, see
disagreements, not an opaque score". A single-word verdict would have
hidden all seventy of them.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

from core.chain import (ALIGNED, AVOID, BUY, FLAGGED, PRICED, SPLIT, THIN,
                        WAIT, call, rank, read, reason, state, summary)


def ev(kind, headline, grade=None):
    return {"kind": kind, "headline": headline, "grade": grade}


BASELINE = ev("EXPECTATION", "EXPECTED NEUTRAL: stable trends expected")
STRONG = ev("RESULT", "PULSE: Excellent results", grade="EXCELLENT")
WEAK = ev("RESULT", "PULSE: Weak results", grade="WEAK")
CLEAN = ev("RESULT", "CLEAN | Rising, Expanding, Healthy", grade="GOOD")
OVERRULE = ev("AI_VERDICT",
              "AI AUDIT OVERRULES: algo said Weak, audit says BEAT")
AGREES = ev("AI_VERDICT", "AI AUDIT BEAT: algo said Good")
UNPRICED = ev("REPORTED", "REPORTED AFTER CLOSE (31 Jul) -- not yet priced")
TAPE_OK = ev("MARKET_ANSWER", "TAPE AGREED: Good result, stock +2.10%")
TAPE_SPLIT = ev("MARKET_ANSWER", "TAPE DISAGREED: Weak result, stock +6.79%")
TOP = ev("SETUP", "CANSLIM EXCEPTIONAL -- 4 of 90 today")
ONE_OFF = ev("RESULT", "ONE-OFF: Dividend income Rs 39.5 Cr", grade="GOOD")


# ---------------------------------------------------------------
# 1. THE FIVE STATES
# ---------------------------------------------------------------
def test_agreeing_reads_are_aligned():
    assert state(read([BASELINE, STRONG, AGREES, TOP])) == ALIGNED


def test_a_contradiction_is_split():
    """SYRMA. The audit read the concall and overruled the grade."""
    assert state(read([BASELINE, WEAK, OVERRULE, TOP])) == SPLIT


def test_a_tape_contradiction_is_also_split():
    assert state(read([BASELINE, WEAK, TAPE_SPLIT])) == SPLIT


def test_a_one_off_outranks_everything_positive_beside_it():
    """THE ONE THAT MATTERS. ONE-OFF measured -1.61% and beat the
    market 28% of the time. Three agreeing reads must not bury it."""
    assert state(read([BASELINE, STRONG, AGREES, TOP, ONE_OFF])) == FLAGGED


def test_a_contradiction_outranks_an_agreement():
    """The agreement is the part everybody else can see too."""
    both = read([BASELINE, STRONG, OVERRULE, TOP])
    assert state(both) == SPLIT
    assert rank(both) > rank(read([BASELINE, STRONG, AGREES, TOP]))


def test_a_tape_that_has_answered_is_priced():
    assert state(read([BASELINE, STRONG, TAPE_OK])) == PRICED


def test_unpriced_beats_priced_even_with_a_tape_reading():
    """A result released after the close has an after-hours reading
    against it and is still unpriced at the open."""
    assert state(read([BASELINE, STRONG, UNPRICED, TAPE_OK])) == ALIGNED


def test_one_read_is_not_a_chain():
    assert state(read([STRONG])) == THIN
    assert state(read([])) == THIN


def test_no_events_means_no_line():
    assert summary([]) is None
    assert summary(None) is None


# ---------------------------------------------------------------
# 2. THE LINE ITSELF
# ---------------------------------------------------------------
def test_the_chip_is_one_word_and_nothing_else():
    """---- 2 August 2026, the fourth time he asked ----

        "on display at why? only chips buy , wait , avoid can be used
         right? this is our own bot & we r not selling anything to any
         one at all"

    Everything read() computes still happens. It decides the word and
    then gets out of the way. An earlier version printed
    "ALIGNED · 4 of 5 reads · not priced yet" on the row, which is a
    sentence, not a call, and he had to say so four times.
    """
    for events in ([BASELINE, STRONG, AGREES, TOP],
                   [BASELINE, WEAK, OVERRULE],
                   [BASELINE, STRONG, ONE_OFF]):
        got = summary(events)
        assert got in (BUY, WAIT, AVOID)
        assert " " not in got


def test_the_why_is_available_but_never_on_the_row():
    """The reason lives on the hover. The row carries the call."""
    facts = read([BASELINE, STRONG, UNPRICED, TOP])
    why = reason(facts)
    assert "not priced yet" in why
    assert "low bar" in why
    # Their own wording, from the CANSLIM guide -- the tier counts how
    # many frameworks agree, so the chip names that rather than calling
    # it a "tier".
    assert "all three frameworks agree" in why
    assert summary([BASELINE, STRONG, UNPRICED, TOP]) == BUY


# ---------------------------------------------------------------
# 3. THE RULES BEHIND THE WORD
# ---------------------------------------------------------------
@pytest.mark.parametrize("events,expected", [
    # AVOID first -- a quality flag outranks every positive read.
    ([BASELINE, STRONG, AGREES, TOP, ONE_OFF], AVOID),
    ([BASELINE, WEAK, ev("AI_VERDICT", "AI AUDIT MISS: algo said Weak")], AVOID),
    # BUY -- positive, nothing flagged, the tape has not answered.
    ([BASELINE, STRONG, TOP], BUY),
    ([BASELINE, CLEAN, UNPRICED], BUY),
    ([BASELINE, WEAK, OVERRULE], BUY),
    # WAIT -- everything else.
    ([BASELINE, STRONG, TAPE_OK], WAIT),
    ([BASELINE, WEAK, OVERRULE, TAPE_SPLIT], WAIT),
    ([STRONG], WAIT),
    ([], WAIT),
])
def test_the_rules_in_the_order_they_are_applied(events, expected):
    assert call(read(events)) == expected


def test_a_quality_flag_beats_three_agreeing_reads():
    """THE ONE THAT MATTERS. ONE-OFF measured -1.61% and beat the
    market 28% of the time. A screen that lets three positives bury it
    is flattering itself."""
    assert call(read([BASELINE, STRONG, AGREES, TOP, UNPRICED, ONE_OFF])) == AVOID


def test_the_audit_overruling_a_weak_grade_is_a_buy():
    """SYRMA. The algorithm said Weak; the audit read the concall and
    found revenue up 67%. Under the grade alone this was skipped."""
    assert call(read([BASELINE, WEAK, OVERRULE, TOP])) == BUY


def test_one_read_is_never_a_buy():
    """One source is an opinion, not a chain."""
    assert call(read([STRONG])) == WAIT
    assert call(read([CLEAN])) == WAIT


# ---------------------------------------------------------------
# 4. NOTHING IS THROWN AWAY
# ---------------------------------------------------------------
def test_the_panel_collapses_the_chips_rather_than_dropping_them():
    """The standing rule: do not throw away any information we are
    receiving. The chips still exist -- they are one click away."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find("if (r.chain) {"):]
    block = block[:block.find("const inline =")]
    assert "badges.concat(trusted, others, warn)" in block
    assert "why-more" in block
    assert "WHY_OPEN.has(r.symbol)" in block


def test_every_call_has_a_colour():
    """BUY loud, AVOID loud, WAIT quiet. The row is readable without
    reading it."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    for name in (BUY, WAIT, AVOID):
        assert re.search(rf"\.chain-{name}\s*\{{", src), f"{name} has no CSS"


def test_the_row_carries_the_state_and_the_sort_key():
    src = open("core/shortlist.py", encoding="utf-8").read()
    for key in ('"chain":', '"chain_state":', '"chain_rank":',
                '"chain_layers":'):
        assert key in src


def test_the_summary_reads_the_same_events_the_chips_did():
    """Fetching them twice would let the line and the chips disagree
    about the same stock -- the one thing a summary must never do."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    assert "events_for_symbol = list(self._events_for(symbol))" in src
    assert "for event in events_for_symbol:" in src
    # The signature grew when today's price and volume were added --
    # see section 7. What matters is that it reads the SAME list the
    # chips were built from, not that the call looks identical.
    assert "chain_read(events_for_symbol" in src


# ---------------------------------------------------------------
# 5. THE SORT KEY IS NOT A SCORE
# ---------------------------------------------------------------
def test_the_chain_rank_never_reaches_the_score():
    """It orders equals. Adding it to the score would be inventing
    points for evidence that has never been measured against price."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    assert "score += chain" not in src
    assert "chain_rank(chain_facts)" in src


def test_more_reads_break_a_tie():
    few = read([BASELINE, STRONG])
    many = read([BASELINE, STRONG, AGREES, TOP])
    assert state(few) == state(many) == ALIGNED
    assert rank(many) > rank(few)


# ---------------------------------------------------------------
# 6. IT HAS TO SURVIVE THE COPY -- 2 August 2026
# ---------------------------------------------------------------
#
# The chain summary was built, tested, stored on the shortlist row --
# and did not appear on screen. dashboard/state.py's decorate() copies
# fields ONE BY ONE from the shortlist hit onto the gainers/losers row,
# so a new key is invisible there until somebody names it.
#
# The identical thing happened to `support` on 31 July: APTUS showed
# "0 backing" beside a score of 13 and three positive chips, because
# the count was never copied. That comment is four lines above the fix
# for this one.
#
# A hand-written copy list is where new work goes to be silently
# dropped. These tests exist so the third time is caught by a machine.

def test_the_call_survives_the_copy_onto_the_gainers_row():
    """THE ONE THAT MATTERS. Built, stored, and invisible."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.find("def decorate(row, direction, rank):"):]
    block = block[:block.find("return out")]
    for key in ("chain", "chain_state", "chain_why"):
        assert f'out["{key}"] = hit.get("{key}")' in block, (
            f"{key} is built by the shortlist and never copied here, so "
            f"it cannot reach the screen")


def test_every_chain_key_the_shortlist_builds_is_copied():
    """Catches the NEXT one rather than this one. If shortlist.py grows
    a chain_* field, decorate() has to carry it or the feature is dead
    on arrival."""
    import re as _re
    short = open("core/shortlist.py", encoding="utf-8").read()
    state = open("dashboard/state.py", encoding="utf-8").read()
    block = state[state.find("def decorate(row, direction, rank):"):]
    block = block[:block.find("return out")]
    built = set(_re.findall(r'"(chain(?:_\w+)?)":\s', short))
    assert built, "the shortlist row no longer carries a chain field"
    missing = [k for k in built if f'out["{k}"]' not in block]
    assert not missing, (
        f"{missing} reach the shortlist row but not the gainers row. "
        f"decorate() copies field by field -- add them there too.")


# ---------------------------------------------------------------
# 7. THE OPERATOR'S RULE IN FULL -- 2 August 2026
# ---------------------------------------------------------------
#
#     "without any thing stock doesn't move, that something is we need
#      to find out + volumes supports the data + ride untill the
#      momentum stays - exit once it gone ruthlessly + repeat the
#      process on only high setups"
#
# Five parts. The chain implemented ONE -- find the catalyst -- and
# called the answer BUY. On the live panel that produced:
#
#     SATIN   -9.95% today   BUY
#     APTUS   -8.50% today   BUY   (carrying "CANSLIM WEAK")
#
# SATIN had a profit beat two sessions earlier and nothing in the chain
# knew what the price had done since. It was reading last night's cards
# and calling it a view on this morning's tape.

from core.chain import (ALREADY_RUN_PCT, FALLING_HARD_PCT,  # noqa: E402
                        VOLUME_CONFIRMS)

WEAK_TIER = ev("SETUP", "CANSLIM WEAK -- 30 of 90 today")


def test_a_falling_knife_is_never_a_buy():
    """THE ONE THAT MATTERS. SATIN, down 9.95%, came back BUY."""
    facts = read([BASELINE, STRONG, TOP], vol_ratio=2.0, change_pct=-9.95)
    assert call(facts) == AVOID
    assert "already been answered" in reason(facts)


def test_the_falling_knife_beats_every_positive_read():
    facts = read([BASELINE, STRONG, AGREES, TOP, UNPRICED],
                 vol_ratio=5.0, change_pct=-6.8)
    assert call(facts) == AVOID


def test_volume_must_support_the_data():
    """"+ volumes supports the data". A catalyst nobody traded is a
    catalyst the market has not accepted yet. WAIT, not AVOID -- the
    story may still be true, it just has not been believed."""
    quiet = read([BASELINE, STRONG, TOP], vol_ratio=0.9, change_pct=2.0)
    assert call(quiet) == WAIT
    assert "nobody has traded the story" in reason(quiet)

    loud = read([BASELINE, STRONG, TOP], vol_ratio=3.0, change_pct=2.0)
    assert call(loud) == BUY
    assert "volume 3.0x confirms" in reason(loud)


def test_the_volume_threshold_is_the_one_the_panel_already_uses():
    """QUIET_MAX in shortlist.py is 1.5 -- "volume at or under this x
    its own normal". The chain must not invent a second number for the
    same idea."""
    from core.shortlist import QUIET_MAX
    assert VOLUME_CONFIRMS == QUIET_MAX


def test_a_poor_chart_is_not_a_buy():
    """APTUS came back BUY carrying "CANSLIM WEAK -- 30 of 90 today".
    The chart layer was read as a bonus when good and ignored when bad.

    The WORDING changed once their guide was read: WEAK means the
    three frameworks disagree, not that the setup is poor. The
    BEHAVIOUR is the same -- it still holds a BUY back, because their
    instruction is "focus on the top one or two names"."""
    facts = read([BASELINE, STRONG, WEAK_TIER],
                 vol_ratio=2.4, change_pct=-1.0)
    assert call(facts) == WAIT
    assert "do not agree" in reason(facts)


def test_a_stock_that_has_already_run_is_not_an_early_bird():
    """"if i bought even a good stock at near Upper Circuit whats the
    use?" The whole chain exists to be early."""
    facts = read([BASELINE, STRONG, TOP], vol_ratio=4.0, change_pct=11.0)
    assert call(facts) == WAIT
    assert "the move has happened" in reason(facts)


def test_missing_price_data_does_not_block_a_buy():
    """Before the first tick there is no move and no ratio. The chain
    must not refuse everything just because the session has not
    started -- that would empty the 09:15 screen."""
    facts = read([BASELINE, STRONG, TOP], vol_ratio=None, change_pct=None)
    assert call(facts) == BUY


@pytest.mark.parametrize("move,expected", [
    (FALLING_HARD_PCT - 0.1, AVOID),
    (FALLING_HARD_PCT + 0.1, BUY),
    (ALREADY_RUN_PCT - 0.1, BUY),
    (ALREADY_RUN_PCT + 0.1, WAIT),
])
def test_the_thresholds_are_where_they_say_they_are(move, expected):
    facts = read([BASELINE, STRONG, TOP], vol_ratio=2.0, change_pct=move)
    assert call(facts) == expected


def test_the_shortlist_hands_the_chain_todays_numbers():
    """Without these the chain reads last night's cards and calls it a
    view on this morning's price."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    assert "vol_ratio=vratio, change_pct=move" in src


# ---------------------------------------------------------------
# 8. THEIR RULES, NOT MINE -- 2 August 2026
# ---------------------------------------------------------------
#
#     "pls make sure to follow the pro channel way in building our own
#      chips. we cannot deviate from NSE & PRO CHANNELS."
#
# From Earnings Pulse's own CANSLIM Ratings guide, verbatim:
#
#   "The rank is how many of these three frameworks are simultaneously
#    aligned"  -- earnings quality, chart structure, gap potential.
#
#   "A stock tagged Weak by Pulse but accompanied by a green 360 brief
#    -- one-off charge, strong guidance, analyst upgrades expected --
#    can still appear in the CANSLIM Ratings list at the discretion of
#    the qualitative layer."
#
#   "Focus on the top one or two names. Width of the list is not width
#    of the opportunity."
#
# I had read the tier as a quality grade. It is a COUNT of agreement,
# and WEAK means the frameworks disagree -- not that the company is
# bad. And I had let one WEAK grade override three other sources,
# which is the bot overruling the publisher.
#
# CONCORDBIO, 1 August: GOOD, MIXED, OK and WEAK on one quarter, a
# CLEAN brief beside them, on the CANSLIM list, up 6.77%. It read
# AVOID.

EXCEPTIONAL = ev("SETUP", "CANSLIM EXCEPTIONAL -- 4 of 90 today")


def test_a_weak_grade_beside_a_clean_brief_is_not_an_avoid():
    """THE ONE THAT MATTERS. Their guide builds for this case on
    purpose; the old rule threw it away."""
    facts = read([WEAK, CLEAN, BASELINE], vol_ratio=2.0, change_pct=6.77)
    assert call(facts) != AVOID


def test_an_uncontested_weak_is_still_an_avoid():
    """Nothing beside it -- no clean brief, no second grade, no audit
    overruling it. That is a weak quarter and it stays AVOID."""
    facts = read([WEAK, BASELINE,
                  ev("AI_VERDICT", "AI AUDIT MISS: algo said Weak")],
                 vol_ratio=2.0, change_pct=1.0)
    assert call(facts) == AVOID


@pytest.mark.parametrize("beside", [CLEAN, STRONG, OVERRULE])
def test_any_second_source_contests_the_weak(beside):
    facts = read([WEAK, beside, BASELINE], vol_ratio=2.0, change_pct=1.0)
    assert call(facts) != AVOID


def test_exceptional_is_a_positive_read_on_its_own():
    """All three frameworks aligned -- earnings quality, chart
    structure and gap potential. Requiring a separate strong grade
    beside it would discard the one layer that checked all three."""
    facts = read([BASELINE, EXCEPTIONAL], vol_ratio=2.0, change_pct=1.0)
    assert facts["all_three"] is True
    assert call(facts) == BUY
    assert "all three frameworks agree" in reason(facts)


def test_canslim_weak_does_not_mean_a_bad_company():
    """"The rank is how many frameworks are aligned." WEAK means they
    disagree. It holds a BUY back -- "focus on the top one or two
    names" -- but it is not a verdict on the company, so never AVOID."""
    facts = read([BASELINE, STRONG, WEAK_TIER],
                 vol_ratio=2.0, change_pct=1.0)
    assert call(facts) == WAIT
    assert "do not agree" in reason(facts)
    assert call(facts) != AVOID


def test_the_top_tier_outranks_a_weak_tier_on_the_same_stock():
    """A stale WEAK row beside today's EXCEPTIONAL must not veto it."""
    facts = read([BASELINE, STRONG, EXCEPTIONAL, WEAK_TIER],
                 vol_ratio=2.0, change_pct=1.0)
    assert call(facts) == BUY


def test_the_one_off_rule_is_untouched():
    """BAJAJFINSV stays AVOID at +6.41%. Whether the profit repeats is
    a different question from whether the frameworks agree, and this
    change must not have loosened it."""
    facts = read([BASELINE, STRONG, EXCEPTIONAL, ONE_OFF],
                 vol_ratio=2.0, change_pct=6.41)
    assert call(facts) == AVOID
